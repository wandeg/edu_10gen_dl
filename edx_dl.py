#!/usr/bin/python
# -*- coding: utf-8 -*-

import glob
import json
import mechanize
import re
import sys
import os.path
from bs4 import BeautifulSoup
from math import floor
from random import random
from urllib import urlencode

from youtube_dl.YoutubeDL import YoutubeDL
from youtube_dl.extractor  import YoutubeIE
from youtube_dl.utils import sanitize_filename
from flask import Flask, render_template, request, redirect, jsonify

import config

app = Flask(__name__)
replace_space_with_underscore = False
base_url = 'https://'+config.DOMAIN
# Dirty hack for differences in 10gen and edX implementation
if 'edx' in config.DOMAIN.split('.'):
    login_url = '/login_ajax'
    article_tags_css_class = 'course honor'
else:
    login_url = '/login'
    article_tags_css_class = 'my-course'

dashboard_url = '/dashboard'
youtube_url = 'http://www.youtube.com/watch?v='
DIRECTORY = os.path.curdir

def makeCsrf():
    t = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    e = 24
    csrftoken = list()
    for i in range(0,e):
        csrftoken.append(t[int(floor(random()*len(t)))])
    return ''.join(csrftoken)

def csrfCookie(csrftoken):
    return mechanize.Cookie(version=0,
            name='csrftoken',
            value=csrftoken,
            port=None, port_specified=False,
            domain=config.DOMAIN,
            domain_specified=False,
            domain_initial_dot=False,
            path='/', path_specified=True,
            secure=False, expires=None,
            discard=True,
            comment=None, comment_url=None,
            rest={'HttpOnly': None}, rfc2109=False)

def cleanString(stringy):
    return stringy.strip()

class EdXBrowser(object):
    def __init__(self, config):
        self._br = mechanize.Browser()
        self._cj = mechanize.LWPCookieJar()
        csrftoken = makeCsrf()
        self._cj.set_cookie(csrfCookie(csrftoken))
        self._br.set_handle_robots(False)
        self._br.set_cookiejar(self._cj)
        self._br.addheaders.append(('X-CSRFToken',csrftoken))
        self._br.addheaders.append(('Referer',base_url))
        self._logged_in = False
        self._fd = YoutubeDL(config.YDL_PARAMS)
        self._fd.add_info_extractor(YoutubeIE())
        self._config = config
        self._alldata = {}

    def login(self):
        try:
            login_resp = self._br.open(base_url + login_url, urlencode({'email':self._config.EMAIL, 'password':self._config.PASSWORD}))
            login_state = json.loads(login_resp.read())
            self._logged_in = login_state.get('success')
            if not self._logged_in:
                print login_state.get('value')
            return self._logged_in
        except mechanize.HTTPError, e:
            sys.exit('Can\'t sign in')

    def list_courses(self):
        self.courses = []
        if self._logged_in:
            dashboard = self._br.open(base_url + dashboard_url)
            dashboard_soup = BeautifulSoup(dashboard.read())
            my_courses = dashboard_soup.findAll('article', article_tags_css_class)
            i = 0
            for my_course in my_courses:
                course_url = my_course.a['href']
                course_name = my_course.h3.text
                
                if self._config.interactive_mode:
                    launch_download_msg = 'Download the course [%s] from %s? (y/n) ' % (course_name, course_url)
                    launch_download = raw_input(launch_download_msg)
                    if (launch_download.lower() == "n"):
                        continue

                i += 1
                courseware_url = re.sub(r'\/info$','/courseware',course_url)
                self.courses.append({'name':course_name, 'url':courseware_url})
                print '[%02i] %s' % (i, course_name)

    def list_chapters(self, course_i):
        self.paragraphs = []
        if course_i < len(self.courses) and course_i >= 0:
            print "Getting chapters..."
            course = self.courses[course_i]
            course_name = course['name']
            print(base_url+course['url'])
            if 'courses' in course['url']:
                courseware = self._br.open(base_url+course['url'])
                courseware_soup = BeautifulSoup(courseware.read())
                chapters = courseware_soup.findAll('div','chapter')
                i = 0
                for chapter in chapters:
                    chapter_name = chapter.find('h3').find('a').text

                    if self._config.interactive_mode:
                        launch_download_msg = 'Download the chapter [%s - %s]? (y/n) ' % (course_name, chapter_name)
                        launch_download = raw_input(launch_download_msg)
                        if (launch_download.lower() == "n"):
                            continue
                    
                    i += 1
                    # print '\t[%02i] %s' % (i, chapter_name)
                    paragraphs = chapter.find('ul').findAll('li')
                    j = 0
                    for paragraph in paragraphs:
                        j += 1
                        par_name = paragraph.p.text
                        par_url = paragraph.a['href']
                        data=(cleanString(course_name), i, j, cleanString(chapter_name), cleanString(par_name), par_url)
                        # print [(i,type(i)) for i in data]
                        self.paragraphs.append(data)
                        # print '\t\t[%02i.%02i] %s' % (i, j, par_name)
                return self.paragraphs
            else:
                return []



config.interactive_mode = ('--interactive' in sys.argv)

if config.interactive_mode:
    sys.argv.remove('--interactive')

if len(sys.argv) >= 2:
    DIRECTORY = sys.argv[-1].strip('"')                
edxb = EdXBrowser(config)
edxb.login()
print 'Found the following courses:'
edxb.list_courses()

@app.route('/download', methods=['POST'])
def download():
        print "\n-----------------------\nStart downloading\n-----------------------\n"
        pars=request.form.getlist("chapters[]")
        items=[par.replace(')',"").replace('(',"").split(',') for par in pars]
        for (course_name, i, j, chapter_name, par_name, url) in items:
            #nametmpl = sanitize_filename(course_name) + '/' \
            #         + sanitize_filename(chapter_name) + '/' \
            #         + '%02i.%02i.*' % (i,j)
            #fn = glob.glob(DIRECTORY + nametmpl)
            nametmpl = os.path.join(DIRECTORY,
                                    sanitize_filename(course_name.encode('utf-8'), replace_space_with_underscore),
                                    sanitize_filename(chapter_name.encode('utf-8'), replace_space_with_underscore),
                                    '%02i.%02i.*' % (int(i), int(j)))
            fn = glob.glob(nametmpl)
            
            if fn:
                print "Processing of %s skipped" % nametmpl
                continue
            print "Processing %s..." % nametmpl
            new_url=base_url+url.encode('utf-8')[2:-1].replace("'","")
            par = edxb._br.open(str(new_url))
            par_soup = BeautifulSoup(par.read())
            contents = par_soup.findAll('div','seq_contents')
            k = 0
            for content in contents:
                #print "Content: %s" % content
                content_soup = BeautifulSoup(content.text)
                try:
                    video_type = content_soup.h2.text.strip()
                    video_stream = content_soup.find('div','video')['data-streams']
                    video_id = video_stream.split(':')[1]
                    video_url = youtube_url + video_id
                    k += 1
                    print '[%02i.%02i.%02i] %s (%s)' % (int(i), int(j), k, par_name, video_type)
                    #f.writelines(video_url+'\n')
                    #outtmpl = DIRECTORY + sanitize_filename(course_name) + '/' \
                    #        + sanitize_filename(chapter_name) + '/' \
                    #        + '%02i.%02i.%02i ' % (i,j,k) \
                    #        + sanitize_filename('%s (%s)' % (par_name, video_type)) + '.%(ext)s'
                    outtmpl = os.path.join(DIRECTORY,
                        sanitize_filename(course_name, replace_space_with_underscore),
                        sanitize_filename(chapter_name, replace_space_with_underscore),
                        '%02i.%02i.%02i ' % (int(i),int(j),k) + \
                        sanitize_filename('%s (%s)' % (par_name, video_type), replace_space_with_underscore) + '.%(ext)s')
                    edxb._fd.params['outtmpl'] = outtmpl
                    edxb._fd.download([video_url])
                except Exception as e:
                    # print "Error: %s" % e
                    pass

        return redirect('/')

@app.route('/listchapters', methods=['POST'])
def displayCourseData():
    courses=request.form.getlist('courses[]')
    for c in courses:
        # print 'Course: ' + str(edxb.courses[c])
        # print 'Chapters:'
        try:
            val=edxb.list_chapters(int(c))
            # print val
            edxb._alldata[c]=val
        except Exception, e:
            print "Error: %s" % e
    return render_template('index.html', chapterlist=edxb._alldata)

@app.route('/')
def main():
        # print 'Downloading to ''%s'' directory' % DIRECTORY
    if edxb.courses:
        print "Processing..."
        return render_template('index.html', courselist=edxb.courses)
    else:
        print "No courses selected, nothing to download"
    


if __name__ == '__main__':
    app.run(debug=True)
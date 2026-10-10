"""Black-box HTTP checks for completion access control using synthetic data and isolated DBs.

Authored against completion-contract v1; the backend is integrated separately.
All fixtures are synthetic, requests stay on the loopback test server, and the
faculty video URL is only compared as a string, never fetched.
"""
from datetime import date
import http.cookiejar
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from pilot.server import make_server

TODAY = date.today().isoformat()

FACULTY_VIDEO = {'n': '1', 'title': 'Synthetic lecture', 'speaker_display': 'Teacher',
                 'url': 'https://example.test/video', 'candidate_modules': 'M01',
                 'mapping_status': 'candidate', 'playback_status': 'unverified'}

DATA = {'modules': [{'module_id': 'M01',
              'module_title': 'Synthetic module',
              'pedagogical_year': '1',
              'clinical_cases': [{'id': 'C1',
                                  'title': 'Synthetic task',
                                  'vignette': 'Prompt',
                                  'questions': 'Why?',
                                  'answer': 'SECRET MODEL SOLUTION',
                                  'sources': []}],
              'oral_discussion_questions': ['Synthetic seminar one'],
              'osce_links': ['S01'],
              'tumorboard_links': ['TB01'],
              'reading': {'guidelines': [{'title': 'Synthetic source',
                                          'url': 'https://example.test/source'}],
                          'lectures': [{'title': 'Archive',
                                        'url': 'https://example.test/archive'}]}}],
 'osce': {'stations': [{'id': 'S01',
                        'title': 'Synthetic station',
                        'task': 'Synthetic station task',
                        'materials': 'Synthetic sheet',
                        'examiner_standard': 'HIDDEN STANDARD',
                        'debrief': 'HIDDEN OSCE DEBRIEF',
                        'checklist': [{'№': '1',
                                       'Критерий': 'Plain CRITERION',
                                       'Баллы': '1',
                                       'Критическая ошибка?': '—'}]}]},
 'tumor_board': {'cases': [{'id': 'TB01',
                            'title': 'Synthetic board',
                            'instruction': 'Synthetic instruction',
                            'stages': [{'stage': 1, 'content': ['Stage one text']},
                                       {'stage': 2, 'content': ['STAGE TWO SECRET']}],
                            'debrief': 'TB DEBRIEF SECRET',
                            'checklist': [{'Критерий': 'TB CRITERION',
                                           'Баллы': '2',
                                           'Комментарий экзаменатора': ''}]}]},
 'questions': [{'id': 'Q0',
                'module': 'M01',
                'stem': 'Synthetic 0',
                'options': ['Wrong', 'Right'],
                'correct': 'B'},
               {'id': 'Q1',
                'module': 'M01',
                'stem': 'Synthetic 1',
                'options': ['Wrong', 'Right'],
                'correct': 'B'},
               {'id': 'Q2',
                'module': 'M01',
                'stem': 'Synthetic 2',
                'options': ['Wrong', 'Right'],
                'correct': 'B'},
               {'id': 'Q3',
                'module': 'M01',
                'stem': 'Synthetic 3',
                'options': ['Wrong', 'Right'],
                'correct': 'B'},
               {'id': 'Q4',
                'module': 'M01',
                'stem': 'Synthetic 4',
                'options': ['Wrong', 'Right'],
                'correct': 'B'},
               {'id': 'Q5',
                'module': 'M01',
                'stem': 'Synthetic 5',
                'options': ['Wrong', 'Right'],
                'correct': 'B'},
               {'id': 'Q6',
                'module': 'M01',
                'stem': 'Synthetic 6',
                'options': ['Wrong', 'Right'],
                'correct': 'B'},
               {'id': 'Q7',
                'module': 'M01',
                'stem': 'Synthetic 7',
                'options': ['Wrong', 'Right'],
                'correct': 'B'},
               {'id': 'Q8',
                'module': 'M01',
                'stem': 'Synthetic 8',
                'options': ['Wrong', 'Right'],
                'correct': 'B'},
               {'id': 'Q9',
                'module': 'M01',
                'stem': 'Synthetic 9',
                'options': ['Wrong', 'Right'],
                'correct': 'B'}]}

class CompletionFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data, self.db = root / 'data.json', root / 'pilot.db'
        self.data.write_text(json.dumps(DATA, ensure_ascii=False))
        self.start_server()
        self.addCleanup(self.close)
        self.a, self.b, self.t = self.login('student-a'), self.login('student-b'), self.login('teacher')
        self.version = self.practice_version = self.get(self.a, '/api/practice/M01')[1]['version']

    def start_server(self):
        self.server = make_server(self.db, 0, self.data)
        self.server.pilot.materials.videos = [dict(FACULTY_VIDEO)]
        self.url = 'http://127.0.0.1:%d' % self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def close(self):
        self.stop()
        self.tmp.cleanup()

    def login(self, name):
        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.assertEqual(self.get(client, '/api/login', {'username': name, 'password': 'demo-' + name})[0], 200)
        return client

    def anonymous(self):
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(self, client, path, body=None):
        headers = {'Content-Type': 'application/json', 'Origin': self.url, 'X-Pilot-Request': '1'}
        req = urllib.request.Request(self.url + path, None if body is None else json.dumps(body).encode(), headers)
        try:
            with client.open(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def state(self, client=None, module='M01'):
        code, body = self.get(client or self.a, '/api/completion/' + module)
        self.assertEqual(code, 200)
        return body

    def submit(self, client=None, **over):
        body = {'module': 'M01', 'version': self.state(client)['version'], 'key': 'sub-1'}
        body.update(over)
        return self.get(client or self.a, '/api/completion/submit', body)

    def answer(self, activity_id, client=None, **over):
        if activity_id == 'S01':
            activity_id = 'P:osce:S01'
        if activity_id.startswith('C'):
            version = self.get(client or self.a, '/api/modules/M01')[1]['version']
            body = {'module':'M01', 'case':activity_id, 'version':version,
                    'answer':'Synthetic answer', 'key':activity_id+'-1'}
            path = '/api/answers'
        else:
            body = {'module':'M01', 'activity':activity_id, 'version':self.practice_version,
                    'answer':'Synthetic answer', 'key':activity_id+'-1'}
            path = '/api/practice/answers'
        body.update(over)
        return self.get(client or self.a, path, body)

    def bind_lecture(self):
        cat = self.get(self.t, '/api/completion/lecture/M01')[1]
        self.lecture_id = cat['candidates'][0]['id']
        self.assertEqual(self.get(self.t, '/api/completion/lecture', {
            'module':'M01', 'materials_version':cat['materials_version'],
            'resource':self.lecture_id, 'key':'bind-1'})[0], 200)

    def open_resource(self, resource):
        m = self.get(self.a, '/api/modules/M01')[1]
        return self.get(self.a, '/api/resources/open', {'module':'M01',
            'version':m['materials']['version'], 'resource':resource})

    def pass_quiz(self, score=7, key='quiz-1'):
        code,q = self.get(self.a, '/api/quizzes/start', {'module':'M01','key':key})
        self.assertEqual(code, 200)
        answers = {x['id']:('B' if i<score else 'A') for i,x in enumerate(q['questions'])}
        code,row = self.get(self.a, '/api/quizzes/submit', {'id':q['id'],'answers':answers})
        self.assertEqual(code,200)
        return row

    def mark(self, row):
        if row['case'].startswith('C'):
            body={'submission_id':row['id'], 'decision':'accepted', 'comment':'Synthetic review','key':'rev-'+str(row['id'])}
            route='/api/reviews'
        else:
            a=self.get(self.t,'/api/practice/submissions/'+str(row['id']))[1]['activity']
            body={'submission_id':row['id'], 'decision':'discussed' if a['kind']=='seminar' else 'accepted',
                  'comment':'Synthetic review','key':'rev-'+str(row['id']), 'meeting_date':TODAY,
                  'marks':{r['id']:r['max_score'] for r in a['rubric']}}
            route='/api/practice/reviews'
        code,result=self.get(self.t,route,body)
        self.assertEqual(code,200,result)
        return result

    def make_ready(self, teacher=True):
        self.bind_lecture()
        self.assertEqual(self.open_resource(self.lecture_id)[0],200)
        self.assertEqual(self.open_resource('guidelines-1')[0],200)
        self.rows={}
        for aid in ('C1','P:seminar:1','P:tb:TB01:1','P:tb:TB01:2'):
            code,row=self.answer(aid)
            self.assertEqual(code,200,row)
            self.rows[aid]=row
            if teacher and aid != 'P:tb:TB01:1':
                self.mark(row)
        self.pass_quiz()
        state=CompletionFixture.state(self)
        self.assertTrue(state['student_ready'],state)
        if teacher:self.assertTrue(state['teacher_ready'],state)
        self.cversion=state['version']
        return state

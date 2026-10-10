"""HTTP checks for written practice using synthetic, nonclinical content and isolated DBs."""
from datetime import date, timedelta
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
SECRETS = ('HIDDEN STANDARD', 'HIDDEN OSCE DEBRIEF', 'CRITERION SECRET')
TB_SECRETS = ('STAGE TWO SECRET', 'STAGE THREE SECRET', 'TB DEBRIEF SECRET', 'TB CRITERION SECRET')
DATA = {
    'modules': [{'module_id': 'M01', 'module_title': 'Synthetic module', 'pedagogical_year': '1',
                 'clinical_cases': [{'title': 'Synthetic task', 'vignette': 'Prompt', 'questions': 'Why?',
                                     'answer': 'SECRET MODEL SOLUTION', 'sources': []}],
                 'oral_discussion_questions': ['Synthetic seminar one', 'Synthetic seminar two'],
                 'osce_links': ['S01', 'S99'], 'tumorboard_links': ['TB01']}],
    'osce': {'stations': [{'id': 'S01', 'title': 'Synthetic station', 'task': 'Synthetic station task',
                           'materials': 'Synthetic sheet', 'examiner_standard': 'HIDDEN STANDARD',
                           'debrief': 'HIDDEN OSCE DEBRIEF', 'checklist': [
                               {'№': '1', 'Критерий': 'Plain CRITERION SECRET', 'Баллы': '1', 'Критическая ошибка?': '—'},
                               {'№': '2', 'Критерий': 'Critical CRITERION SECRET', 'Баллы': '2', 'Критическая ошибка?': 'ДА'}]}]},
    'tumor_board': {'cases': [{'id': 'TB01', 'title': 'Synthetic board', 'instruction': 'Synthetic instruction',
                               'stages': [{'stage': 1, 'content': ['Stage one text', 'Stage one task']},
                                          {'stage': 2, 'content': ['STAGE TWO SECRET']},
                                          {'stage': 3, 'content': ['STAGE THREE SECRET']}],
                               'debrief': 'TB DEBRIEF SECRET',
                               'checklist': [{'Критерий': 'TB CRITERION SECRET', 'Баллы': '2', 'Комментарий экзаменатора': ''}]}]},
}


class PracticeHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data, self.db = root / 'data.json', root / 'pilot.db'
        self.data.write_text(json.dumps(DATA, ensure_ascii=False))
        self.start_server()
        self.addCleanup(self.close)
        self.a, self.b, self.t = self.login('student-a'), self.login('student-b'), self.login('teacher')
        self.version = self.get(self.a, '/api/practice/M01')[1]['version']

    def start_server(self):
        self.server = make_server(self.db, 0, self.data)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
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

    def get(self, client, path, body=None):
        headers = {'Content-Type': 'application/json', 'Origin': self.url, 'X-Pilot-Request': '1'}
        req = urllib.request.Request(self.url + path, None if body is None else json.dumps(body).encode(), headers)
        try:
            with client.open(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def view(self, client=None):
        code, body = self.get(client or self.a, '/api/practice/M01')
        self.assertEqual(code, 200)
        return body, {a['id']: a for a in body['activities']}

    def answer(self, activity_id, client=None, **over):
        body = {'module': 'M01', 'activity': activity_id, 'version': self.version, 'answer': 'Synthetic answer',
                'key': activity_id + '-1'}
        body.update(over)
        return self.get(client or self.a, '/api/practice/answers', body)

    def review(self, sid, client=None, **over):
        body = {'submission_id': sid, 'decision': 'accepted', 'comment': 'ok', 'key': f'rev-{sid}',
                'meeting_date': TODAY, 'marks': {'1': 1, '2': 2}}
        body.update(over)
        return self.get(client or self.t, '/api/practice/reviews', body)

    def test_activity_shapes_and_teacher_view(self):
        body, acts = self.view()
        self.assertEqual(list(acts), ['P:seminar:1', 'P:seminar:2', 'P:osce:S01', 'P:tb:TB01:1', 'P:tb:TB01:2', 'P:tb:TB01:3'])
        self.assertEqual(acts['P:seminar:2']['title'], 'Вопрос к семинару №2')
        self.assertEqual(acts['P:seminar:2']['prompts'], ['Synthetic seminar two'])
        self.assertEqual(acts['P:osce:S01']['prompts'], ['Synthetic station task', 'Synthetic sheet'])
        self.assertEqual(acts['P:tb:TB01:1']['prompts'], ['Stage one text', 'Stage one task'])
        self.assertEqual((acts['P:tb:TB01:2']['group_id'], acts['P:tb:TB01:2']['stage_index'],
                          acts['P:tb:TB01:2']['stage_total']), ('TB01', 2, 3))
        dump = json.dumps(body, ensure_ascii=False)
        for secret in SECRETS + TB_SECRETS:
            self.assertNotIn(secret, dump)
        teacher = self.view(self.t)[1]
        self.assertEqual(teacher['P:osce:S01']['standard'], 'HIDDEN STANDARD')
        self.assertEqual(teacher['P:osce:S01']['rubric'], [
            {'id': '1', 'label': 'Plain CRITERION SECRET', 'max_score': 1, 'critical': False},
            {'id': '2', 'label': 'Critical CRITERION SECRET', 'max_score': 2, 'critical': True}])
        self.assertEqual(teacher['P:tb:TB01:3']['prompts'], ['STAGE THREE SECRET'])
        self.assertEqual(teacher['P:tb:TB01:3']['debrief'], 'TB DEBRIEF SECRET')
        self.assertEqual(teacher['P:tb:TB01:2']['rubric'], [])
        self.assertEqual(self.view(self.t)[0]['drafts'], {})

    def test_tumor_board_stages_unlock_only_after_own_answers(self):
        draft = {'module': 'M01', 'activity': 'P:tb:TB01:1', 'version': self.version, 'text': 'PRIVATE DRAFT'}
        self.assertEqual(self.get(self.a, '/api/practice/drafts', draft)[0], 200)
        body, acts = self.view()
        self.assertEqual(body['drafts'], {'P:tb:TB01:1': 'PRIVATE DRAFT'})
        locked = acts['P:tb:TB01:2']
        self.assertTrue(locked['locked'])
        self.assertEqual([locked[k] for k in ('prompts', 'instruction', 'standard', 'debrief', 'rubric', 'attempts')],
                         [[], '', '', '', [], []])
        self.assertNotIn('PRIVATE DRAFT', json.dumps(self.view(self.b)[0]))
        for path, extra in (('/api/practice/drafts', {'text': 'x'}), ('/api/practice/answers', {'answer': 'x', 'key': 'k'})):
            code, error = self.get(self.a, path, {'module': 'M01', 'activity': 'P:tb:TB01:2', 'version': self.version, **extra})
            self.assertEqual(code, 409)
            self.assertFalse(any(s in json.dumps(error) for s in TB_SECRETS))
        self.assertEqual(self.answer('P:tb:TB01:9')[0], 404)
        self.assertEqual(self.answer('P:tb:TB01:1', version='stale')[0], 409)
        self.assertEqual(self.answer('P:tb:TB01:1')[0], 200)
        body, acts = self.view()
        self.assertEqual(body['drafts'].get('P:tb:TB01:1', ''), '')
        self.assertEqual(acts['P:tb:TB01:2']['prompts'], ['STAGE TWO SECRET'])
        self.assertEqual(acts['P:tb:TB01:2']['instruction'], 'Synthetic instruction')
        self.assertNotIn('STAGE THREE SECRET', json.dumps(body))
        self.assertNotIn('STAGE TWO SECRET', json.dumps(self.view(self.b)[0]))
        self.assertEqual(self.answer('P:tb:TB01:2')[0], 200)
        self.assertNotIn('TB DEBRIEF SECRET', json.dumps(self.view()[0]))
        self.assertEqual(self.answer('P:tb:TB01:3')[0], 200)
        final = self.view()[1]['P:tb:TB01:3']
        self.assertEqual((final['debrief'], final['rubric'][0]['label']), ('TB DEBRIEF SECRET', 'TB CRITERION SECRET'))
        self.server.pilot.practice.versions['M01'] = 'new-version'
        self.version = 'new-version'
        acts = self.view()[1]
        self.assertTrue(acts['P:tb:TB01:2']['locked'])  # old-version answers never unlock a new version
        self.assertEqual(acts['P:tb:TB01:1']['attempts'], [])

    def test_osce_standard_hidden_until_own_submission(self):
        self.get(self.a, '/api/practice/drafts', {'module': 'M01', 'activity': 'P:osce:S01', 'version': self.version, 'text': 'd'})
        self.assertFalse(any(s in json.dumps(self.view()[0]) for s in SECRETS))
        code, row = self.answer('P:osce:S01', student='student-b', role='teacher', logbook=['fake'])
        self.assertEqual((code, row['student'], row['case'], row['logbook']), (200, 'student-a', 'P:osce:S01', []))
        own = self.view()[1]['P:osce:S01']
        self.assertEqual((own['standard'], own['debrief'], len(own['rubric'])), ('HIDDEN STANDARD', 'HIDDEN OSCE DEBRIEF', 2))
        self.assertEqual([r['id'] for r in own['attempts']], [row['id']])
        self.assertFalse(any(s in json.dumps(self.view(self.b)[0]) for s in SECRETS))
        self.assertEqual(self.get(self.b, f'/api/practice/submissions/{row["id"]}')[0], 404)
        self.assertEqual(self.get(self.b, '/api/practice/reviews', {'submission_id': row['id']})[0], 403)

    def test_malformed_answers_and_idempotency(self):
        for over in ({'answer': '   '}, {'answer': 'x' * 20001}, {'answer': 5}, {'key': ''}, {'activity': None},
                     {'module': 'M99'}, {'activity': 'C1'}):
            with self.subTest(over=over):
                self.assertIn(self.answer('P:seminar:1', **over)[0], (400, 404))
        first = self.answer('P:seminar:1')[1]
        self.assertEqual(self.answer('P:seminar:1')[1]['id'], first['id'])
        self.assertEqual(self.answer('P:seminar:1', answer='Changed')[0], 400)
        self.assertEqual(self.answer('P:seminar:1', client=self.t)[0], 403)
        self.assertEqual(len(self.get(self.t, '/api/practice/queue')[1]), 1)

    def test_seminar_decisions_and_student_sees_event(self):
        sid = self.answer('P:seminar:1')[1]['id']
        self.assertEqual(self.review(sid, marks={})[0], 400)  # seminar has no 'accepted'
        self.assertEqual(self.review(sid, decision='discussed', marks={'1': 1})[0], 400)
        self.assertEqual(self.review(sid, decision='returned', comment='', marks={})[0], 400)
        code, event = self.review(sid, decision='discussed', comment='Discussed well', marks={})
        self.assertEqual((code, event['decision'], event['meeting_date'], event['max_score']), (200, 'discussed', TODAY, 0))
        self.assertEqual(self.view()[1]['P:seminar:1']['attempts'][0]['logbook'][0]['id'], event['id'])

    def test_rubric_ranges_critical_guard_and_fake_fields(self):
        sid = self.answer('P:osce:S01')[1]['id']
        for over in ({'marks': {'1': 1}}, {'marks': {'1': 1, '2': 2, '9': 1}}, {'marks': {'1': True, '2': 2}},
                     {'marks': {'1': 1, '2': 3}}, {'marks': {'1': 1, '2': 1}}, {'decision': 'discussed'},
                     {'meeting_date': (date.today() + timedelta(days=1)).isoformat()}, {'meeting_date': 'today'},
                     {'submission_id': str(sid)}):
            with self.subTest(over=over):
                self.assertEqual(self.review(sid, **over)[0], 400)
        code, event = self.review(sid, marks={'1': 0, '2': 2}, teacher='intruder', student='student-b', max_score=99,
                                  rubric=[{'id': '1', 'label': 'fake', 'max_score': 50, 'critical': False}])
        self.assertEqual((code, event['teacher'], event['score'], event['max_score']), (200, 'teacher', 2, 3))
        self.assertEqual(event['rubric'][1]['label'], 'Critical CRITERION SECRET')
        self.assertEqual(self.review(sid, marks={'1': 0, '2': 2})[1]['id'], event['id'])
        self.assertEqual(self.review(sid, marks={'1': 1, '2': 2})[0], 400)
        returned = self.review(sid, key='rev-2', decision='returned', comment='Critical step missed', marks={'1': 1, '2': 0})[1]
        logbook = self.view()[1]['P:osce:S01']['attempts'][0]['logbook']
        self.assertEqual([e['id'] for e in logbook], [event['id'], returned['id']])
        self.assertEqual(self.review(sid, client=self.a, key='s')[0], 403)

    def test_tb_early_stage_needs_explicit_decision_without_rubric(self):
        sid = self.answer('P:tb:TB01:1')[1]['id']
        self.assertEqual(self.review(sid)[0], 400)
        self.assertEqual(self.review(sid, marks={})[0], 200)

    def test_stale_version_history_and_queue(self):
        first = self.answer('P:osce:S01')[1]
        self.assertEqual(self.review(first['id'], decision='returned', comment='Rework', marks={'1': 0, '2': 0})[0], 200)
        second = self.answer('P:osce:S01', key='again', answer='Improved')[1]
        code, view = self.get(self.t, f'/api/practice/submissions/{first["id"]}')
        self.assertEqual(code, 200)
        self.assertEqual([r['id'] for r in view['history']], [second['id'], first['id']])
        self.assertEqual(view['history'][1]['answer'], 'Synthetic answer')
        self.assertEqual(view['activity']['standard'], 'HIDDEN STANDARD')
        self.assertFalse(view['row']['stale'])
        self.server.pilot.practice.versions['M01'] = 'new-version'
        self.assertEqual(self.review(second['id'], marks={'1': 1, '2': 2})[0], 409)
        queue = self.get(self.t, '/api/practice/queue')[1]
        self.assertEqual([(q['id'], q['stale'], q['kind'], q['title']) for q in queue],
                         [(second['id'], True, 'osce', 'Synthetic station'), (first['id'], True, 'osce', 'Synthetic station')])
        own = self.get(self.a, f'/api/practice/submissions/{second["id"]}')[1]
        self.assertEqual((own['current_version'], own['row']['stale']), ('new-version', True))
        self.assertEqual(own['activity']['standard'], '')
        self.assertEqual(own['history'][1]['logbook'][0]['rubric'], [])
        self.assertEqual(self.get(self.a, '/api/practice/queue')[0], 403)

    def test_teacher_assignment_enforced(self):
        sid = self.answer('P:osce:S01')[1]['id']
        self.server.pilot.assignments['teacher'] = set()
        self.assertEqual(self.get(self.t, '/api/practice/M01')[0], 403)
        self.assertEqual(self.get(self.t, f'/api/practice/submissions/{sid}')[0], 403)
        self.assertEqual(self.get(self.t, '/api/practice/queue')[1], [])
        self.assertEqual(self.review(sid, marks={'1': 1, '2': 2})[0], 403)

    def test_clinical_flows_isolated_from_practice(self):
        pid = self.answer('P:osce:S01')[1]['id']
        clinical_version = self.get(self.a, '/api/modules/M01')[1]['version']
        self.get(self.a, '/api/practice/drafts', {'module': 'M01', 'activity': 'P:seminar:2', 'version': self.version, 'text': 'p'})
        module = self.get(self.a, '/api/modules/M01')[1]
        self.assertEqual((module['attempts'], module['drafts']), ([], {}))
        self.assertEqual(self.get(self.t, '/api/queue')[1], [])
        self.assertEqual(self.get(self.a, f'/api/submissions/{pid}')[0], 404)
        self.assertEqual(self.get(self.t, f'/api/submissions/{pid}')[0], 404)
        self.assertEqual(self.get(self.t, '/api/reviews', {'submission_id': pid, 'decision': 'accepted',
                                                          'comment': '', 'key': 'clinical'})[0], 404)
        self.assertEqual(self.get(self.a, '/api/answers', {'module': 'M01', 'case': 'P:osce:S01', 'version': clinical_version,
                                                          'answer': 'x', 'key': 'bypass'})[0], 404)
        cid = self.get(self.a, '/api/answers', {'module': 'M01', 'case': 'C1', 'version': clinical_version,
                                                 'answer': 'Clinical', 'key': 'c1'})[1]['id']
        self.assertEqual(self.get(self.t, f'/api/practice/submissions/{cid}')[0], 404)
        self.assertEqual(self.review(cid, marks={})[0], 404)
        self.assertEqual([r['id'] for r in self.get(self.t, '/api/queue')[1]], [cid])
        self.assertEqual([r['id'] for r in self.get(self.t, '/api/practice/queue')[1]], [pid])
        self.assertEqual(self.get(self.t, '/api/reviews', {'submission_id': cid, 'decision': 'accepted',
                                                          'comment': '', 'key': 'c-ok'})[0], 200)
        self.assertEqual(self.view()[1]['P:osce:S01']['attempts'][0]['logbook'], [])

    def test_survives_restart(self):
        sid = self.answer('P:tb:TB01:1')[1]['id']
        event = self.review(sid, marks={})[1]
        self.stop()
        self.start_server()
        self.a, self.t = self.login('student-a'), self.login('teacher')
        acts = self.view()[1]
        self.assertFalse(acts['P:tb:TB01:2']['locked'])
        self.assertEqual(acts['P:tb:TB01:1']['attempts'][0]['logbook'][0]['id'], event['id'])
        self.assertEqual(self.review(sid, marks={})[1]['id'], event['id'])
        self.assertEqual(self.review(sid, marks={}, comment='different')[0], 400)


if __name__ == '__main__':
    unittest.main()

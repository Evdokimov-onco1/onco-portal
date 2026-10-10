"""HTTP integration checks using synthetic, nonclinical content and isolated DBs."""
import http.cookiejar
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from pilot.server import make_server


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data.json'
        self.db = self.root / 'pilot.db'
        self.data.write_text(json.dumps({'modules': [{'module_id': 'M01', 'module_title': 'Synthetic module',
            'pedagogical_year': '1', 'clinical_cases': [
                {'title': 'Synthetic task', 'vignette': 'Explain your method', 'questions': 'Why?',
                 'answer': 'SECRET MODEL SOLUTION', 'sources': []},
                {'title': 'Another task', 'vignette': 'Another prompt', 'questions': 'How?',
                 'answer': 'SECOND SECRET', 'sources': []}]}]}))
        self.start_server()
        self.addCleanup(self.close)
        self.a = self.client()
        self.b = self.client()
        self.t = self.client()
        for opener, name in [(self.a, 'student-a'), (self.b, 'student-b'), (self.t, 'teacher')]:
            self.assertEqual(self.request(opener, '/api/login', {'username': name, 'password': 'demo-'+name})[0], 200)
        self.version = self.request(self.a, '/api/modules/M01')[1]['version']

    def start_server(self):
        self.server = make_server(self.db, 0, self.data)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def client(self):
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, client, path, body=None, headers=None):
        defaults = {'Content-Type': 'application/json', 'Origin': self.url, 'X-Pilot-Request': '1'}
        defaults.update(headers or {})
        req = urllib.request.Request(self.url+path, data=None if body is None else json.dumps(body).encode(), headers=defaults)
        try:
            with client.open(req, timeout=5) as r:
                raw = r.read()
                return r.status, json.loads(raw) if 'application/json' in r.headers['Content-Type'] else raw.decode()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def answer(self, client=None, **over):
        body = {'module': 'M01', 'case': 'C1', 'version': self.version, 'answer': 'Synthetic own solution', 'key': 'request-1'}
        body.update(over)
        return self.request(client or self.a, '/api/answers', body)

    def test_model_gated_per_student_case_and_version(self):
        before = self.request(self.a, '/api/modules/M01')[1]
        self.assertNotIn('answer', before['cases'][0])
        self.assertEqual(self.answer(answer='   ')[0], 400)
        self.assertNotIn('answer', self.request(self.a, '/api/modules/M01')[1]['cases'][0])
        self.assertEqual(self.answer()[0], 200)
        after = self.request(self.a, '/api/modules/M01')[1]
        self.assertEqual(after['cases'][0]['answer'], 'SECRET MODEL SOLUTION')
        self.assertNotIn('answer', after['cases'][1])
        self.assertNotIn('answer', self.request(self.b, '/api/modules/M01')[1]['cases'][0])
        self.server.pilot.versions['M01'] = 'new-version'
        self.assertNotIn('answer', self.request(self.a, '/api/modules/M01')[1]['cases'][0])
        self.assertEqual(self.answer(key='new')[0], 409)
        row_id = after['attempts'][0]['id']
        self.assertEqual(self.request(self.t, '/api/reviews', {'submission_id': row_id,
            'decision': 'accepted', 'comment': '', 'key': 'old-version'})[0], 409)

    def test_identity_is_server_assigned_and_cross_user_denied(self):
        code, row = self.answer(student='student-b', role='teacher')
        self.assertEqual(code, 200)
        self.assertEqual(row['student'], 'student-a')
        self.assertEqual(self.request(self.b, f'/api/submissions/{row["id"]}')[0], 404)
        self.assertEqual(self.request(self.a, '/api/queue')[0], 403)
        self.assertEqual(self.request(self.a, '/api/reviews', {'submission_id': row['id'],
            'decision': 'accepted', 'comment': '', 'key': 'r'})[0], 403)
        self.assertEqual(self.request(self.client(), '/api/modules/M01')[0], 401)

    def test_draft_is_private_and_does_not_unlock_model(self):
        body = {'module': 'M01', 'case': 'C1', 'version': self.version, 'text': 'PRIVATE DRAFT'}
        self.assertEqual(self.request(self.a, '/api/drafts', body)[0], 200)
        own = self.request(self.a, '/api/modules/M01')[1]
        self.assertEqual(own['drafts']['C1'], 'PRIVATE DRAFT')
        self.assertNotIn('answer', own['cases'][0])
        self.assertNotIn('PRIVATE DRAFT', json.dumps(self.request(self.b, '/api/modules/M01')[1]))
        self.assertNotIn('PRIVATE DRAFT', json.dumps(self.request(self.t, '/api/modules/M01')[1]))
        self.assertEqual(self.request(self.t, '/api/queue')[1], [])

    def test_return_resubmit_accept_preserves_history(self):
        row = self.answer()[1]
        review = {'submission_id': row['id'], 'decision': 'returned', 'comment': '', 'key': 'review-1'}
        self.assertEqual(self.request(self.t, '/api/reviews', review)[0], 400)
        review['comment'] = 'Explain your reasoning'
        self.assertEqual(self.request(self.t, '/api/reviews', review)[0], 200)
        new = self.answer(answer='Improved reasoning', key='request-2')[1]
        self.assertEqual(self.request(self.t, '/api/reviews', {'submission_id': new['id'],
            'decision': 'accepted', 'comment': 'Thank you', 'key': 'review-2'})[0], 200)
        attempts = self.request(self.a, '/api/modules/M01')[1]['attempts']
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]['reviews'][0]['decision'], 'accepted')
        self.assertEqual(attempts[1]['answer'], 'Synthetic own solution')
        self.assertEqual(attempts[1]['reviews'][0]['comment'], 'Explain your reasoning')

    def test_http_idempotency(self):
        first = self.answer()[1]
        self.assertEqual(self.answer()[1]['id'], first['id'])
        self.assertEqual(self.answer(answer='Changed with same key')[0], 400)
        self.assertEqual(len(self.request(self.t, '/api/queue')[1]), 1)

    def test_teacher_assignment_enforced(self):
        row = self.answer()[1]
        self.server.pilot.assignments['teacher'] = set()
        self.assertEqual(self.request(self.t, '/api/modules/M01')[0], 403)
        self.assertEqual(self.request(self.t, f'/api/submissions/{row["id"]}')[0], 403)
        self.assertEqual(self.request(self.t, '/api/queue')[1], [])
        self.assertEqual(self.request(self.t, '/api/reviews', {'submission_id': row['id'],
            'decision': 'accepted', 'comment': '', 'key': 'r'})[0], 403)

    def test_host_origin_and_static_allowlist(self):
        self.assertEqual(self.request(self.a, '/api/answers', {}, {'Origin': 'https://unrelated.example'})[0], 403)
        self.assertEqual(self.request(self.a, '/api/session', headers={'Host': 'unrelated.example'})[0], 403)
        self.assertEqual(self.request(self.a, '/data/orp-data.json')[0], 404)
        self.assertEqual(self.request(self.a, '/pilot/store.py')[0], 404)
        self.assertEqual(self.request(self.a, '/api/modules/M01')[0], 200)

    def test_write_failure_does_not_unlock_answer(self):
        with patch.object(self.server.pilot.store, 'submit', side_effect=RuntimeError('SECRET diagnostic')):
            code, error = self.answer()
        self.assertEqual(code, 500)
        self.assertNotIn('SECRET', str(error))
        self.assertNotIn('answer', self.request(self.a, '/api/modules/M01')[1]['cases'][0])

    def test_database_survives_server_restart(self):
        row = self.answer()[1]
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.start_server()
        other_device = self.client()
        self.request(other_device, '/api/login', {'username': 'student-a', 'password': 'demo-student-a'})
        self.assertEqual(self.request(other_device, '/api/modules/M01')[1]['attempts'][0]['id'], row['id'])


if __name__ == '__main__':
    unittest.main()

"""Devin SWE-2-High assertions; Codex adapted fixture/helpers to existing API."""
import unittest
from pilot.completion_fixture import CompletionFixture, FACULTY_VIDEO
MODULE='M01'

class CompletionAccessTest(CompletionFixture):
    def test_student_reads_only_own_state(self):
        body = self.state(self.a)
        self.assertEqual(body['module'], 'M01')
        self.assertEqual(body['student'], 'student-a')
        self.assertIn(body['status'], ('blocked', 'ready', 'submitted', 'returned', 'completed'))
        self.assertEqual({c['id'] for c in body['checks']},
                         {'lecture', 'source', 'cases', 'seminar', 'tumor_board', 'quiz'})
        self.assertEqual({c['id'] for c in body['teacher_checks']}, {'cases', 'seminar', 'tumor_board'})
        for path in ('/api/completion/students/student-a/M01',
                     '/api/completion/students/student-b/M01'):
            self.assertEqual(self.get(self.a, path)[0], 403)
        self.assertEqual(self.get(self.b, '/api/completion/students/student-a/M01')[0], 403)

    def test_teacher_lookup_queue_and_unknown_student(self):
        code, body = self.get(self.t, '/api/completion/students/student-a/M01')
        self.assertEqual(code, 200)
        self.assertEqual(body['student'], 'student-a')
        self.assertEqual(self.get(self.t, '/api/completion/students/ghost-student/M01')[0], 404)
        code, rows = self.get(self.t, '/api/completion/queue')
        self.assertEqual(code, 200)
        self.assertIsInstance(rows, list)
        for row in rows:
            self.assertIn('stale', row)
        self.assertEqual(self.get(self.a, '/api/completion/queue')[0], 403)

    def test_unauthenticated_and_cross_role_posts_rejected(self):
        anon = self.anonymous()
        self.assertIn(self.get(anon, '/api/completion/M01')[0], (401, 403))
        self.assertIn(self.get(anon, '/api/completion/queue')[0], (401, 403))
        self.assertIn(self.get(anon, '/api/completion/submit',
                                 {'module': 'M01', 'version': 'x', 'key': 'k'})[0], (401, 403))
        review = {'request_id': 1, 'decision': 'confirmed', 'comment': 'ok', 'key': 'rev-1'}
        self.assertEqual(self.get(self.a, '/api/completion/review', review)[0], 403)
        self.assertEqual(self.get(self.t, '/api/completion/submit',
                                  {'module': 'M01', 'version': 'x', 'key': 'k'})[0], 403)

    def test_submit_blocked_until_ready_ignores_forged_fields(self):
        forged = {'module': 'M01', 'version': self.state(self.a)['version'], 'key': 'sub-forged',
                  'student': 'teacher', 'teacher': 'teacher', 'status': 'completed',
                  'score': 100, 'ready': True, 'student_ready': True, 'teacher_ready': True}
        self.assertEqual(self.get(self.a, '/api/completion/submit', forged)[0], 409)
        body = self.state(self.a)
        self.assertEqual(body['status'], 'blocked')
        self.assertFalse(body['student_ready'])
        self.assertIsNone(body['request'])
        self.assertEqual(body['history'], [])

    def test_osce_answer_never_satisfies_readiness(self):
        code, _ = self.answer('S01')
        self.assertIn(code, (200, 201))
        body = self.state(self.a)
        self.assertEqual(body['status'], 'blocked')
        self.assertFalse(body['student_ready'])
        checks = {c['id']: c for c in body['checks']}
        self.assertFalse(checks['lecture']['ok'])
        self.assertFalse(checks['quiz']['ok'])
        code, _ = self.submit(self.a, key='sub-after-osce')
        self.assertEqual(code, 409)

    def test_lecture_catalogue_access_and_binding_validation(self):
        self.assertEqual(self.get(self.a, '/api/completion/lecture/M01')[0], 403)
        code, cat = self.get(self.t, '/api/completion/lecture/M01')
        self.assertEqual(code, 200)
        self.assertEqual(cat['module'], 'M01')
        self.assertIsNone(cat['current'])
        cand = [c for c in cat['candidates'] if c.get('url') == FACULTY_VIDEO['url']]
        self.assertEqual(len(cand), 1)
        bind = {'module': 'M01', 'materials_version': cat['materials_version'], 'key': 'bind-1'}
        bad = dict(bind, resource='archive-or-invented')
        self.assertIn(self.get(self.t, '/api/completion/lecture', bad)[0], (400, 404))
        self.assertEqual(self.get(self.a, '/api/completion/lecture',
                                  dict(bind, resource=cand[0]['id']))[0], 403)
        good = dict(bind, resource=cand[0]['id'])
        code, first = self.get(self.t, '/api/completion/lecture', good)
        self.assertEqual(code, 200)
        code, replay = self.get(self.t, '/api/completion/lecture', good)
        self.assertEqual(code, 200)
        self.assertEqual(first, replay)
        code, after = self.get(self.t, '/api/completion/lecture/M01')
        self.assertEqual(code, 200)
        self.assertEqual(after['current']['url'], FACULTY_VIDEO['url'])
        self.assertEqual(after['current']['materials_version'], cat['materials_version'])

if __name__ == '__main__':
    unittest.main()

"""Devin SWE-2-High assertions; Codex adapted fixture/helpers to existing API."""
import unittest
from pilot.completion_fixture import CompletionFixture, FACULTY_VIDEO
MODULE='M01'

class CompletionHistoryTest(CompletionFixture):
    def state(self, client=None):
        return self.get(client or self.a, '/api/completion/M01')

    def queue_rows(self):
        code, rows=self.get(self.t, '/api/completion/queue')
        self.assertEqual(code,200)
        return rows

    def submit(self, client=None, **over):
        body={'module':'M01','version':self.cversion,'key':'sub-1'}
        body.update(over)
        return self.get(client or self.a,'/api/completion/submit',body)

    def test_submit_returns_request_row_and_history_entry(self):
        st = self.make_ready()
        code, row = self.submit(key='sub-1')
        self.assertEqual(code, 200)
        self.assertIsInstance(row['id'], int)
        self.assertEqual(row['student'], 'student-a')
        self.assertEqual(row['module'], MODULE)
        self.assertEqual(row['version'], st['version'])
        self.assertEqual(row['key'], 'sub-1')
        self.assertTrue(row['created_at'])
        self.assertEqual(row['events'], [])
        code, st = self.state()
        self.assertEqual(code, 200)
        self.assertEqual(st['status'], 'submitted')
        self.assertEqual(st['request']['id'], row['id'])
        self.assertEqual([h['id'] for h in st['history']], [row['id']])

    def test_submit_replay_same_key_returns_original_row(self):
        self.make_ready()
        code, r1 = self.submit(key='sub-replay')
        self.assertEqual(code, 200)
        code, r2 = self.submit(key='sub-replay')
        self.assertEqual(code, 200)
        self.assertEqual(r2['id'], r1['id'])
        self.assertEqual(r2['created_at'], r1['created_at'])
        code, st = self.state()
        self.assertEqual(code, 200)
        self.assertEqual([h['id'] for h in st['history']], [r1['id']])
        self.assertEqual(st['request']['id'], r1['id'])

    def test_new_required_answer_stales_queue_row_and_keeps_history(self):
        self.make_ready()
        code, row = self.submit(key='sub-stale')
        self.assertEqual(code, 200)
        mine = [r for r in self.queue_rows() if r.get('id') == row['id']]
        self.assertEqual(len(mine), 1)
        self.assertFalse(mine[0]['stale'])
        code, _ = self.answer('C1', key='C1-stale', answer='Synthetic follow-up')
        self.assertEqual(code, 200)
        mine = [r for r in self.queue_rows() if r.get('id') == row['id']]
        self.assertEqual(len(mine), 1)
        self.assertTrue(mine[0]['stale'])
        code, st = self.state()
        self.assertEqual(code, 200)
        self.assertIsNone(st['request'])
        self.assertNotEqual(st['status'], 'completed')
        self.assertIn(row['id'], [h['id'] for h in st['history']])

    def test_return_then_new_declaration_appends_history(self):
        self.make_ready()
        code, r1 = self.submit(key='sub-first')
        self.assertEqual(code, 200)
        code, ev = self.get(self.t, '/api/completion/review',
                            {'request_id': r1['id'], 'decision': 'returned',
                             'comment': 'Please redo the declaration', 'key': 'comp-rev-1'})
        self.assertEqual(code, 200)
        self.assertEqual(ev.get('decision'), 'returned')
        code, st = self.state()
        self.assertEqual(code, 200)
        self.assertEqual(st['status'], 'returned')
        code, r2 = self.submit(key='sub-second', version=st['version'])
        self.assertEqual(code, 200)
        self.assertNotEqual(r2['id'], r1['id'])
        code, st = self.state()
        self.assertEqual(code, 200)
        self.assertEqual(st['status'], 'submitted')
        self.assertEqual(st['request']['id'], r2['id'])
        ids = [h['id'] for h in st['history']]
        self.assertEqual(sorted(ids), sorted([r1['id'], r2['id']]))

    def test_history_and_lecture_binding_survive_restart(self):
        self.make_ready()
        code, row = self.submit(key='sub-restart')
        self.assertEqual(code, 200)
        self.stop()
        self.start_server()
        student = self.login('student-a')
        teacher = self.login('teacher')
        code, st = self.get(student, '/api/completion/' + MODULE)
        self.assertEqual(code, 200)
        self.assertIn(row['id'], [h['id'] for h in st['history']])
        self.assertEqual(st['request']['id'], row['id'])
        code, lec = self.get(teacher, '/api/completion/lecture/' + MODULE)
        self.assertEqual(code, 200)
        self.assertIsNotNone(lec['current'])
        self.assertEqual(lec['current']['url'], FACULTY_VIDEO['url'])
        self.assertEqual(lec['current']['title'], FACULTY_VIDEO['title'])

    def test_submit_ignores_forged_fields_and_rejects_wrong_version(self):
        self.make_ready()
        code, row = self.submit(key='sub-forge', student='student-b', teacher='teacher',
                                status='completed', score=100, student_ready=False,
                                teacher_ready=False)
        self.assertEqual(code, 200)
        self.assertEqual(row['student'], 'student-a')
        code, st = self.state()
        self.assertEqual(code, 200)
        self.assertEqual(st['status'], 'submitted')
        code, _ = self.submit(key='sub-badver', version='not-the-version')
        self.assertEqual(code, 409)
        code, st = self.state()
        self.assertEqual(code, 200)
        self.assertEqual(len(st['history']), 1)

if __name__ == '__main__':
    unittest.main()

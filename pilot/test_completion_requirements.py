"""Independent Devin assertions adapted by Codex to documented existing API."""
import unittest
import uuid
from pilot.completion_fixture import CompletionFixture, FACULTY_VIDEO

class CompletionRequirementsTest(CompletionFixture):
    def key(self,prefix):return prefix+str(uuid.uuid4())

    def submit(self, **over):
        body={'module':'M01','version':self.state()['version'],'key':self.key('submit')}
        body.update(over)
        return self.get(self.a,'/api/completion/submit',body)

    def make_ready(self):
        return super().make_ready(teacher=False)

    def grade_latest(self):
        for aid,row in self.rows.items():
            if aid!='P:tb:TB01:1':self.mark(row)

    def teacher_state(self):
        code,row=self.get(self.t,'/api/completion/students/student-a/M01')
        self.assertEqual(code,200)
        return row

    def test_initial_state_blocked_with_named_gates(self):
        st = self.state()
        ch = {c['id']: c for c in st['checks']}
        self.assertEqual(st['status'], 'blocked')
        self.assertFalse(st['student_ready'])
        self.assertFalse(st['teacher_ready'])
        self.assertIsNone(st['lecture'])
        self.assertIsNone(st['request'])
        for cid in ('lecture', 'source', 'cases', 'seminar', 'tumor_board', 'quiz'):
            self.assertIn(cid, ch, f'missing check {cid}')
            self.assertFalse(ch[cid]['ok'], f'{cid} must be unmet before any work')
        reason = str(ch['lecture'].get('reason') or ch['lecture'].get('label') or '')
        self.assertTrue(reason, 'unmet lecture check must report the missing mapping')

    def test_lecture_candidates_binding_and_idempotent_replay(self):
        code, _ = self.get(self.a, '/api/completion/lecture/M01')
        self.assertEqual(code, 403)
        code, cat = self.get(self.t, '/api/completion/lecture/M01')
        self.assertEqual(code, 200)
        self.assertEqual(cat['module'], 'M01')
        self.assertIsNone(cat['current'])
        self.assertEqual(len(cat['candidates']), 1)
        cand = cat['candidates'][0]
        self.assertEqual(cand['url'], FACULTY_VIDEO['url'])
        body = {'module': 'M01', 'materials_version': cat['materials_version'],
                'resource': cand['id'], 'key': self.key('bind')}
        code, bound = self.get(self.t, '/api/completion/lecture', body)
        self.assertIn(code, (200, 201))
        snap = bound.get('binding') or bound.get('lecture') or bound
        for field in ('resource', 'url', 'materials_version', 'teacher', 'created_at'):
            self.assertIn(field, snap, f'lecture snapshot missing {field}')
        self.assertEqual(snap['url'], FACULTY_VIDEO['url'])
        code, replay = self.get(self.t, '/api/completion/lecture', dict(body))
        self.assertIn(code, (200, 201))
        rsnap = replay.get('binding') or replay.get('lecture') or replay
        self.assertEqual(rsnap.get('resource'), snap.get('resource'))
        self.assertEqual(rsnap.get('created_at'), snap.get('created_at'), 'same key must replay the binding')
        bad = dict(body, resource='not-a-real-candidate', key=self.key('bind'))
        code, _ = self.get(self.t, '/api/completion/lecture', bad)
        self.assertIn(code, (400, 404))
        stale = dict(body, materials_version='bogus-version', key=self.key('bind'))
        code, _ = self.get(self.t, '/api/completion/lecture', stale)
        self.assertIn(code, (400, 409))

    def test_submit_blocked_until_ready_and_forged_fields_ignored(self):
        code, _ = self.submit()
        self.assertIn(code, (400, 409))
        code, _ = self.submit(student='teacher', teacher='teacher', status='completed',
                              student_ready=True, teacher_ready=True, score=100,
                              events=[{'decision': 'confirmed'}])
        self.assertIn(code, (400, 409))
        st = self.state()
        self.assertEqual(st['status'], 'blocked')
        self.assertIsNone(st['request'])

    def test_full_cycle_submit_confirm_and_persist_across_restart(self):
        self.make_ready()
        st = self.state()
        self.assertEqual(st['status'], 'ready')
        self.assertTrue(st['student_ready'])
        submit_key = self.key('submit')
        code, row = self.submit(key=submit_key)
        self.assertIn(code, (200, 201), msg=str(row))
        self.assertIsInstance(row['id'], int)
        self.assertEqual(row['student'], 'student-a')
        self.assertEqual(row['module'], 'M01')
        self.assertEqual(row['events'], [])
        code, replay = self.submit(key=submit_key)
        self.assertIn(code, (200, 201))
        self.assertEqual(replay['id'], row['id'], 'same key must replay the original row')
        self.grade_latest()
        tst = self.teacher_state()
        self.assertEqual(tst['status'], 'submitted')
        self.assertTrue(tst['teacher_ready'],
                        f'teacher checks failed: {tst.get("teacher_checks")}')
        code, queue = self.get(self.t, '/api/completion/queue')
        self.assertEqual(code, 200)
        rows = queue if isinstance(queue, list) else queue.get('rows') or queue.get('requests') or []
        mine = [r for r in rows if r.get('student') == 'student-a' and r.get('module') == 'M01']
        self.assertTrue(mine, 'student-a request missing from teacher queue')
        self.assertFalse(mine[-1].get('stale', True), 'current request must not be stale')
        self.assertFalse(any(r.get('student') == 'student-b' for r in rows),
                         'queue must not leak other students')
        code, _ = self.get(self.t, '/api/completion/review',
                           {'request_id': row['id'], 'decision': 'confirmed', 'comment': 'ok',
                            'key': self.key('cfm')})
        self.assertIn(code, (200, 201))
        self.assertEqual(self.state()['status'], 'completed')
        self.stop()
        self.start_server()
        self.a = self.login('student-a')
        self.t = self.login('teacher')
        st = self.state()
        self.assertEqual(st['status'], 'completed')
        self.assertIsNotNone(st['lecture'])
        self.assertEqual(st['lecture']['url'], FACULTY_VIDEO['url'])

    def test_return_requires_comment_and_permits_new_declaration(self):
        self.make_ready()
        code, row = self.submit()
        self.assertIn(code, (200, 201))
        code, _ = self.get(self.t, '/api/completion/review',
                           {'request_id': row['id'], 'decision': 'returned', 'comment': '   ',
                            'key': self.key('ret')})
        self.assertEqual(code, 400)
        code, _ = self.get(self.t, '/api/completion/review',
                           {'request_id': row['id'], 'decision': 'returned',
                            'comment': 'Please redo the tumor-board stage',
                            'key': self.key('ret')})
        self.assertIn(code, (200, 201))
        self.assertEqual(self.state()['status'], 'returned')
        code, row2 = self.submit()
        self.assertIn(code, (200, 201))
        self.assertNotEqual(row2['id'], row['id'], 'a new declaration must create a new row')
        self.assertGreaterEqual(len(self.state().get('history') or []), 1)

    def test_access_control_and_unknown_targets(self):
        code, _ = self.get(self.b, '/api/completion/students/student-a/M01')
        self.assertEqual(code, 403)
        code, _ = self.get(self.a, '/api/completion/queue')
        self.assertEqual(code, 403)
        code, _ = self.get(self.a, '/api/completion/lecture',
                           {'module': 'M01', 'materials_version': 'x', 'resource': '1',
                            'key': 'forbidden'})
        self.assertEqual(code, 403)
        code, _ = self.get(self.b, '/api/completion/review',
                           {'request_id': 1, 'decision': 'confirmed', 'comment': 'x', 'key': 'k'})
        self.assertIn(code, (403, 404))
        code, _ = self.get(self.t, '/api/completion/students/ghost/M01')
        self.assertEqual(code, 404)
        code, _ = self.get(self.a, '/api/completion/ZZ')
        self.assertEqual(code, 404)

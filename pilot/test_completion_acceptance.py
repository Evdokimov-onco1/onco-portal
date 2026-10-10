"""Codex acceptance: changing evidence must never preserve an invalid module credit."""
from pilot.completion_fixture import CompletionFixture

class CompletionAcceptanceTest(CompletionFixture):
    def confirm(self, rid, key='confirm'):
        return self.get(self.t,'/api/completion/review',{'request_id':rid,
            'decision':'confirmed','comment':'Synthetic final review','key':key})

    def test_optional_osce_does_not_invalidate_but_new_required_answer_does(self):
        self.make_ready()
        row=self.submit()[1]
        first=self.confirm(row['id'])
        self.assertEqual(first[0],200,first)
        self.assertEqual(self.confirm(row['id'])[1],first[1])
        self.assertEqual(self.state()['status'],'completed')
        version=self.state()['version']
        self.assertEqual(self.answer('S01')[0],200)
        self.assertEqual(self.state()['version'],version)
        self.assertEqual(self.state()['status'],'completed')
        self.assertEqual(self.answer('P:seminar:1',key='seminar-new',answer='Revised')[0],200)
        self.assertIsNone(self.state()['request'])
        self.assertEqual(self.confirm(row['id'],key='stale')[0],409)
        queue=self.get(self.t,'/api/completion/queue')[1]
        self.assertTrue(queue[0]['stale'])
        self.assertFalse(queue[0]['current_request'])
        self.assertNotEqual(queue[0]['effective_status'],'completed')

    def test_teacher_grading_required_only_final_tb_stage(self):
        self.make_ready(teacher=False)
        row=self.submit()[1]
        self.assertEqual(self.confirm(row['id'])[0],409)
        for aid in ('C1','P:seminar:1'):
            self.mark(self.rows[aid])
        self.assertFalse(self.state()['teacher_ready'])
        self.mark(self.rows['P:tb:TB01:2'])
        self.assertTrue(self.state()['teacher_ready'])
        self.assertEqual(self.confirm(row['id'])[0],200)
        # No intermediate-stage or OSCE grading was submitted.
        self.assertEqual(self.state()['status'],'completed')

    def test_later_returned_case_removes_effective_confirmation(self):
        self.make_ready()
        row=self.submit()[1]
        self.assertEqual(self.confirm(row['id'])[0],200)
        code,_=self.get(self.t,'/api/reviews',{'submission_id':self.rows['C1']['id'],
            'decision':'returned','comment':'Recheck reasoning','key':'case-return'})
        self.assertEqual(code,200)
        state=self.state()
        self.assertFalse(state['teacher_ready'])
        self.assertNotEqual(state['status'],'completed')
        self.assertEqual(state['history'][0]['events'][0]['decision'],'confirmed')
        self.assertNotEqual(self.get(self.t,'/api/completion/queue')[1][0]['effective_status'],'completed')

    def test_exact_threshold_and_current_quiz_bank(self):
        self.pass_quiz(score=6)
        def quiz_ok():return next(c['ok'] for c in self.state()['checks'] if c['id']=='quiz')
        self.assertFalse(quiz_ok())
        self.pass_quiz(score=7,key='quiz-pass')
        self.assertTrue(quiz_ok())
        self.server.pilot.questions[0]['stem']='Changed required quiz content'
        self.assertFalse(quiz_ok())

    def test_archive_does_not_replace_bound_lecture_and_assignment_enforced(self):
        self.bind_lecture()
        self.assertEqual(self.open_resource('lectures-1')[0],200)
        self.assertFalse(next(c['ok'] for c in self.state()['checks'] if c['id']=='lecture'))
        self.assertEqual(self.open_resource(self.lecture_id)[0],200)
        self.assertTrue(next(c['ok'] for c in self.state()['checks'] if c['id']=='lecture'))
        self.server.pilot.assignments['teacher']=set()
        self.assertEqual(self.get(self.t,'/api/completion/lecture/M01')[0],403)
        self.assertEqual(self.get(self.t,'/api/completion/students/student-a/M01')[0],403)
        self.assertEqual(self.get(self.t,'/api/completion/queue')[1],[])

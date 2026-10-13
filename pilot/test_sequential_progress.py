import copy,json
from unittest.mock import patch
from pilot.completion_fixture import CompletionFixture, DATA

class SequentialProgressTest(CompletionFixture):
    def start_server(self):
        data=copy.deepcopy(DATA)
        for mid,year in [('M02','1'),('M03','1'),('M35','2'),('M36','2')]:
            m=copy.deepcopy(data['modules'][0]);m.update(module_id=mid,pedagogical_year=year);data['modules'].append(m)
        self.data.write_text(json.dumps(data))
        super().start_server()
        self.server.pilot.sequential=True

    def test_first_of_each_year_only_and_no_hidden_content(self):
        status,rows=self.get(self.a,'/api/modules');self.assertEqual(status,200)
        self.assertEqual([r['id'] for r in rows if not r['locked']],['M01','M35'])
        self.assertTrue(all(set(r)=={'id','title','year','locked','previous','completed'} for r in rows))
        for path in ['/api/modules/M02','/api/practice/M02','/api/completion/M02']:
            self.assertEqual(self.get(self.a,path)[0],403)
        for path in ['/api/drafts','/api/answers','/api/resources/open','/api/quizzes/start', '/api/practice/drafts','/api/practice/answers','/api/completion/submit']:
            self.assertEqual(self.get(self.a,path,{'module':'M02','version':'x','case':'C1','activity':'P:osce:S01','text':'x','answer':'x','key':'x'})[0],403)
        self.assertEqual(self.get(self.t,'/api/modules/M02')[0],200)
        self.assertEqual(self.get(self.anonymous(),'/api/modules')[0],401)

    def test_confirmation_revalidated_and_isolated_per_student(self):
        c=self.server.pilot.completion;con=c._connect()
        con.execute("INSERT INTO completion_requests(student,module,version,request_key,created_at) VALUES('student-a','M01','old','req','date')")
        con.execute("INSERT INTO completion_events(request_id,teacher,decision,comment,request_key,created_at) VALUES(1,'teacher','confirmed','','event','date')");con.close()
        # Stale/fabricated evidence never opens a module.
        self.assertEqual(self.get(self.a,'/api/modules/M02')[0],403)
        with patch.object(c,'state',return_value={'status':'completed'}):
            self.assertEqual(self.get(self.a,'/api/modules/M02')[0],200)
            self.assertEqual(self.get(self.a,'/api/modules/M03')[0],403)
            self.assertEqual(self.get(self.b,'/api/modules/M02')[0],403)
            self.assertEqual(self.get(self.a,'/api/modules/M36')[0],403)
        self.assertEqual(self.get(self.a,'/api/modules/M02')[0],403)

    def test_old_quiz_id_and_submission_do_not_bypass_lock(self):
        p=self.server.pilot
        row=p.quiz.start('student-a','M02',[q for q in p.questions if q['module']=='M01'],'old-q')
        for path,body in [('/api/quizzes/'+row['id'],None),('/api/quizzes/save',{'id':row['id'],'answers':{}}),('/api/quizzes/submit',{'id':row['id'],'answers':{}})]:
            self.assertEqual(self.get(self.a,path,body)[0],403)
        submission=p.store.submit('student-a','M02','C1',p.versions['M02'],'old response','old-s')
        self.assertEqual(self.get(self.a,'/api/submissions/'+str(submission['id']))[0],403)

    def test_real_credit_unlocks_next_and_return_relocks(self):
        self.make_ready()
        req=self.submit()[1]
        code,_=self.get(self.t,'/api/completion/review',{'request_id':req['id'],'decision':'confirmed','comment':'Synthetic review','key':'final'})
        self.assertEqual(code,200)
        self.assertEqual(self.get(self.a,'/api/modules/M02')[0],200)
        self.assertEqual(self.get(self.a,'/api/modules/M03')[0],403)
        rows=self.get(self.a,'/api/modules')[1]
        self.assertTrue(next(r for r in rows if r['id']=='M01')['completed'])
        self.get(self.t,'/api/reviews',{'submission_id':self.rows['C1']['id'],'decision':'returned','comment':'Recheck','key':'return-after-confirm'})
        self.assertEqual(self.get(self.a,'/api/modules/M02')[0],403)

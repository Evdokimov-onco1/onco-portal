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

    def test_all_first_year_open_and_second_year_locked(self):
        status,rows=self.get(self.a,'/api/modules');self.assertEqual(status,200)
        self.assertEqual([r['id'] for r in rows if not r['locked']],['M01','M02','M03'])
        self.assertTrue(all(set(r)=={'id','title','year','locked','previous','completed'} for r in rows))
        for path in ['/api/modules/M35','/api/practice/M35','/api/completion/M35']:
            self.assertEqual(self.get(self.a,path)[0],403)
        for path in ['/api/drafts','/api/answers','/api/resources/open','/api/quizzes/start', '/api/practice/drafts','/api/practice/answers','/api/completion/submit']:
            self.assertEqual(self.get(self.a,path,{'module':'M35','version':'x','case':'C1','activity':'P:osce:S01','text':'x','answer':'x','key':'x'})[0],403)
        self.assertEqual(self.get(self.t,'/api/modules/M02')[0],200)
        self.assertEqual(self.get(self.anonymous(),'/api/modules')[0],401)

    def test_confirmation_revalidated_and_isolated_per_student(self):
        c=self.server.pilot.completion;con=c._connect()
        con.execute("INSERT INTO completion_requests(student,module,version,request_key,created_at) VALUES('student-a','M03','old','req','date')")
        con.execute("INSERT INTO completion_events(request_id,teacher,decision,comment,request_key,created_at) VALUES(1,'teacher','confirmed','','event','date')");con.close()
        self.assertEqual(self.get(self.a,'/api/modules/M35')[0],403)
        with patch.object(c,'state',return_value={'status':'completed'}):
            self.assertEqual(self.get(self.a,'/api/modules/M35')[0],200)
            self.assertEqual(self.get(self.a,'/api/modules/M36')[0],200)
            self.assertEqual(self.get(self.b,'/api/modules/M35')[0],403)
        self.assertEqual(self.get(self.a,'/api/modules/M35')[0],403)

    def test_old_quiz_id_and_submission_do_not_bypass_lock(self):
        p=self.server.pilot
        row=p.quiz.start('student-a','M35',[q for q in p.questions if q['module']=='M01'],'old-q')
        for path,body in [('/api/quizzes/'+row['id'],None),('/api/quizzes/save',{'id':row['id'],'answers':{}}),('/api/quizzes/submit',{'id':row['id'],'answers':{}})]:
            self.assertEqual(self.get(self.a,path,body)[0],403)
        submission=p.store.submit('student-a','M35','C1',p.versions['M35'],'old response','old-s')
        self.assertEqual(self.get(self.a,'/api/submissions/'+str(submission['id']))[0],403)

    def test_real_final_credit_unlocks_entire_second_year_and_return_relocks(self):
        # With one first-year module, M01 is the actual final module.
        for mid in ('M02','M03'):
            del self.server.pilot.modules[mid]
        self.make_ready()
        req=self.submit()[1]
        code,_=self.get(self.t,'/api/completion/review',{'request_id':req['id'],'decision':'confirmed','comment':'Synthetic review','key':'final'})
        self.assertEqual(code,200)
        for mid in ('M35','M36'):
            self.assertEqual(self.get(self.a,'/api/modules/'+mid)[0],200)
            self.assertEqual(self.get(self.b,'/api/modules/'+mid)[0],403)
        self.get(self.t,'/api/reviews',{'submission_id':self.rows['C1']['id'],'decision':'returned','comment':'Recheck','key':'return-after-confirm'})
        self.assertEqual(self.get(self.a,'/api/modules/M35')[0],403)
        self.assertEqual(self.get(self.a,'/api/modules/M01')[0],200)

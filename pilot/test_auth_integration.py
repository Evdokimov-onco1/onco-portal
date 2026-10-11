"""Independent hosted acceptance checks by Codex, synthetic data only."""
import subprocess
import unittest
from unittest import mock
from pilot import test_wsgi_hosted as hosted_test
API = hosted_test.API
from pilot.test_auth import extract_token
from pilot.wsgi import make_app
from pilot.mailer import Mailer, MailError

class AuthIntegrationTest(unittest.TestCase):
    call = hosted_test.WsgiHostedTest.call
    login = hosted_test.WsgiHostedTest.login
    auth = hosted_test.WsgiHostedTest.auth

    def setUp(self):
        hosted_test.WsgiHostedTest.setUp(self)
        self.sink = []
        self.env.update(PILOT_AUTH_ENABLED='1', PILOT_MAIL_TRANSPORT='fake', PILOT_MAIL_SINK=self.sink)
        self.a = make_app(self.env)
        self.b = make_app(self.env)

    def post(self, app, path, body, headers=None):
        return self.call(app, 'POST', path, headers or API, body)

    def test_registration_reset_cross_worker_and_progress(self):
        email = 'new-student@example.test'
        self.assertEqual(self.post(self.a, '/api/auth/register', {'email':email,'name':'New Student'})[0],200)
        token = extract_token(self.sink)
        self.assertEqual(self.post(self.b, '/api/auth/verify', {'token':token,'password':'First-password-123'})[0],200)
        status,user,cookie = self.login(self.a,email,'First-password-123')
        self.assertEqual(status,200)
        uid=user['id']
        headers=self.auth(cookie)
        status,module,_=self.call(self.b,'GET','/api/modules/M01',headers)
        self.assertEqual(status,200)
        self.assertEqual(self.post(self.b,'/api/drafts',{'module':'M01','case':'C1','version':module['version'],'text':'Synthetic saved progress'},headers)[0],200)
        self.assertEqual(self.post(self.a,'/api/auth/forgot',{'email':email})[0],200)
        reset=extract_token(self.sink)
        self.assertEqual(self.post(self.b,'/api/auth/reset',{'token':reset,'password':'Second-password-123'})[0],200)
        self.assertEqual(self.call(self.a,'GET','/api/session',headers)[0],401)
        self.assertEqual(self.login(self.a,email,'First-password-123')[0],401)
        status,user,newcookie=self.login(self.b,email,'Second-password-123')
        self.assertEqual((status,user['id']),(200,uid))
        status,module,_=self.call(self.a,'GET','/api/modules/M01',self.auth(newcookie))
        self.assertEqual(status,200)
        self.assertIn('Synthetic saved progress',str(module))
        self.assertEqual(self.post(self.a,'/api/auth/reset',{'token':reset,'password':'Third-password-123'})[0],400)

    def test_teacher_scope_preserved(self):
        import json
        from pathlib import Path
        p=Path(self.env['PILOT_USERS_FILE']); users=json.loads(p.read_text());users['prof']['modules']=[];p.write_text(json.dumps(users))
        app=make_app(self.env)
        self.assertEqual(app.pilot.assignments['prof'],set())

    def test_non_object_json_rejected(self):
        for path in ['/api/auth/register','/api/auth/forgot','/api/login']:
            self.assertEqual(self.post(self.a,path,[])[0],400)

    def test_sendmail_timeout_is_generic(self):
        mailer=Mailer({'transport':'sendmail','sendmail_path':'/usr/sbin/sendmail','mail_from':'no-reply@example.test'})
        with mock.patch('pilot.mailer.os.path.isfile',return_value=True), mock.patch('pilot.mailer.subprocess.run',side_effect=subprocess.TimeoutExpired('sendmail',20)):
            with self.assertRaises(MailError):
                mailer.send('student@example.test','Test','Synthetic')

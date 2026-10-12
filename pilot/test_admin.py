"""Admin boundary, revocation, optimistic locking and worker persistence."""
import unittest
from pilot.test_auth_integration import AuthIntegrationTest
from pilot.test_auth import extract_token
from pilot.wsgi import make_app


class AdminTest(AuthIntegrationTest):
    def setUp(self):
        super().setUp()
        self.post(self.a,'/api/auth/register',{'email':'owner@example.test','name':'Owner'})
        self.post(self.a,'/api/auth/verify',{'token':extract_token(self.sink),'password':'Owner-password-123'})
        self.uid=self.a.pilot.admin.grant_verified('owner@example.test')
        status,user,cookie=self.login(self.b,'owner@example.test','Owner-password-123')
        self.assertEqual(status,200)
        self.assertTrue(user['is_admin'])
        self.headers=self.auth(cookie)

    def overview(self,app=None):
        status,data,_=self.call(app or self.b,'GET','/api/admin/overview',self.headers)
        self.assertEqual(status,200)
        return data

    def update(self,uid='ira',role='teacher',enabled=True,modules=None,version=None):
        target=next(u for u in self.overview()['users'] if u['id']==uid)
        body={'id':uid,'role':role,'enabled':enabled,'modules':['M01'] if modules is None else modules,
              'version':target['auth_version'] if version is None else version}
        return self.post(self.a,'/api/admin/users',body,self.headers)

    def test_student_teacher_and_guest_cannot_access_admin(self):
        for login,password in [('ira','Pass-ira-1'),('prof','Pass-prof-2')]:
            _,user,cookie=self.login(self.a,login,password)
            self.assertFalse(user['is_admin'])
            h=self.auth(cookie)
            self.assertEqual(self.call(self.a,'GET','/api/admin/overview',h)[0],403)
            self.assertEqual(self.post(self.a,'/api/admin/users',{'id':'ira','role':'teacher'},h)[0],403)
        self.assertEqual(self.call(self.a,'GET','/api/admin/overview')[0],401)

    def test_no_password_or_tokens_in_overview(self):
        data=self.overview()
        for user in data['users']:
            self.assertNotIn('password_hash',user)
            self.assertNotIn('password',user)
        self.assertNotIn('Owner-password',str(data))
        self.assertNotIn('pbkdf2$',str(data))

    def test_changes_persist_workers_and_revoke_target_session(self):
        _,_,cookie=self.login(self.b)
        self.assertEqual(self.update()[0],200)
        self.assertEqual(self.call(self.b,'GET','/api/session',self.auth(cookie))[0],401)
        self.assertEqual(self.b.pilot.assignments.get('ira'),{'M01'})
        fresh=make_app(self.env)
        status,user,cookie=self.login(fresh)
        self.assertEqual(user['role'],'teacher')
        self.assertEqual(self.call(fresh,'GET','/api/modules/M01',self.auth(cookie))[0],200)
        self.assertEqual(self.update(modules=[])[0],200)
        _,_,cookie=self.login(self.b)
        self.assertEqual(self.call(self.b,'GET','/api/modules/M01',self.auth(cookie))[0],403)

    def test_disabled_account_has_no_access_but_is_not_deleted(self):
        self.assertEqual(self.update(role='student',enabled=False,modules=[])[0],200)
        self.assertEqual(self.login(self.b)[0],401)
        self.assertIsNotNone(self.a.pilot.auth.store.get_account('ira'))
        self.assertEqual(self.update(role='student',enabled=True,modules=[])[0],200)
        self.assertEqual(self.login(self.b)[0],200)

    def test_admin_self_lockout_and_web_grants_prohibited(self):
        self.assertEqual(self.update(uid=self.uid,role='student',enabled=False,modules=[])[0],403)
        self.assertEqual(self.post(self.a,'/api/admin/grant',{'id':'ira'},self.headers)[0],404)

    def test_stale_update_rejected_without_overwrite(self):
        self.assertEqual(self.update(version=1)[0],200)
        self.assertEqual(self.update(role='student',modules=[],version=1)[0],409)
        self.assertEqual(self.a.pilot.auth.store.get_account('ira')['role'],'teacher')

    def test_invalid_assignment_and_csrf_rejected(self):
        self.assertEqual(self.update(modules=['M999'])[0],400)
        self.assertEqual(self.update(role='student',modules=['M01'])[0],400)
        self.assertEqual(self.update(modules=['M01','M01'])[0],400)
        h=dict(self.headers,HTTP_ORIGIN='https://evil.example.test')
        self.assertEqual(self.post(self.a,'/api/admin/users',{},h)[0],403)

    def test_unverified_cannot_bootstrap_and_registration_cannot_grant(self):
        self.post(self.a,'/api/auth/register',{'email':'unverified@example.test','name':'Unverified','is_admin':True,'role':'teacher'})
        with self.assertRaises(ValueError):
            self.a.pilot.admin.grant_verified('unverified@example.test')
        uid=self.a.pilot.auth.store.resolve_login('unverified@example.test')
        self.assertFalse(self.a.pilot.admin.is_admin(uid))
        self.assertEqual(self.a.pilot.auth.store.get_account(uid)['role'],'student')


if __name__=='__main__':
    unittest.main()

"""WSGI hosted-mode checks on synthetic data and isolated DBs (no network)."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from pilot.server import make_password_hash
from pilot.wsgi import COOKIE_NAME, build_assignments, load_users, make_app

DATA = {'modules': [{'module_id': 'M01', 'module_title': 'Synthetic module',
    'pedagogical_year': '1', 'clinical_cases': [
        {'title': 'Synthetic task', 'vignette': 'Explain your method', 'questions': 'Why?',
         'answer': 'SECRET MODEL SOLUTION', 'sources': []}]}],
    'questions': []}

USERS = {
    'ira': {'name': 'Ира Синтетикова', 'role': 'student',
            'password_hash': make_password_hash('Pass-ira-1')},
    'prof': {'name': 'Проф Синтетиков', 'role': 'teacher',
             'password_hash': make_password_hash('Pass-prof-2'), 'modules': 'all'},
}

HOST = 'staging.example.test'
API = {'HTTP_ORIGIN': f'https://{HOST}', 'HTTP_X_PILOT_REQUEST': '1'}


class WsgiHostedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        data = root / 'data.json'
        data.write_text(json.dumps(DATA))
        users = root / 'users.json'
        users.write_text(json.dumps(USERS))
        self.env = {'PILOT_HOST': HOST,
                    'PILOT_DB': str(root / 'pilot.sqlite3'),
                    'PILOT_SESSION_DB': str(root / 'sessions.sqlite3'),
                    'PILOT_USERS_FILE': str(users),
                    'PILOT_DATA': str(data)}
        self.worker_a = make_app(self.env)
        self.worker_b = make_app(self.env)  # отдельный «процесс» mod_wsgi
        self.addCleanup(self.tmp.cleanup)

    def call(self, app, method, path, headers=None, body=None):
        environ = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': '',
                   'HTTP_HOST': HOST, 'wsgi.url_scheme': 'https',
                   'wsgi.input': io.BytesIO(b''), 'CONTENT_LENGTH': '0'}
        environ.update(headers or {})
        if body is not None:
            raw = json.dumps(body).encode()
            environ['wsgi.input'] = io.BytesIO(raw)
            environ['CONTENT_TYPE'] = 'application/json'
            environ['CONTENT_LENGTH'] = str(len(raw))
        captured = {}

        def start_response(status, hdrs):
            captured['status'] = int(status.split()[0])
            captured['headers'] = dict(hdrs)

        payload = b''.join(app(environ, start_response))
        ctype = captured['headers'].get('Content-Type', '')
        parsed = json.loads(payload) if 'application/json' in ctype else payload
        return captured['status'], parsed, captured['headers']

    def login(self, app, username='ira', password='Pass-ira-1'):
        status, user, headers = self.call(app, 'POST', '/api/login', API,
                                          {'username': username, 'password': password})
        cookie = headers.get('Set-Cookie', '')
        return status, user, cookie

    def auth(self, cookie):
        return {'HTTP_COOKIE': cookie.split(';')[0], **API}

    def test_config_required_and_fail_closed(self):
        for key in ('PILOT_HOST', 'PILOT_DB', 'PILOT_USERS_FILE'):
            env = dict(self.env)
            env.pop(key)
            with self.assertRaises(RuntimeError):
                make_app(env)
        for bad in ('https://x.test', 'x.test:443', ''):
            with self.assertRaises(RuntimeError):
                make_app({**self.env, 'PILOT_HOST': bad})
        with self.assertRaises(ValueError):
            load_users(self.env['PILOT_DATA'])  # не файл аккаунтов
        # невалидные форматы password_hash отклоняются при загрузке
        root = Path(self.env['PILOT_DB']).parent
        for bad_hash in ('plain-password', 'pbkdf2$', 'pbkdf2$abc$s$' + 'a' * 40,
                         'pbkdf2$0$12345678$' + 'a' * 64):
            bad = root / 'users-bad.json'
            bad.write_text(json.dumps({'u': {'name': 'U', 'role': 'student',
                                             'password_hash': bad_hash}}))
            with self.assertRaises(ValueError, msg=bad_hash):
                load_users(bad)
            with self.assertRaises(ValueError, msg=bad_hash):
                make_app({**self.env, 'PILOT_USERS_FILE': str(bad)})
        # пути внутри public_html отклоняются после резолвинга
        public = root / 'public_html'
        public.mkdir()
        for key in ('PILOT_DB', 'PILOT_SESSION_DB', 'PILOT_USERS_FILE'):
            with self.assertRaises(RuntimeError, msg=key):
                make_app({**self.env, key: str(public / 'x.sqlite3')})
        self.assertEqual(build_assignments(USERS, {'M01': {}}), {'prof': {'M01'}})

    def test_host_and_origin_rejected(self):
        status, *_ = self.call(self.worker_a, 'GET', '/',
                               {'HTTP_HOST': 'evil.example'})
        self.assertEqual(status, 403)
        status, *_ = self.call(self.worker_a, 'GET', '/',
                               {'HTTP_HOST': 'staging.example.test.evil.test'})
        self.assertEqual(status, 403)
        # произвольный порт отклоняется; явный :443 допустим
        status, *_ = self.call(self.worker_a, 'GET', '/',
                               {'HTTP_HOST': 'staging.example.test:8443'})
        self.assertEqual(status, 403)
        status, *_ = self.call(self.worker_a, 'GET', '/',
                               {'HTTP_HOST': 'staging.example.test:443'})
        self.assertEqual(status, 200)
        # http-схема отклоняется независимо от заголовков
        status, *_ = self.call(self.worker_a, 'GET', '/',
                               {'wsgi.url_scheme': 'http'})
        self.assertEqual(status, 403)
        for headers in ({'HTTP_ORIGIN': 'http://staging.example.test'},
                        {'HTTP_ORIGIN': 'https://evil.example', 'HTTP_X_PILOT_REQUEST': '1'},
                        {'HTTP_X_PILOT_REQUEST': '1'},
                        {'HTTP_ORIGIN': f'https://{HOST}'}):
            status, *_ = self.call(self.worker_a, 'POST', '/api/login', headers,
                                   {'username': 'ira', 'password': 'Pass-ira-1'})
            self.assertEqual(status, 403, headers)
        # forwarded-заголовки не влияют на решение: Host берётся из HTTP_HOST,
        # поэтому guard пропускает запрос до проверки auth → 401, а не 403
        status, *_ = self.call(self.worker_a, 'GET', '/api/session',
                               {'HTTP_X_FORWARDED_HOST': 'evil.test'})
        self.assertEqual(status, 401)

    def test_secure_cookie_login_and_cross_worker_session(self):
        status, user, cookie = self.login(self.worker_a)
        self.assertEqual(status, 200)
        self.assertEqual(user['id'], 'ira')
        self.assertIn('Secure', cookie)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        auth = self.auth(cookie)
        # сессия видна другому процессу через общий session DB
        status, session, _ = self.call(self.worker_b, 'GET', '/api/session', auth)
        self.assertEqual(status, 200)
        self.assertEqual(session['id'], 'ira')
        # logout на втором процессе инвалидирует токен и для первого
        status, *_ = self.call(self.worker_b, 'POST', '/api/logout', auth, {})
        self.assertEqual(status, 200)
        status, *_ = self.call(self.worker_a, 'GET', '/api/session', auth)
        self.assertEqual(status, 401)

    def test_demo_accounts_absent_and_teacher_assignment(self):
        status, *_ = self.login(self.worker_a, 'student-a', 'demo-student-a')
        self.assertEqual(status, 401)
        _, _, cookie = self.login(self.worker_a, 'prof', 'Pass-prof-2')
        status, queue, _ = self.call(self.worker_a, 'GET', '/api/completion/queue',
                                     self.auth(cookie))
        self.assertEqual(status, 200)

    def test_static_and_api_routes(self):
        status, body, headers = self.call(self.worker_a, 'GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('text/html', headers['Content-Type'])
        status, js, _ = self.call(self.worker_a, 'GET', '/learning.js')
        self.assertIn(b'suggested-player', js)
        status, *_ = self.call(self.worker_a, 'GET', '/api/modules')
        self.assertEqual(status, 401)
        _, _, cookie = self.login(self.worker_a)
        status, modules, _ = self.call(self.worker_b, 'GET', '/api/modules',
                                       self.auth(cookie))
        self.assertEqual(status, 200)
        self.assertEqual(modules[0]['id'], 'M01')
        status, *_ = self.call(self.worker_a, 'PUT', '/api/session')
        self.assertEqual(status, 405)

    def test_persistent_progress_across_workers(self):
        _, _, cookie = self.login(self.worker_a)
        auth = self.auth(cookie)
        status, module, _ = self.call(self.worker_a, 'GET', '/api/modules/M01', auth)
        version = module['version']
        status, *_ = self.call(self.worker_a, 'POST', '/api/drafts', auth,
                               {'module': 'M01', 'case': 'C1', 'version': version,
                                'text': 'PRIVATE DRAFT'})
        self.assertEqual(status, 200)
        # другой процесс видит прогресс через общую основную БД
        status, module, _ = self.call(self.worker_b, 'GET', '/api/modules/M01', auth)
        self.assertEqual(module['drafts'].get('C1'), 'PRIVATE DRAFT')

    def test_session_expiry(self):
        _, _, cookie = self.login(self.worker_a)
        token = cookie.split(';')[0].split('=', 1)[1]
        import sqlite3, time
        con = sqlite3.connect(self.env['PILOT_SESSION_DB'])
        con.execute('UPDATE sessions SET expires=? WHERE token=?', (time.time() - 1, token))
        con.commit()
        con.close()
        status, *_ = self.call(self.worker_b, 'GET', '/api/session', self.auth(cookie))
        self.assertEqual(status, 401)


if __name__ == '__main__':
    unittest.main()

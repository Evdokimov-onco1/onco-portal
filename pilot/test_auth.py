"""Синтетические тесты auth (без сети и реальной почты)."""
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from pilot.auth import AccountStore, AuthService, UsersView, normalize_login_identifier
from pilot.mailer import MailError, Mailer
from pilot.practice import ApiError
from pilot.server import USERS, Pilot, serve_request
from pilot.session_store import MemorySessions, SqliteSessions

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'orp-data.json'


def extract_token(mail_sink):
    body = mail_sink[-1]['body']
    for line in body.splitlines():
        if '#verify=' in line or '#reset=' in line:
            return line.split('#', 1)[1].split('=', 1)[1].strip()
    raise AssertionError('token not in mail')


class FakeReq:
    def __init__(self, pilot, path, mutation=False, body=None, token='', host='127.0.0.1:8789'):
        self.pilot = pilot
        self.path = path
        self._mutation = mutation
        self._body = body or {}
        self._token = token
        self._host = host
        self.out = None
        self.headers = {
            'Host': host,
            'Origin': f'http://{host}',
            'X-Pilot-Request': '1',
            'Content-Type': 'application/json',
        }

    def client_ip(self):
        return '203.0.113.50'

    def guard(self, mutation=False):
        pass

    def body(self):
        return self._body

    def token(self):
        return self._token

    def cookie_name(self):
        return 'test'

    def respond(self, status, value, content_type='application/json; charset=utf-8', cookie=None):
        data = value if isinstance(value, (bytes, bytearray)) else json.loads(
            json.dumps(value, ensure_ascii=False).encode()
        )
        if isinstance(data, bytes):
            self.out = (status, data, content_type, cookie)
        else:
            self.out = (status, value, content_type, cookie)


def run_post(pilot, path, body, token=''):
    req = FakeReq(pilot, path, mutation=True, body=body, token=token)
    serve_request(req, True)
    return req.out


def run_get(pilot, path, token=''):
    req = FakeReq(pilot, path, mutation=False, token=token)
    serve_request(req, False)
    return req.out


class FlakyMailer(Mailer):
    def __init__(self, sink):
        super().__init__({'transport': 'fake', 'sink': sink})
        self.fail_next = 0

    def send(self, to_addr, subject, body_text):
        if self.fail_next:
            self.fail_next -= 1
            raise MailError('transport down')
        return super().send(to_addr, subject, body_text)


def make_auth_stack(tmp, users=None, mailer=None):
    users = users or USERS
    mail_sink = []
    accounts = tmp / 'accounts.sqlite3'
    store = AccountStore(accounts)
    store.seed_once(users)
    if mailer is None:
        mailer = Mailer({'transport': 'fake', 'sink': mail_sink})
    auth = AuthService(store, mailer, 'https://cabinet.test', registration=True)
    sessions = SqliteSessions(tmp / 'sessions.sqlite3')
    pilot = Pilot(tmp / 'pilot.sqlite3', data_path=DATA, sessions=sessions, auth=auth)
    return pilot, mail_sink, store, accounts, mailer


class AuthTests(unittest.TestCase):
    def test_legacy_demo_without_auth(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pilot = Pilot(tmp / 'p.db', data_path=DATA, sessions=MemorySessions())
            st, data, _, cookie = run_post(
                pilot, '/api/login',
                {'username': 'student-a', 'password': 'demo-student-a'},
            )
            self.assertEqual(st, 200)
            self.assertEqual(data['role'], 'student')

    def test_users_view_values(self):
        with tempfile.TemporaryDirectory() as td:
            store = AccountStore(Path(td) / 'a.sqlite3')
            store.seed_once(USERS)
            view = UsersView(store)
            names = {a['name'] for a in view.values()}
            self.assertIn('Преподаватель', names)

    def test_seed_ids_stable(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = tmp / 'accounts.sqlite3'
            s1 = AccountStore(path)
            s1.seed_once(USERS)
            ids1 = s1.list_ids()
            s2 = AccountStore(path)
            s2.seed_once(USERS)
            self.assertEqual(ids1, s2.list_ids())
            self.assertIn('teacher', ids1)

    def test_register_verify_login_role_student(self):
        with tempfile.TemporaryDirectory() as td:
            pilot, sink, store, _, _ = make_auth_stack(Path(td))
            st, data, _, _ = run_post(
                pilot, '/api/auth/register',
                {'email': 'New.User@Example.com', 'name': 'Новый Ординатор', 'role': 'teacher'},
            )
            self.assertEqual(st, 200)
            token = extract_token(sink)
            st, data, _, _ = run_post(
                pilot, '/api/auth/verify',
                {'token': token, 'password': 'secure-pass-12'},
            )
            self.assertEqual(st, 200)
            uid = store.resolve_login('new.user@example.com')
            self.assertIsNotNone(uid)
            self.assertEqual(store.get_account(uid)['role'], 'student')
            st, data, _, cookie = run_post(
                pilot, '/api/login',
                {'username': 'NEW.USER@example.com', 'password': 'secure-pass-12'},
            )
            self.assertEqual(st, 200)
            self.assertEqual(data['role'], 'student')

    def test_unverified_resend_preserves_name(self):
        with tempfile.TemporaryDirectory() as td:
            pilot, sink, store, _, _ = make_auth_stack(Path(td))
            run_post(pilot, '/api/auth/register', {'email': 'r@x.ru', 'name': 'Истинное Имя'})
            uid = store.resolve_login('r@x.ru')
            run_post(pilot, '/api/auth/register', {'email': 'r@x.ru', 'name': 'Подмена'})
            self.assertEqual(store.get_account(uid)['name'], 'Истинное Имя')
            self.assertEqual(len(sink), 2)
            old = extract_token(sink[:1])
            new = extract_token(sink)
            st, _, _, _ = run_post(pilot, '/api/auth/verify', {'token': old, 'password': 'password-twelve'})
            self.assertEqual(st, 400)
            st, _, _, _ = run_post(pilot, '/api/auth/verify', {'token': new, 'password': 'password-twelve'})
            self.assertEqual(st, 200)

    def test_register_mail_fail_then_resend(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            sink = []
            mailer = FlakyMailer(sink)
            mailer.fail_next = 1
            pilot, _, store, _, _ = make_auth_stack(tmp, mailer=mailer)
            st, _, _, _ = run_post(pilot, '/api/auth/register', {'email': 'm@f.ru', 'name': 'M F'})
            self.assertEqual(st, 503)
            self.assertIsNotNone(store.resolve_login('m@f.ru'))
            st, _, _, _ = run_post(pilot, '/api/auth/register', {'email': 'm@f.ru', 'name': 'M F'})
            self.assertEqual(st, 200)
            self.assertEqual(len(sink), 1)

    def test_verify_replay_and_expiry(self):
        with tempfile.TemporaryDirectory() as td:
            pilot, sink, store, acc_path, _ = make_auth_stack(Path(td))
            run_post(pilot, '/api/auth/register', {'email': 'a@b.c', 'name': 'А Б'})
            token = extract_token(sink)
            run_post(pilot, '/api/auth/verify', {'token': token, 'password': 'long-enough-pass'})
            st, data, _, _ = run_post(
                pilot, '/api/auth/verify',
                {'token': token, 'password': 'long-enough-pass'},
            )
            self.assertEqual(st, 400)
            with sqlite3.connect(acc_path) as con:
                con.execute('UPDATE tokens SET expires=?', (time.time() - 10,))
            st, data, _, _ = run_post(
                pilot, '/api/auth/verify',
                {'token': 'stale-token-value-here-xx', 'password': 'long-enough-pass'},
            )
            self.assertEqual(st, 400)

    def test_reset_revokes_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pilot, sink, store, _, _ = make_auth_stack(tmp)
            run_post(pilot, '/api/auth/register', {'email': 'u@t.ru', 'name': 'U T'})
            tok = extract_token(sink)
            run_post(pilot, '/api/auth/verify', {'token': tok, 'password': 'password-twelve'})
            st, _, _, cookie = run_post(
                pilot, '/api/login', {'username': 'u@t.ru', 'password': 'password-twelve'},
            )
            self.assertEqual(st, 200)
            st, data, _, _ = run_get(pilot, '/api/session', token=cookie)
            self.assertEqual(st, 200)
            run_post(pilot, '/api/auth/forgot', {'email': 'u@t.ru'})
            rtok = extract_token(sink)
            run_post(pilot, '/api/auth/reset', {'token': rtok, 'password': 'new-password-99'})
            st, data, _, _ = run_get(pilot, '/api/session', token=cookie)
            self.assertEqual(st, 401)

    def test_concurrent_reset_tokens(self):
        with tempfile.TemporaryDirectory() as td:
            pilot, sink, store, acc_path, _ = make_auth_stack(Path(td))
            run_post(pilot, '/api/auth/register', {'email': 'd@e.f', 'name': 'D E'})
            tok = extract_token(sink)
            run_post(pilot, '/api/auth/verify', {'token': tok, 'password': 'password-twelve'})
            uid = store.resolve_login('d@e.f')
            t1 = __import__('secrets').token_urlsafe(32)
            t2 = __import__('secrets').token_urlsafe(32)
            from pilot.auth import _hash_token
            exp = time.time() + 3600
            with sqlite3.connect(acc_path) as con:
                for t in (t1, t2):
                    con.execute(
                        'INSERT INTO tokens(token_hash,user_id,kind,expires,consumed) VALUES(?,?,?,?,0)',
                        (_hash_token(t), uid, 'reset', exp),
                    )
            results = []

            def worker(tok):
                st, _, _, _ = run_post(
                    pilot, '/api/auth/reset', {'token': tok, 'password': 'new-password-99'},
                )
                results.append(st)

            threads = [threading.Thread(target=worker, args=(t1,)),
                       threading.Thread(target=worker, args=(t2,))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(sum(1 for s in results if s == 200), 1)
            self.assertEqual(sum(1 for s in results if s == 400), 1)

    def test_cross_process_visibility(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pilot1, sink, _, acc, _ = make_auth_stack(tmp)
            run_post(pilot1, '/api/auth/register', {'email': 'cross@x.ru', 'name': 'Cross'})
            store2 = AccountStore(acc)
            self.assertIsNotNone(store2.resolve_login('cross@x.ru'))

    def test_concurrent_token_consume(self):
        with tempfile.TemporaryDirectory() as td:
            pilot, sink, store, _, _ = make_auth_stack(Path(td))
            run_post(pilot, '/api/auth/register', {'email': 'c@d.e', 'name': 'C D'})
            token = extract_token(sink)
            results = []

            def worker():
                st, _, _, _ = run_post(
                    pilot, '/api/auth/verify',
                    {'token': token, 'password': 'password-twelve'},
                )
                results.append(st)

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(sum(1 for s in results if s == 200), 1)
            self.assertEqual(sum(1 for s in results if s == 400), 3)

    def test_concurrent_register_same_email(self):
        with tempfile.TemporaryDirectory() as td:
            pilot, sink, _, _, _ = make_auth_stack(Path(td))
            results = []

            def worker():
                try:
                    st, _, _, _ = run_post(
                        pilot, '/api/auth/register',
                        {'email': 'same@z.z', 'name': 'Same'},
                    )
                    results.append(st)
                except Exception:
                    results.append(500)

            threads = [threading.Thread(target=worker) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertNotIn(500, results)
            self.assertTrue(all(s in (200, 429) for s in results))

    def test_mail_unconfigured_503(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = AccountStore(tmp / 'a.sqlite3')
            store.seed_once(USERS)
            auth = AuthService(store, Mailer({}), 'https://x', registration=True)
            pilot = Pilot(tmp / 'p.db', data_path=DATA, auth=auth)
            st, data, _, _ = run_post(pilot, '/api/auth/register', {'email': 'z@z.z', 'name': 'Z Z'})
            self.assertEqual(st, 503)

    def test_rate_limit_register_email(self):
        with tempfile.TemporaryDirectory() as td:
            pilot, _, _, _, _ = make_auth_stack(Path(td))
            last = 200
            for _ in range(6):
                st, _, _, _ = run_post(
                    pilot, '/api/auth/register',
                    {'email': 'repeat@rate.test', 'name': 'Rate Test'},
                )
                last = st
            self.assertEqual(last, 429)

    def test_rate_limit_ip_independent_of_email_block(self):
        with tempfile.TemporaryDirectory() as td:
            store = AccountStore(Path(td) / 'a.sqlite3')
            ip = '198.51.100.9'
            for _ in range(5):
                store.rate_limit_register(ip, 'blocked@x.test')
            with self.assertRaises(ApiError):
                store.rate_limit_register(ip, 'blocked@x.test')
            store.rate_limit_register(ip, 'other@x.test')

    def test_password_type_validation(self):
        with tempfile.TemporaryDirectory() as td:
            pilot, sink, _, _, _ = make_auth_stack(Path(td))
            run_post(pilot, '/api/auth/register', {'email': 'short@x.ru', 'name': 'Short'})
            token = extract_token(sink)
            st, _, _, _ = run_post(pilot, '/api/auth/verify', {'token': token, 'password': 'short'})
            self.assertEqual(st, 400)

    def test_bad_token_and_login_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            pilot, _, _, _, _ = make_auth_stack(Path(td))
            st, _, _, _ = run_post(pilot, '/api/auth/verify', {'token': 'x' * 300, 'password': 'password-twelve'})
            self.assertEqual(st, 400)
            st, _, _, _ = run_post(
                pilot, '/api/login',
                {'username': 'x' * 300, 'password': 'password-twelve'},
            )
            self.assertEqual(st, 401)

    def test_login_identifier_normalization(self):
        self.assertEqual(normalize_login_identifier('  Teacher  '), 'teacher')
        self.assertEqual(normalize_login_identifier('A@B.C'), 'a@b.c')

    def test_seeded_teacher_login_by_alias(self):
        with tempfile.TemporaryDirectory() as td:
            pilot, _, _, _, _ = make_auth_stack(Path(td))
            st, data, _, _ = run_post(
                pilot, '/api/login',
                {'username': 'teacher', 'password': 'demo-teacher'},
            )
            self.assertEqual(st, 200)
            self.assertEqual(data['role'], 'teacher')

    def test_auth_config_disabled_locally(self):
        with tempfile.TemporaryDirectory() as td:
            pilot = Pilot(Path(td) / 'p.db', data_path=DATA)
            st, data, _, _ = run_get(pilot, '/api/auth/config')
            self.assertEqual(data, {'enabled': False, 'registration': False, 'hosted': False})

    def test_auth_config_hosted_without_auth(self):
        with tempfile.TemporaryDirectory() as td:
            pilot = Pilot(Path(td) / 'p.db', data_path=DATA, hosted=True)
            st, data, _, _ = run_get(pilot, '/api/auth/config')
            self.assertTrue(data.get('hosted'))

    def test_session_missing_auth_version_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pilot, sink, _, _, _ = make_auth_stack(tmp)
            run_post(pilot, '/api/auth/register', {'email': 'v@w.x', 'name': 'V W'})
            tok = extract_token(sink)
            run_post(pilot, '/api/auth/verify', {'token': tok, 'password': 'password-twelve'})
            st, _, _, cookie = run_post(
                pilot, '/api/login', {'username': 'v@w.x', 'password': 'password-twelve'},
            )
            self.assertEqual(st, 200)
            real = pilot.sessions.session_auth_version
            pilot.sessions.session_auth_version = lambda t: None if t == cookie else real(t)
            st, _, _, _ = run_get(pilot, '/api/session', token=cookie)
            self.assertEqual(st, 401)

    def test_verify_rollback_on_missing_account(self):
        with tempfile.TemporaryDirectory() as td:
            store = AccountStore(Path(td) / 'a.sqlite3')
            token = __import__('secrets').token_urlsafe(32)
            from pilot.auth import _hash_token
            th = _hash_token(token)
            with store._connect() as con:
                con.execute(
                    'INSERT INTO tokens(token_hash,user_id,kind,expires,consumed) VALUES(?,?,?,?,0)',
                    (th, 'ghost-user', 'verify', time.time() + 3600),
                )
            with self.assertRaises(ApiError):
                store.verify(token, 'password-twelve', '127.0.0.1')
            with store._connect() as con:
                row = con.execute('SELECT consumed FROM tokens WHERE token_hash=?', (th,)).fetchone()
            self.assertEqual(row[0], 0)

    def test_mailer_smtp_requires_sender(self):
        self.assertFalse(Mailer({'transport': 'smtp', 'smtp_host': 'smtp.test'}).configured())
        self.assertTrue(Mailer({
            'transport': 'fake', 'mail_from': 'noreply@test.example',
        }).configured())

    def test_mailer_sendmail_allowlist(self):
        m = Mailer({'transport': 'sendmail', 'sendmail_path': '/bin/sh',
                    'mail_from': 'noreply@test.example'})
        self.assertFalse(m.configured())

    def test_mailer_smtp_starttls(self):
        msg = mock.MagicMock()
        with mock.patch('pilot.mailer.smtplib.SMTP') as smtp_cls:
            smtp = smtp_cls.return_value.__enter__.return_value
            Mailer({
                'transport': 'smtp',
                'smtp_host': 'smtp.test',
                'smtp_port': '587',
                'mail_from': 'noreply@test.example',
            }).send('u@test.example', 'subj', 'body')
            smtp.starttls.assert_called_once()
            ctx = smtp.starttls.call_args.kwargs.get('context')
            self.assertIsNotNone(ctx)

    def test_mailer_transport_error_generic(self):
        with tempfile.TemporaryDirectory() as td:
            store = AccountStore(Path(td) / 'a.sqlite3')
            mailer = Mailer({'transport': 'smtp', 'smtp_host': 'x', 'mail_from': 'a@b.c'})
            auth = AuthService(store, mailer, 'https://x', registration=True)
            pilot = Pilot(Path(td) / 'p.db', data_path=DATA, auth=auth)
            with mock.patch.object(mailer, 'send', side_effect=MailError('secret token leak')):
                st, data, _, _ = run_post(pilot, '/api/auth/register', {'email': 'e@f.g', 'name': 'E F'})
            self.assertEqual(st, 503)
            self.assertNotIn('secret', data.get('error', ''))


if __name__ == '__main__':
    unittest.main()

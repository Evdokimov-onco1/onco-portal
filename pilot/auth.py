"""Регистрация по e-mail и восстановление пароля (accounts.sqlite3, stdlib)."""
import hashlib
import hmac
import re
import secrets
from contextlib import contextmanager
import sqlite3
import threading
import time
import uuid
from pilot.practice import ApiError
from pilot.mailer import MailError

PBKDF2_ITERS = 600_000

LOGIN_MAX = 254
TOKEN_MAX = 256

def make_password_hash(password, iterations=PBKDF2_ITERS):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode(), iterations).hex()
    return f'pbkdf2${iterations}${salt}${digest}'


def verify_password(account, password):
    stored = account.get('password_hash')
    if isinstance(stored, str) and stored.startswith('pbkdf2$'):
        try:
            _, iters, salt, expect = stored.split('$', 3)
            digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                                         salt.encode(), int(iters)).hex()
            return hmac.compare_digest(digest, expect)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(account.get('password', ''), password)

TOKEN_TTL = 3600
NAME_MIN, NAME_MAX = 2, 120
EMAIL_MAX = 254
RATE_WINDOW = 900

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_UNIFORM_OK = (
    'Если указанный адрес можно использовать, на него отправлено письмо с инструкцией. '
    'Проверьте почту (включая папку «Спам»).'
)
_VERIFY_OK = 'Пароль установлен. Теперь можно войти в кабинет.'
_RESET_OK = 'Пароль обновлён. Войдите с новым паролем.'


def normalize_email(value):
    if not isinstance(value, str):
        return ''
    return value.strip().lower()


def normalize_login_identifier(value):
    if not isinstance(value, str):
        return ''
    key = value.strip()
    if not key or len(key) > LOGIN_MAX:
        return ''
    if '@' in key:
        return normalize_email(key)
    return key.lower()


def _hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _password_ok(password):
    return isinstance(password, str) and 12 <= len(password) <= 128


def _token_ok(token):
    return isinstance(token, str) and 0 < len(token) <= TOKEN_MAX


class UsersView:
    """Dict-подобное представление аккаунтов для Pilot (ключ — стабильный user id)."""

    def __init__(self, store):
        self._store = store

    def get(self, key, default=None):
        row = self._store.get_account(key)
        return row if row is not None else default

    def __getitem__(self, key):
        row = self.get(key)
        if row is None:
            raise KeyError(key)
        return row

    def __contains__(self, key):
        return self.get(key) is not None

    def __iter__(self):
        return iter(self._store.list_ids())

    def keys(self):
        return self._store.list_ids()

    def items(self):
        for uid in self._store.list_ids():
            yield uid, self[uid]

    def values(self):
        for uid in self._store.list_ids():
            yield self[uid]


class AccountStore:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        self._init_schema()

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA busy_timeout=10000')
        try:
            with con:
                yield con
        finally:
            con.close()

    def _init_schema(self):
        with self._connect() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts(
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('student','teacher')),
                    password_hash TEXT NOT NULL DEFAULT '',
                    email_verified INTEGER NOT NULL DEFAULT 0,
                    auth_version INTEGER NOT NULL DEFAULT 1,
                    login_alias TEXT UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(email);
                CREATE TABLE IF NOT EXISTS tokens(
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('verify','reset')),
                    expires REAL NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS rate_limits(
                    bucket TEXT PRIMARY KEY,
                    count INTEGER NOT NULL,
                    window_start REAL NOT NULL
                );
            ''')

    def seed_once(self, users):
        with self._lock, self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT value FROM meta WHERE key=?', ('seeded',)).fetchone()
            if row:
                con.execute('COMMIT')
                return
            for uid, account in users.items():
                if not isinstance(account, dict):
                    continue
                role = account.get('role')
                if role not in ('student', 'teacher'):
                    continue
                name = account.get('name') or uid
                ph = account.get('password_hash')
                if not ph and account.get('password'):
                    ph = make_password_hash(account['password'], PBKDF2_ITERS)
                if not ph:
                    ph = ''
                email = normalize_email(account.get('email', '')) or None
                verified = 1 if ph else 0
                con.execute(
                    '''INSERT OR IGNORE INTO accounts
                       (id, email, name, role, password_hash, email_verified, auth_version, login_alias)
                       VALUES (?,?,?,?,?,?,1,?)''',
                    (uid, email, name, role, ph, verified, uid if uid != email else None),
                )
            con.execute('INSERT INTO meta(key,value) VALUES(?,?)', ('seeded', '1'))
            con.execute('COMMIT')

    def list_ids(self):
        with self._connect() as con:
            return [r[0] for r in con.execute('SELECT id FROM accounts ORDER BY id')]

    def get_account(self, user_id):
        with self._connect() as con:
            row = con.execute('SELECT * FROM accounts WHERE id=?', (user_id,)).fetchone()
        if not row:
            return None
        return self._row_account(row)

    def _row_account(self, row):
        return {
            'name': row['name'],
            'role': row['role'],
            'password_hash': row['password_hash'] or None,
            'password': '',
            'email': row['email'],
            'email_verified': bool(row['email_verified']),
            'auth_version': row['auth_version'],
        }

    def resolve_login(self, login):
        if not isinstance(login, str):
            return None
        key = login.strip()
        if not key or len(key) > LOGIN_MAX:
            return None
        with self._connect() as con:
            row = con.execute('SELECT id FROM accounts WHERE id=? OR login_alias=?',
                              (key, key)).fetchone()
            if row:
                return row[0]
            email = normalize_email(key)
            if email:
                row = con.execute('SELECT id FROM accounts WHERE email=?', (email,)).fetchone()
                if row:
                    return row[0]
        return None

    def get_auth_version(self, user_id):
        with self._connect() as con:
            row = con.execute('SELECT auth_version FROM accounts WHERE id=?', (user_id,)).fetchone()
        return row[0] if row else None

    def _check_rate(self, con, bucket, limit, window):
        now = time.time()
        row = con.execute('SELECT count, window_start FROM rate_limits WHERE bucket=?',
                          (bucket,)).fetchone()
        if not row or now - row['window_start'] >= window:
            con.execute('INSERT OR REPLACE INTO rate_limits(bucket,count,window_start) VALUES(?,?,?)',
                        (bucket, 1, now))
            return
        if row['count'] >= limit:
            raise ApiError(429, 'Слишком много попыток. Подождите и повторите позже.')
        con.execute('UPDATE rate_limits SET count=count+1 WHERE bucket=?', (bucket,))

    def _rate_bucket(self, bucket, limit, window):
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                self._check_rate(con, bucket, limit, window)
                con.execute('COMMIT')
            except ApiError:
                con.execute('ROLLBACK')
                raise

    def rate_limit_register(self, client_ip, email_hint=None):
        if client_ip:
            self._rate_bucket(f'ip:{client_ip}:register', 30, RATE_WINDOW)
        email = normalize_email(email_hint) if email_hint else ''
        if email:
            self._rate_bucket(f'email:{email}:register', 5, RATE_WINDOW)

    def rate_limit_login(self, client_ip, login_hint=None):
        if client_ip:
            self._rate_bucket(f'ip:{client_ip}:login', 100, RATE_WINDOW)
        ident = normalize_login_identifier(login_hint) if login_hint else ''
        if ident:
            self._rate_bucket(f'id:{ident}:login', 20, RATE_WINDOW)

    def rate_limit(self, action, client_ip, email=None):
        if action == 'register':
            self.rate_limit_register(client_ip, email)
            return
        if action == 'login':
            self.rate_limit_login(client_ip, email)
            return
        limits = {
            'forgot': (5, RATE_WINDOW),
            'verify': (10, RATE_WINDOW),
            'reset': (10, RATE_WINDOW),
        }
        spec = limits.get(action)
        if not spec:
            return
        limit, window = spec
        if client_ip:
            self._rate_bucket(f'ip:{client_ip}:{action}', limit, window)
        if email:
            self._rate_bucket(f'email:{email}:{action}', limit, window)

    def _issue_verify_token(self, con, user_id):
        token = secrets.token_urlsafe(32)
        th = _hash_token(token)
        exp = time.time() + TOKEN_TTL
        con.execute('DELETE FROM tokens WHERE user_id=? AND kind=?', (user_id, 'verify'))
        con.execute(
            'INSERT INTO tokens(token_hash,user_id,kind,expires,consumed) VALUES(?,?,?,?,0)',
            (th, user_id, 'verify', exp),
        )
        return token

    def register(self, email, name, client_ip):
        self.rate_limit_register(client_ip, email if isinstance(email, str) else None)
        email = normalize_email(email)
        if not email or len(email) > EMAIL_MAX or not _EMAIL_RE.match(email):
            raise ApiError(400, 'Укажите корректный адрес электронной почты.')
        if not isinstance(name, str):
            raise ApiError(400, 'Укажите имя.')
        name = name.strip()
        if len(name) < NAME_MIN or len(name) > NAME_MAX:
            raise ApiError(400, f'Имя: от {NAME_MIN} до {NAME_MAX} символов.')
        token = None
        with self._lock, self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                row = con.execute(
                    'SELECT id, email_verified, name FROM accounts WHERE email=?', (email,)
                ).fetchone()
                if row:
                    if row['email_verified']:
                        con.execute('COMMIT')
                        return _UNIFORM_OK, None
                    token = self._issue_verify_token(con, row['id'])
                    con.execute('COMMIT')
                    return _UNIFORM_OK, token
                user_id = str(uuid.uuid4())
                con.execute(
                    '''INSERT INTO accounts(id,email,name,role,password_hash,email_verified,auth_version)
                       VALUES(?,?,?,?,?,0,1)''',
                    (user_id, email, name, 'student', ''),
                )
                token = self._issue_verify_token(con, user_id)
                con.execute('COMMIT')
            except sqlite3.IntegrityError:
                con.execute('ROLLBACK')
                raise ApiError(503, 'Не удалось завершить регистрацию. Попробуйте позже.')
        return _UNIFORM_OK, token

    def forgot(self, email, client_ip):
        self.rate_limit('forgot', client_ip, normalize_email(email) if isinstance(email, str) else None)
        email = normalize_email(email)
        if not email or len(email) > EMAIL_MAX:
            raise ApiError(400, 'Укажите корректный адрес электронной почты.')
        token = None
        with self._connect() as con:
            row = con.execute(
                'SELECT id, email_verified, password_hash FROM accounts WHERE email=?', (email,)
            ).fetchone()
            if row and row['email_verified'] and row['password_hash']:
                token = secrets.token_urlsafe(32)
                th = _hash_token(token)
                exp = time.time() + TOKEN_TTL
                con.execute(
                    'INSERT INTO tokens(token_hash,user_id,kind,expires,consumed) VALUES(?,?,?,?,0)',
                    (th, row['id'], 'reset', exp),
                )
        return _UNIFORM_OK, token

    def verify(self, token, password, client_ip):
        self.rate_limit('verify', client_ip, None)
        if not _token_ok(token):
            raise ApiError(400, 'Недействительная ссылка.')
        if not _password_ok(password):
            raise ApiError(400, 'Пароль: от 12 до 128 символов.')
        ph = make_password_hash(password, PBKDF2_ITERS)
        th = _hash_token(token)
        now = time.time()
        with self._lock, self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute(
                'SELECT user_id, kind, expires, consumed FROM tokens WHERE token_hash=?', (th,)
            ).fetchone()
            if not row or row['kind'] != 'verify' or row['consumed'] or row['expires'] <= now:
                con.execute('ROLLBACK')
                raise ApiError(400, 'Ссылка недействительна или устарела.')
            updated = con.execute(
                'UPDATE tokens SET consumed=1 WHERE token_hash=? AND consumed=0', (th,)
            ).rowcount
            if updated != 1:
                con.execute('ROLLBACK')
                raise ApiError(400, 'Ссылка уже использована.')
            user_id = row['user_id']
            updated_acct = con.execute(
                'UPDATE accounts SET password_hash=?, email_verified=1 WHERE id=?',
                (ph, user_id),
            ).rowcount
            if updated_acct != 1:
                con.execute('ROLLBACK')
                raise ApiError(400, 'Ссылка недействительна или устарела.')
            con.execute('DELETE FROM tokens WHERE user_id=? AND kind=?', (user_id, 'verify'))
            con.execute('COMMIT')
        return _VERIFY_OK

    def reset_password(self, token, password, client_ip, sessions):
        self.rate_limit('reset', client_ip, None)
        if not _token_ok(token):
            raise ApiError(400, 'Недействительная ссылка.')
        if not _password_ok(password):
            raise ApiError(400, 'Пароль: от 12 до 128 символов.')
        ph = make_password_hash(password, PBKDF2_ITERS)
        th = _hash_token(token)
        now = time.time()
        with self._lock, self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute(
                'SELECT user_id, kind, expires, consumed FROM tokens WHERE token_hash=?', (th,)
            ).fetchone()
            if not row or row['kind'] != 'reset' or row['consumed'] or row['expires'] <= now:
                con.execute('ROLLBACK')
                raise ApiError(400, 'Ссылка недействительна или устарела.')
            updated = con.execute(
                'UPDATE tokens SET consumed=1 WHERE token_hash=? AND consumed=0', (th,)
            ).rowcount
            if updated != 1:
                con.execute('ROLLBACK')
                raise ApiError(400, 'Ссылка уже использована.')
            user_id = row['user_id']
            if con.execute(
                'UPDATE accounts SET password_hash=?, auth_version=auth_version+1 WHERE id=?',
                (ph, user_id),
            ).rowcount != 1:
                con.execute('ROLLBACK')
                raise ApiError(400, 'Ссылка недействительна или устарела.')
            con.execute('DELETE FROM tokens WHERE user_id=? AND kind=?', (user_id, 'reset'))
            ver = con.execute('SELECT auth_version FROM accounts WHERE id=?', (user_id,)).fetchone()[0]
            con.execute('COMMIT')
        if sessions:
            sessions.destroy_all_for_user(user_id)
        return _RESET_OK, ver


    def check_login_allowed(self, user_id, account):
        if not account:
            return False
        if not account.get('email_verified') and account.get('email'):
            return False
        ph = account.get('password_hash')
        if not ph and not account.get('password'):
            return False
        return True


class AuthService:
    def __init__(self, store, mailer, public_base_url, registration=True, hosted=False):
        self.store = store
        self.mailer = mailer
        self.public_base_url = (public_base_url or '').rstrip('/')
        self.registration_enabled = registration
        self.hosted = hosted
        self.users = UsersView(store)

    def config(self):
        return {
            'enabled': True,
            'registration': self.registration_enabled,
            'hosted': self.hosted,
        }

    def _send_link(self, kind, email, token):
        if not token:
            return
        fragment = 'verify' if kind == 'verify' else 'reset'
        url = f'{self.public_base_url}/#{fragment}={token}'
        if kind == 'verify':
            subject = 'Подтверждение регистрации — учебный кабинет ONCO'
            body = (
                f'Здравствуйте!\n\n'
                f'Для завершения регистрации откройте ссылку и задайте пароль:\n{url}\n\n'
                f'Ссылка действует ограниченное время и предназначена только для вас.\n'
            )
        else:
            subject = 'Восстановление пароля — учебный кабинет ONCO'
            body = (
                f'Здравствуйте!\n\n'
                f'Чтобы задать новый пароль, откройте ссылку:\n{url}\n\n'
                f'Если вы не запрашивали сброс, проигнорируйте это письмо.\n'
            )
        self.mailer.send(email, subject, body)

    def register(self, body, client_ip):
        if not self.registration_enabled:
            raise ApiError(403, 'Регистрация отключена.')
        if not self.mailer.configured():
            raise ApiError(503, 'Отправка писем временно недоступна. Попробуйте позже.')
        email = body.get('email')
        name = body.get('name')
        if body.get('role') is not None:
            pass  # игнорируем переданную роль
        msg, token = self.store.register(email, name, client_ip)
        if token:
            try:
                self._send_link('verify', normalize_email(email), token)
            except MailError:
                raise ApiError(503, 'Отправка писем временно недоступна. Попробуйте позже.')
        return {'ok': True, 'message': msg}

    def forgot(self, body, client_ip):
        if not self.mailer.configured():
            raise ApiError(503, 'Отправка писем временно недоступна. Попробуйте позже.')
        email = body.get('email')
        msg, token = self.store.forgot(email, client_ip)
        if token:
            try:
                self._send_link('reset', normalize_email(email), token)
            except MailError:
                raise ApiError(503, 'Отправка писем временно недоступна. Попробуйте позже.')
        return {'ok': True, 'message': msg}

    def verify(self, body, client_ip):
        return {'ok': True, 'message': self.store.verify(body.get('token'), body.get('password'), client_ip)}

    def reset(self, body, client_ip, sessions):
        msg, _ = self.store.reset_password(body.get('token'), body.get('password'), client_ip, sessions)
        return {'ok': True, 'message': msg}

    def login(self, username, password, client_ip, sessions):
        self.store.rate_limit_login(client_ip, username)
        if isinstance(username, str) and len(username) > LOGIN_MAX:
            raise ApiError(401, 'Неверный логин или пароль.')
        if isinstance(password, str) and len(password) > 128:
            raise ApiError(401, 'Неверный логин или пароль.')
        user_id = self.store.resolve_login(username)
        account = self.store.get_account(user_id) if user_id else None
        if not self.store.check_login_allowed(user_id, account):
            raise ApiError(401, 'Неверный логин или пароль.')
        if not isinstance(password, str) or not verify_password(account, password):
            raise ApiError(401, 'Неверный логин или пароль.')
        if sessions and hasattr(sessions, 'create_with_version'):
            return sessions.create_with_version(user_id, account.get('auth_version', 1))
        return sessions.create(user_id)

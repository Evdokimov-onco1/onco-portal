"""WSGI-вход для размещённого пилота (Timeweb shared mod_wsgi и подобные).

Обязательные переменные окружения:
  PILOT_HOST        — точный публичный hostname без схемы (staging.example.ru)
  PILOT_DB          — путь к SQLite БД пилота ВНЕ public_html
  PILOT_USERS_FILE  — JSON-файл реальных аккаунтов ВНЕ public_html:
                      {"user1": {"name": "Имя", "role": "student|teacher",
                                 "password_hash": "pbkdf2$iters$salt$hex",
                                 "modules": "all" | ["M01", ...]}}
Необязательные:
  PILOT_SESSION_DB  — файл сессий SQLite (по умолчанию pilot-sessions.sqlite3
                      рядом с PILOT_DB); PILOT_DATA — путь к orp-data.json.

Демонстрационные аккаунты в hosted-режиме не используются: без корректного
PILOT_USERS_FILE приложение не стартует (fail closed). Заголовки
X-Forwarded-* намеренно игнорируются — доверяем только Host/Origin,
которые выставил наш фронт-сервер.
"""
import json
import os
import re
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path

from pilot.practice import ApiError
from pilot.server import (ROOT, Pilot, base_headers, serve_request,
                          session_cookie_header)
from pilot.session_store import SqliteSessions
from pilot.auth import AccountStore, AuthService
from pilot.mailer import mailer_from_env

COOKIE_NAME = 'onco_pilot'
REQUIRED_ENV = ('PILOT_HOST', 'PILOT_DB', 'PILOT_USERS_FILE')
_HASH_FORMAT = re.compile(r'^pbkdf2\$[1-9]\d*\$[0-9a-fA-F]{8,}\$[0-9a-fA-F]{32,}$')

_ENV_HEADERS = {'HTTP_HOST': 'Host', 'HTTP_ORIGIN': 'Origin',
                'HTTP_COOKIE': 'Cookie', 'HTTP_X_PILOT_REQUEST': 'X-Pilot-Request'}


def load_users(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not data:
        raise ValueError('Файл аккаунтов пуст или не является объектом.')
    users = {}
    for uid, account in data.items():
        if (not isinstance(account, dict) or
                account.get('role') not in ('student', 'teacher') or
                not account.get('name') or
                not _HASH_FORMAT.match(str(account.get('password_hash', '')))):
            raise ValueError(f'Некорректная запись аккаунта: {uid!r}')
        users[uid] = account
    return users


def resolve_private(path_value, label):
    """Реальный резолвинг пути (expanduser+symlinks): файл обязан лежать
    вне любого public_html — иначе fail closed."""
    p = Path(path_value).expanduser().resolve()
    if 'public_html' in p.parts:
        raise RuntimeError(f'{label} должен лежать вне public_html: {p}')
    return p


def build_assignments(users, modules):
    out = {}
    for uid, account in users.items():
        if account.get('role') != 'teacher':
            continue
        mods = account.get('modules', 'all')
        out[uid] = set(modules) if mods == 'all' else set(mods)
    return out


class _Headers:
    def __init__(self, environ):
        self._h = {}
        for key, name in _ENV_HEADERS.items():
            if environ.get(key):
                self._h[name] = environ[key]
        for key, name in (('CONTENT_TYPE', 'Content-Type'),
                          ('CONTENT_LENGTH', 'Content-Length')):
            if environ.get(key):
                self._h[name] = environ[key]

    def get(self, name, default=''):
        return self._h.get(name, default)


class Request:
    """Тот же интерфейс, что у Handler: pilot/path/headers/body/token/respond/guard."""

    def __init__(self, app, environ):
        self.app = app
        self.environ = environ
        self.headers = _Headers(environ)
        query = environ.get('QUERY_STRING', '')
        self.path = environ.get('PATH_INFO', '/') + (('?' + query) if query else '')
        self.out_status, self.out_headers, self.out_body = 500, [], b''

    @property
    def pilot(self):
        return self.app.pilot

    @property
    def cookie_name(self):
        return COOKIE_NAME

    def token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            return cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else ''
        except Exception:
            return ''

    def client_ip(self):
        return self.environ.get('REMOTE_ADDR') or '127.0.0.1'

    def guard(self, mutation=False):
        # wsgi.url_scheme ставит наш фронт-сервер; X-Forwarded-* не доверяем.
        if str(self.environ.get('wsgi.url_scheme', '')).lower() != 'https':
            raise ApiError(403, 'Пилот доступен только по HTTPS.')
        # Точный authority: настроенный hostname, допускаем явный :443.
        host = self.headers.get('Host', '').lower().rstrip('.')
        if host not in (self.app.host, f'{self.app.host}:443'):
            raise ApiError(403, 'Пилот доступен только по назначенному адресу.')
        if mutation and (self.headers.get('Origin') != f'https://{self.app.host}' or
                         self.headers.get('X-Pilot-Request') != '1'):
            raise ApiError(403, 'Запрос должен исходить со страницы пилота.')

    def body(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise ApiError(415, 'Ожидается JSON.')
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 100000:
                raise ApiError(413, 'Слишком большой или пустой запрос.')
            data = json.loads(self.environ['wsgi.input'].read(length))
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeError):
            raise ApiError(400, 'Не удалось прочитать запрос.')

    def respond(self, status, value, content_type='application/json; charset=utf-8', cookie=None):
        data = (json.dumps(value, ensure_ascii=False).encode()
                if content_type.startswith('application/json') else value)
        headers = base_headers(content_type, len(data))
        if cookie is not None:
            headers.append(('Set-Cookie',
                            session_cookie_header(COOKIE_NAME, cookie, secure=True)))
        self.out_status, self.out_headers, self.out_body = status, headers, data


class App:
    def __init__(self, pilot, host):
        self.pilot = pilot
        self.host = host

    def __call__(self, environ, start_response):
        req = Request(self, environ)
        method = environ.get('REQUEST_METHOD', 'GET').upper()
        if method == 'GET':
            serve_request(req, False)
        elif method == 'POST':
            serve_request(req, True)
        else:
            req.respond(405, {'error': 'Метод не поддерживается.'})
        try:
            phrase = HTTPStatus(req.out_status).phrase
        except ValueError:
            phrase = 'Status'
        start_response(f'{req.out_status} {phrase}', req.out_headers)
        return [req.out_body]


def make_app(env=None):
    env = os.environ if env is None else env
    missing = [key for key in REQUIRED_ENV if not env.get(key)]
    if missing:
        raise RuntimeError('Hosted-режим требует переменные: ' + ', '.join(missing))
    host = env['PILOT_HOST'].strip().lower().rstrip('/')
    if not host or '/' in host or ':' in host:
        raise RuntimeError('PILOT_HOST должен быть hostname без схемы и порта.')
    db = resolve_private(env['PILOT_DB'], 'PILOT_DB')
    if not db.is_absolute():
        raise RuntimeError('PILOT_DB должен быть абсолютным путём вне public_html.')
    users = load_users(resolve_private(env['PILOT_USERS_FILE'], 'PILOT_USERS_FILE'))
    sessions_db = (resolve_private(env['PILOT_SESSION_DB'], 'PILOT_SESSION_DB')
                   if env.get('PILOT_SESSION_DB') else db.parent / 'pilot-sessions.sqlite3')
    assignment_users = users
    auth = None
    if str(env.get('PILOT_AUTH_ENABLED', '')).lower() in ('1', 'true', 'yes'):
        accounts_db = (resolve_private(env['PILOT_ACCOUNTS_DB'], 'PILOT_ACCOUNTS_DB')
                       if env.get('PILOT_ACCOUNTS_DB') else db.parent / 'accounts.sqlite3')
        store = AccountStore(accounts_db)
        store.seed_once(users)
        public_url = env.get('PILOT_PUBLIC_URL', f'https://{host}').strip()
        reg = str(env.get('PILOT_AUTH_REGISTRATION', '1')).lower() not in ('0', 'false', 'no')
        auth = AuthService(store, mailer_from_env(env), public_url, registration=reg, hosted=True)
        users = auth.users
    pilot = Pilot(db, data_path=env.get('PILOT_DATA', ROOT / 'data/orp-data.json'),
                  users=users, sessions=SqliteSessions(sessions_db), auth=auth, hosted=True,
                  sequential=str(env.get('PILOT_SEQUENTIAL_MODULES', '0')).lower() in ('1', 'true', 'yes'))
    pilot.assignments = build_assignments(assignment_users,
                                          pilot.modules)
    return App(pilot, host)


_app = None


def application(environ, start_response):
    """mod_wsgi entry point: ленивая инициализация на первый запрос."""
    global _app
    if _app is None:
        _app = make_app()
    return _app(environ, start_response)

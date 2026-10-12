"""Loopback-only learning pilot. Demo credentials MUST NOT be deployed publicly."""
import argparse
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
from urllib.parse import urlsplit

from pilot.store import Store
from pilot.quiz import QuizStore
from pilot.materials import Materials, ReadingStore
from pilot.logbook import Logbook
from pilot.practice import PREFIX, ApiError, Practice
from pilot.completion import Completion
from pilot.session_store import MemorySessions

ROOT = Path(__file__).resolve().parents[1]
USERS = {
    'student-a': {'name': 'Ординатор А', 'role': 'student', 'password': 'demo-student-a'},
    'student-b': {'name': 'Ординатор Б', 'role': 'student', 'password': 'demo-student-b'},
    'teacher': {'name': 'Преподаватель', 'role': 'teacher', 'password': 'demo-teacher'},
}


def clinical(rows):
    return [r for r in rows if not r['case'].startswith(PREFIX)]


def make_password_hash(password, iterations=200_000):
    """pbkdf2-хэш для файла аккаунтов hosted-режима (генерация офлайн)."""
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


class Pilot:
    def __init__(self, db_path, data_path=ROOT / 'data/orp-data.json', users=None, sessions=None, auth=None,
                 hosted=False):
        self.store = Store(str(db_path))
        self.auth = auth
        self.admin = None
        self.hosted = hosted
        data = json.loads(Path(data_path).read_text())
        self.quiz = QuizStore(str(db_path))
        self.reading = ReadingStore(db_path)
        self.materials = Materials(data, ROOT / 'docs/audit-2026-10-10/FACULTY_VIDEO_CATALOGUE.csv',
                                   ROOT / 'data' / 'video-suggestions.json')
        self.questions = data.get('questions', [])
        self.modules = {m['module_id']: m for m in data['modules']}
        self.versions = {k: hashlib.sha256(json.dumps(m['clinical_cases'], ensure_ascii=False,
                        sort_keys=True).encode()).hexdigest()[:16] for k, m in self.modules.items()}
        self.users = auth.users if auth else (users or USERS)
        # All demo modules are assigned to the demo teacher. This is NOT a real roster.
        self.assignments = {'teacher': set(self.modules)}
        self.logbook = Logbook(db_path)
        self.practice = Practice(self, data)
        self.completion = Completion(self, self.users)
        self.sessions = sessions or MemorySessions()
        self.lock = threading.Lock()

    def login(self, username, password, client_ip='127.0.0.1'):
        if self.auth:
            return self.auth.login(username, password, client_ip, self.sessions)
        account = self.users.get(username) if isinstance(username, str) else None
        if not account or not isinstance(password, str) or not verify_password(account, password):
            raise ApiError(401, 'Неверный логин или пароль.')
        return self.sessions.create(username)

    def user(self, token):
        username = self.sessions.user(token)
        account = self.users.get(username) if username else None
        if not account:
            raise ApiError(401, 'Войдите в учётную запись.')
        if self.auth:
            if not hasattr(self.sessions, 'session_auth_version'):
                raise ApiError(401, 'Войдите в учётную запись.')
            ver = self.sessions.session_auth_version(token)
            if ver is None:
                raise ApiError(401, 'Войдите в учётную запись.')
            expected = account.get('auth_version', 1)
            if ver != expected:
                raise ApiError(401, 'Войдите в учётную запись.')
        if self.admin and not self.admin.enabled(username):
            raise ApiError(401, 'Доступ к аккаунту отключён. Обратитесь к администратору.')
        result = {'id': username, 'name': account['name'], 'role': account['role']}
        if self.admin:
            result['is_admin'] = self.admin.is_admin(username)
        return result

    def module(self, module_id):
        if module_id not in self.modules:
            raise ApiError(404, 'Модуль не найден.')
        return self.modules[module_id]

    def case(self, module_id, case_id, version):
        m = self.module(module_id)
        if version != self.versions[module_id]:
            raise ApiError(409, 'Материал изменился. Скопируйте черновик и обновите страницу.')
        cases = {f'C{i+1}': c for i, c in enumerate(m['clinical_cases'])}
        if case_id not in cases:
            raise ApiError(404, 'Задача не найдена.')
        return cases[case_id]

    def teacher(self, user, module_id):
        if user['role'] != 'teacher' or module_id not in self.assignments.get(user['id'], set()):
            raise ApiError(403, 'Проверка доступна только назначенному преподавателю.')

    def student(self, user):
        if user['role'] != 'student':
            raise ApiError(403, 'Отправка доступна только ординатору.')

    def module_view(self, user, module_id):
        m = self.module(module_id)
        teacher = user['role'] == 'teacher'
        if teacher:
            self.teacher(user, module_id)
        attempts = clinical(self.store.submissions(student=user['id'], module=module_id)) if not teacher else []
        version = self.versions[module_id]
        unlocked = {r['case'] for r in attempts if r['version'] == version}
        cases = []
        for i, c in enumerate(m['clinical_cases']):
            cid = f'C{i+1}'
            item = {k: c.get(k, '') for k in ('title', 'vignette', 'questions')}
            item['id'] = cid
            if teacher or cid in unlocked:
                item.update(answer=c.get('answer', ''), sources=c.get('sources', []))
            cases.append(item)
        content = self.materials.view(m)
        return {'id': module_id, 'title': m['module_title'], 'year': m['pedagogical_year'],
                'version': version, 'cases': cases, 'attempts': attempts,
                'drafts': {k: v for k, v in self.store.drafts(user['id'], module_id, version).items()
                           if not k.startswith(PREFIX)} if not teacher else {},
                'materials': content, 'opened': self.reading.get(user['id'], module_id, content['version']),
                'question_count': len([q for q in self.questions if q['module'] == module_id]),
                'quizzes': self.quiz.history(user['id'], module_id) if not teacher else []}

    def submission_view(self, user, sid):
        row = self.store.get(sid)
        if row is None or row['case'].startswith(PREFIX):  # practice rows use /api/practice/*
            raise ApiError(404, 'Ответ не найден.')
        if user['role'] == 'teacher':
            self.teacher(user, row['module'])
        elif row['student'] != user['id']:
            raise ApiError(404, 'Ответ не найден.')
        row['student_name'] = self.users.get(row['student'], {}).get('name', row['student'])
        return row


CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self'; media-src 'self' https://video.rosoncoweb.ru; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def base_headers(content_type, length):
    return [('Content-Type', content_type),
            ('Content-Length', str(length)),
            ('Cache-Control', 'no-store'),
            ('X-Content-Type-Options', 'nosniff'),
            ('Referrer-Policy', 'no-referrer'),
            ('Content-Security-Policy', CSP)]


def session_cookie_header(name, value, secure=False):
    header = f'{name}={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={28800 if value else 0}'
    return header + '; Secure' if secure else header


class Handler(BaseHTTPRequestHandler):
    server_version = 'ONCO-Pilot'

    @property
    def pilot(self):
        return self.server.pilot

    @property
    def cookie_name(self):
        return f'onco_pilot_{self.server.server_port}'

    def token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            return cookie[self.cookie_name].value if self.cookie_name in cookie else ''
        except Exception:
            return ''

    def respond(self, status, value, content_type='application/json; charset=utf-8', cookie=None):
        data = json.dumps(value, ensure_ascii=False).encode() if content_type.startswith('application/json') else value
        self.send_response(status)
        for key, val in base_headers(content_type, len(data)):
            self.send_header(key, val)
        if cookie is not None:
            self.send_header('Set-Cookie', session_cookie_header(self.cookie_name, cookie))
        self.end_headers()
        self.wfile.write(data)

    def client_ip(self):
        return self.client_address[0]

    def guard(self, mutation=False):
        port = self.server.server_port
        allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
        host = self.headers.get('Host', '')
        if host not in allowed:
            raise ApiError(403, 'Пилот доступен только на этом компьютере.')
        if mutation and (self.headers.get('Origin') != f'http://{host}' or
                         self.headers.get('X-Pilot-Request') != '1'):
            raise ApiError(403, 'Запрос должен исходить со страницы пилота.')

    def body(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise ApiError(415, 'Ожидается JSON.')
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 100000:
                raise ApiError(413, 'Слишком большой или пустой запрос.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeError):
            raise ApiError(400, 'Не удалось прочитать запрос.')

    def do_GET(self):
        self.run(False)

    def do_POST(self):
        self.run(True)

    def run(self, mutation):
        serve_request(self, mutation)


def serve_request(req, mutation):
    """Общая маршрутизация для BaseHTTPRequestHandler (локально) и WSGI-запроса.

    req должен давать: .pilot, .path, .headers, .body(), .token(), .guard(),
    .respond(), .cookie_name. Поведение одинаковое на обоих транспортах."""
    try:
        req.guard(mutation)
        path = urlsplit(req.path).path
        if not mutation:
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/learning.js': ('learning.js', 'text/javascript; charset=utf-8'),
                      '/practice.js': ('practice.js', 'text/javascript; charset=utf-8'),
                      '/completion.js': ('completion.js', 'text/javascript; charset=utf-8'),
                      '/admin.js': ('admin.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path in assets:
                name, mime = assets[path]
                return req.respond(200, (ROOT / 'pilot/web' / name).read_bytes(), mime)
        body = req.body() if mutation else {}
        if not isinstance(body, dict):
            raise ApiError(400, 'Ожидается объект JSON.')
        client_ip = req.client_ip() if hasattr(req, 'client_ip') else '127.0.0.1'
        if not mutation and path == '/api/auth/config':
            hosted = getattr(req.pilot, 'hosted', False)
            if req.pilot.auth:
                return req.respond(200, req.pilot.auth.config())
            return req.respond(200, {'enabled': False, 'registration': False, 'hosted': hosted})
        auth_paths = {
            '/api/auth/register': 'register',
            '/api/auth/forgot': 'forgot',
            '/api/auth/verify': 'verify',
            '/api/auth/reset': 'reset',
        }
        if mutation and path in auth_paths:
            if not req.pilot.auth:
                raise ApiError(404, 'Страница не найдена.')
            auth = req.pilot.auth
            if path == '/api/auth/register':
                return req.respond(200, auth.register(body, client_ip))
            if path == '/api/auth/forgot':
                return req.respond(200, auth.forgot(body, client_ip))
            if path == '/api/auth/verify':
                return req.respond(200, auth.verify(body, client_ip))
            if path == '/api/auth/reset':
                return req.respond(200, auth.reset(body, client_ip, req.pilot.sessions))
        if mutation and path == '/api/login':
            token = req.pilot.login(body.get('username'), body.get('password'), client_ip)
            req.pilot.sessions.destroy(req.token())
            return req.respond(200, req.pilot.user(token), cookie=token)
        user = req.pilot.user(req.token())
        if path.startswith('/api/admin/'):
            if not req.pilot.admin:
                raise ApiError(403, 'Администрирование недоступно.')
            req.pilot.admin.require(user)
            if not mutation and path == '/api/admin/overview':
                return req.respond(200, req.pilot.admin.overview(user, req.pilot.assignments, req.pilot.modules))
            if mutation and path == '/api/admin/users':
                return req.respond(200, req.pilot.admin.update(user, body, req.pilot.modules))
            raise ApiError(404, 'Страница не найдена.')
        if not mutation and path.startswith('/documents/'):
            module_id = path.removeprefix('/documents/')
            req.pilot.teacher(user, module_id)
            m = req.pilot.module(module_id)
            docx = m.get('docx', '')
            if not docx or Path(docx).name != docx:
                raise ApiError(404, 'Документ не найден.')
            return req.respond(200, (ROOT / 'modules' / docx).read_bytes(),
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        if mutation and path == '/api/logout':
            req.pilot.sessions.destroy(req.token())
            return req.respond(200, {'ok': True}, cookie='')
        if not mutation and path == '/api/session':
            return req.respond(200, user)
        if not mutation and path == '/api/modules':
            return req.respond(200, [{'id': k, 'title': m['module_title'], 'year': m['pedagogical_year']}
                                     for k, m in req.pilot.modules.items()])
        if not mutation and path.startswith('/api/modules/'):
            return req.respond(200, req.pilot.module_view(user, path.removeprefix('/api/modules/')))
        if not mutation and path == '/api/queue':
            if user['role'] != 'teacher':
                raise ApiError(403, 'Очередь доступна преподавателю.')
            rows = [r for r in clinical(req.pilot.store.submissions()) if
                    r['module'] in req.pilot.assignments.get(user['id'], set())]
            for row in rows:
                row['student_name'] = req.pilot.users.get(row['student'], {}).get('name', row['student'])
            return req.respond(200, rows)
        practice = req.pilot.practice
        if not mutation and path == '/api/practice/queue':
            return req.respond(200, practice.queue(user))
        if not mutation and path.startswith('/api/practice/submissions/'):
            return req.respond(200, practice.submission(user, int(path.rsplit('/', 1)[1])))
        if not mutation and path.startswith('/api/practice/'):
            return req.respond(200, practice.view(user, path.removeprefix('/api/practice/')))
        routes = {'/api/practice/drafts': practice.draft, '/api/practice/answers': practice.answer,
                  '/api/practice/reviews': practice.review}
        if mutation and path in routes:
            return req.respond(200, routes[path](user, body))
        if not mutation and path == '/api/test-results':
            if user['role'] != 'teacher':
                raise ApiError(403, 'Результаты группы доступны преподавателю.')
            result = []
            for student in req.pilot.users:
                if req.pilot.users[student]['role'] == 'student':
                    for module_id in req.pilot.assignments.get(user['id'], set()):
                        result.extend(req.pilot.quiz.history(student, module_id))
            return req.respond(200, sorted(result, key=lambda r: r['created_at'], reverse=True))
        if not mutation and path.startswith('/api/quizzes/'):
            row = req.pilot.quiz.get(user['id'], path.rsplit('/', 1)[1])
            if row is None:
                raise ApiError(404, 'Попытка не найдена.')
            return req.respond(200, row)
        if mutation and path == '/api/resources/open':
            req.pilot.student(user)
            module_id, resource = body.get('module'), body.get('resource')
            if not isinstance(module_id, str) or not isinstance(resource, str):
                raise ApiError(400, 'Укажите материал.')
            materials = req.pilot.materials.view(req.pilot.module(module_id))
            if body.get('version') != materials['version']:
                raise ApiError(409, 'Список материалов изменился. Обновите страницу.')
            items = [r for g in materials['groups'] for r in g['items']] + materials['faculty_videos']
            found = next((r for r in items if r['id'] == resource and r['url']), None)
            if found is None:
                raise ApiError(404, 'Ссылка на материал не найдена.')
            req.pilot.reading.mark(user['id'], module_id, materials['version'], resource)
            return req.respond(200, {'saved': True, 'url': found['url']})
        if mutation and path == '/api/quizzes/start':
            req.pilot.student(user)
            module_id = body.get('module')
            if not isinstance(module_id, str):
                raise ApiError(400, 'Укажите модуль.')
            req.pilot.module(module_id)
            bank = [q for q in req.pilot.questions if q['module'] == module_id]
            return req.respond(200, req.pilot.quiz.start(user['id'], module_id, bank, body.get('key')))
        if mutation and path in ('/api/quizzes/save', '/api/quizzes/submit'):
            req.pilot.student(user)
            attempt_id = body.get('id')
            if not isinstance(attempt_id, str) or req.pilot.quiz.get(user['id'], attempt_id) is None:
                raise ApiError(404, 'Попытка не найдена.')
            method = req.pilot.quiz.submit if path.endswith('/submit') else req.pilot.quiz.save
            return req.respond(200, method(user['id'], attempt_id, body.get('answers')))
        if not mutation and path.startswith('/api/submissions/'):
            sid = int(path.rsplit('/', 1)[1])
            return req.respond(200, req.pilot.submission_view(user, sid))
        completion = req.pilot.completion
        if not mutation and path == '/api/completion/queue':
            return req.respond(200, completion.queue(user))
        if not mutation and path.startswith('/api/completion/students/'):
            rest = path.removeprefix('/api/completion/students/')
            student_id, module_id = rest.split('/', 1)
            return req.respond(200, completion.get_student(user, student_id, module_id))
        if not mutation and path == '/api/completion/lectures':
            return req.respond(200, completion.lecture_overview(user))
        if not mutation and path.startswith('/api/completion/lecture/'):
            return req.respond(200, completion.lecture_view(user, path.removeprefix('/api/completion/lecture/')))
        if not mutation and path.startswith('/api/completion/'):
            module_id = path.removeprefix('/api/completion/')
            if module_id in ('queue', 'students', 'lecture', 'lectures', 'submit', 'review'):
                raise ApiError(404, 'Страница не найдена.')
            return req.respond(200, completion.get_own(user, module_id))
        if mutation and path == '/api/completion/lecture':
            return req.respond(200, completion.lecture_bind(user, body))
        if mutation and path == '/api/completion/submit':
            return req.respond(200, completion.submit(user, body))
        if mutation and path == '/api/completion/review':
            return req.respond(200, completion.review(user, body))
        if mutation and path in ('/api/answers', '/api/drafts'):
            req.pilot.student(user)
            module, case, version = (body.get(k) for k in ('module', 'case', 'version'))
            if not all(isinstance(v, str) for v in (module, case, version)):
                raise ApiError(400, 'Укажите модуль, задачу и версию.')
            req.pilot.case(module, case, version)
            if path == '/api/drafts':
                req.pilot.store.save_draft(user['id'], module, case, version, body.get('text'))
                return req.respond(200, {'saved': True})
            row = req.pilot.store.submit(user['id'], module, case, version, body.get('answer'), body.get('key'))
            req.pilot.store.save_draft(user['id'], module, case, version, '')
            return req.respond(200, row)
        if mutation and path == '/api/reviews':
            sid = body.get('submission_id')
            if type(sid) is not int:
                raise ApiError(400, 'Неверный номер ответа.')
            row = req.pilot.submission_view(user, sid)
            req.pilot.teacher(user, row['module'])
            if row['version'] != req.pilot.versions[row['module']]:
                raise ApiError(409, 'Задание изменилось после отправки. Сначала нужна сверка исходной редакции.')
            return req.respond(200, req.pilot.store.review(user['id'], sid, body.get('decision'),
                                body.get('comment'), body.get('key')))
        raise ApiError(404, 'Страница не найдена.')
    except ApiError as error:
        req.respond(error.status, {'error': error.message})
    except (ValueError, TypeError) as error:
        req.respond(400, {'error': str(error) or 'Проверьте заполнение полей.'})
    except Exception:
        # No answer text, passwords, or SQL in browser/logs.
        req.respond(500, {'error': 'Не удалось подтвердить сохранение. Сохраните текст и повторите отправку.'})

    def log_message(self, fmt, *args):
        pass


def make_server(db_path, port=8789, data_path=ROOT / 'data/orp-data.json'):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.pilot = Pilot(db_path, data_path)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8789)
    parser.add_argument('--db', type=Path, default=Path(tempfile.gettempdir()) / 'onco-learning-pilot' / 'pilot.sqlite3')
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    server = make_server(args.db, args.port)
    print(f'LOCAL DEMO ONLY http://127.0.0.1:{server.server_port} — DB: {args.db}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

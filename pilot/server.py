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

ROOT = Path(__file__).resolve().parents[1]
USERS = {
    'student-a': {'name': 'Ординатор А', 'role': 'student', 'password': 'demo-student-a'},
    'student-b': {'name': 'Ординатор Б', 'role': 'student', 'password': 'demo-student-b'},
    'teacher': {'name': 'Преподаватель', 'role': 'teacher', 'password': 'demo-teacher'},
}


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Pilot:
    def __init__(self, db_path, data_path=ROOT / 'data/orp-data.json'):
        self.store = Store(str(db_path))
        data = json.loads(Path(data_path).read_text())
        self.quiz = QuizStore(str(db_path))
        self.reading = ReadingStore(db_path)
        self.materials = Materials(data, ROOT / 'docs/audit-2026-10-10/FACULTY_VIDEO_CATALOGUE.csv')
        self.questions = data.get('questions', [])
        self.modules = {m['module_id']: m for m in data['modules']}
        self.versions = {k: hashlib.sha256(json.dumps(m['clinical_cases'], ensure_ascii=False,
                        sort_keys=True).encode()).hexdigest()[:16] for k, m in self.modules.items()}
        # All demo modules are assigned to the demo teacher. This is NOT a real roster.
        self.assignments = {'teacher': set(self.modules)}
        self.sessions = {}
        self.lock = threading.Lock()

    def login(self, username, password):
        account = USERS.get(username) if isinstance(username, str) else None
        if not account or not isinstance(password, str) or not hmac.compare_digest(account['password'], password):
            raise ApiError(401, 'Неверный демонстрационный логин или пароль.')
        token = secrets.token_urlsafe(32)
        with self.lock:
            now = time.time()
            self.sessions = {k: v for k, v in self.sessions.items() if v[1] > now}
            self.sessions[token] = (username, now + 8 * 3600)
        return token

    def user(self, token):
        with self.lock:
            record = self.sessions.get(token)
        if not record or record[1] <= time.time():
            raise ApiError(401, 'Войдите в демонстрационную учётную запись.')
        username = record[0]
        return {'id': username, 'name': USERS[username]['name'], 'role': USERS[username]['role']}

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
        attempts = self.store.submissions(student=user['id'], module=module_id) if not teacher else []
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
                'drafts': self.store.drafts(user['id'], module_id, version) if not teacher else {},
                'materials': content, 'opened': self.reading.get(user['id'], module_id, content['version']),
                'question_count': len([q for q in self.questions if q['module'] == module_id]),
                'quizzes': self.quiz.history(user['id'], module_id) if not teacher else []}

    def submission_view(self, user, sid):
        row = self.store.get(sid)
        if row is None:
            raise ApiError(404, 'Ответ не найден.')
        if user['role'] == 'teacher':
            self.teacher(user, row['module'])
        elif row['student'] != user['id']:
            raise ApiError(404, 'Ответ не найден.')
        return row


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
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie is not None:
            self.send_header('Set-Cookie', f'{self.cookie_name}={cookie}; HttpOnly; SameSite=Strict; Path=/; Max-Age={28800 if cookie else 0}')
        self.end_headers()
        self.wfile.write(data)

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
        try:
            self.guard(mutation)
            path = urlsplit(self.path).path
            if not mutation:
                assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                          '/learning.js': ('learning.js', 'text/javascript; charset=utf-8'),
                          '/style.css': ('style.css', 'text/css; charset=utf-8')}
                if path in assets:
                    name, mime = assets[path]
                    return self.respond(200, (ROOT / 'pilot/web' / name).read_bytes(), mime)
            body = self.body() if mutation else {}
            if mutation and path == '/api/login':
                token = self.pilot.login(body.get('username'), body.get('password'))
                old = self.token()
                with self.pilot.lock:
                    self.pilot.sessions.pop(old, None)
                return self.respond(200, self.pilot.user(token), cookie=token)
            user = self.pilot.user(self.token())
            if not mutation and path.startswith('/documents/'):
                module_id = path.removeprefix('/documents/')
                self.pilot.teacher(user, module_id)
                m = self.pilot.module(module_id)
                docx = m.get('docx', '')
                if not docx or Path(docx).name != docx:
                    raise ApiError(404, 'Документ не найден.')
                return self.respond(200, (ROOT / 'modules' / docx).read_bytes(),
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            if mutation and path == '/api/logout':
                with self.pilot.lock:
                    self.pilot.sessions.pop(self.token(), None)
                return self.respond(200, {'ok': True}, cookie='')
            if not mutation and path == '/api/session':
                return self.respond(200, user)
            if not mutation and path == '/api/modules':
                return self.respond(200, [{'id': k, 'title': m['module_title'], 'year': m['pedagogical_year']}
                                         for k, m in self.pilot.modules.items()])
            if not mutation and path.startswith('/api/modules/'):
                return self.respond(200, self.pilot.module_view(user, path.removeprefix('/api/modules/')))
            if not mutation and path == '/api/queue':
                if user['role'] != 'teacher':
                    raise ApiError(403, 'Очередь доступна преподавателю.')
                rows = [r for r in self.pilot.store.submissions() if
                        r['module'] in self.pilot.assignments.get(user['id'], set())]
                return self.respond(200, rows)
            if not mutation and path == '/api/test-results':
                if user['role'] != 'teacher':
                    raise ApiError(403, 'Результаты группы доступны преподавателю.')
                result = []
                for student in USERS:
                    if USERS[student]['role'] == 'student':
                        for module_id in self.pilot.assignments.get(user['id'], set()):
                            result.extend(self.pilot.quiz.history(student, module_id))
                return self.respond(200, sorted(result, key=lambda r: r['created_at'], reverse=True))
            if not mutation and path.startswith('/api/quizzes/'):
                row = self.pilot.quiz.get(user['id'], path.rsplit('/', 1)[1])
                if row is None:
                    raise ApiError(404, 'Попытка не найдена.')
                return self.respond(200, row)
            if mutation and path == '/api/resources/open':
                self.pilot.student(user)
                module_id, resource = body.get('module'), body.get('resource')
                if not isinstance(module_id, str) or not isinstance(resource, str):
                    raise ApiError(400, 'Укажите материал.')
                materials = self.pilot.materials.view(self.pilot.module(module_id))
                if body.get('version') != materials['version']:
                    raise ApiError(409, 'Список материалов изменился. Обновите страницу.')
                items = [r for g in materials['groups'] for r in g['items']] + materials['faculty_videos']
                found = next((r for r in items if r['id'] == resource and r['url']), None)
                if found is None:
                    raise ApiError(404, 'Ссылка на материал не найдена.')
                self.pilot.reading.mark(user['id'], module_id, materials['version'], resource)
                return self.respond(200, {'saved': True, 'url': found['url']})
            if mutation and path == '/api/quizzes/start':
                self.pilot.student(user)
                module_id = body.get('module')
                if not isinstance(module_id, str):
                    raise ApiError(400, 'Укажите модуль.')
                self.pilot.module(module_id)
                bank = [q for q in self.pilot.questions if q['module'] == module_id]
                return self.respond(200, self.pilot.quiz.start(user['id'], module_id, bank, body.get('key')))
            if mutation and path in ('/api/quizzes/save', '/api/quizzes/submit'):
                self.pilot.student(user)
                attempt_id = body.get('id')
                if not isinstance(attempt_id, str) or self.pilot.quiz.get(user['id'], attempt_id) is None:
                    raise ApiError(404, 'Попытка не найдена.')
                method = self.pilot.quiz.submit if path.endswith('/submit') else self.pilot.quiz.save
                return self.respond(200, method(user['id'], attempt_id, body.get('answers')))
            if not mutation and path.startswith('/api/submissions/'):
                sid = int(path.rsplit('/', 1)[1])
                return self.respond(200, self.pilot.submission_view(user, sid))
            if mutation and path in ('/api/answers', '/api/drafts'):
                self.pilot.student(user)
                module, case, version = (body.get(k) for k in ('module', 'case', 'version'))
                if not all(isinstance(v, str) for v in (module, case, version)):
                    raise ApiError(400, 'Укажите модуль, задачу и версию.')
                self.pilot.case(module, case, version)
                if path == '/api/drafts':
                    self.pilot.store.save_draft(user['id'], module, case, version, body.get('text'))
                    return self.respond(200, {'saved': True})
                row = self.pilot.store.submit(user['id'], module, case, version, body.get('answer'), body.get('key'))
                self.pilot.store.save_draft(user['id'], module, case, version, '')
                return self.respond(200, row)
            if mutation and path == '/api/reviews':
                sid = body.get('submission_id')
                if type(sid) is not int:
                    raise ApiError(400, 'Неверный номер ответа.')
                row = self.pilot.submission_view(user, sid)
                self.pilot.teacher(user, row['module'])
                if row['version'] != self.pilot.versions[row['module']]:
                    raise ApiError(409, 'Задание изменилось после отправки. Сначала нужна сверка исходной редакции.')
                return self.respond(200, self.pilot.store.review(user['id'], sid, body.get('decision'),
                                    body.get('comment'), body.get('key')))
            raise ApiError(404, 'Страница не найдена.')
        except ApiError as error:
            self.respond(error.status, {'error': error.message})
        except (ValueError, TypeError) as error:
            self.respond(400, {'error': str(error) or 'Проверьте заполнение полей.'})
        except Exception:
            # No answer text, passwords, or SQL in browser/logs.
            self.respond(500, {'error': 'Не удалось подтвердить сохранение. Сохраните текст и повторите отправку.'})

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

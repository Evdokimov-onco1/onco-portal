"""Module completion contract v1 — local demo backend only."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from pilot.practice import ApiError
from pilot.quiz import PASS_THRESHOLD_PCT, _question, _version as quiz_bank_version

_KEY_MAX = 128
_COMMENT_MAX = 10000
_SCHEMA = """
CREATE TABLE IF NOT EXISTS completion_lecture_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL,
    materials_version TEXT NOT NULL,
    resource TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    teacher TEXT NOT NULL,
    request_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (teacher, request_key)
);
CREATE TABLE IF NOT EXISTS completion_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student TEXT NOT NULL,
    module TEXT NOT NULL,
    version TEXT NOT NULL,
    request_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (student, request_key)
);
CREATE TABLE IF NOT EXISTS completion_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES completion_requests(id),
    teacher TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('confirmed', 'returned')),
    comment TEXT NOT NULL,
    request_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (teacher, request_key)
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value, name, *, max_len=None, allow_empty=False):
    if not isinstance(value, str):
        raise ApiError(400, f'{name}: ожидается строка')
    trimmed = value.strip()
    if not allow_empty and not trimmed:
        raise ApiError(400, f'{name}: не должно быть пустым')
    if max_len is not None and len(trimmed) > max_len:
        raise ApiError(400, f'{name}: длиннее {max_len} символов')
    return trimmed


class Completion:
    def __init__(self, pilot, users):
        self.pilot = pilot
        self.users = users
        self._path = pilot.store._path
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()

    def _connect(self):
        conn = sqlite3.connect(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None
        conn.execute('PRAGMA foreign_keys = ON')
        return conn

    def _materials(self, module_id):
        return self.pilot.materials.view(self.pilot.module(module_id))

    def _quiz_bank(self, module_id):
        raw = [q for q in self.pilot.questions if q['module'] == module_id]
        return [_question(q) for q in raw] if raw else []

    def _clinical_ids(self, module_id):
        m = self.pilot.module(module_id)
        return [f'C{i + 1}' for i in range(len(m['clinical_cases']))]

    def _practice_required(self, module_id):
        return [a['id'] for a in self.pilot.practice.sources.get(module_id, [])
                if a['kind'] in ('seminar', 'tumor_board')]

    def _binding_row(self, conn, module_id, materials_version):
        return conn.execute(
            'SELECT * FROM completion_lecture_bindings WHERE module=? AND materials_version=?'
            ' ORDER BY id DESC LIMIT 1', (module_id, materials_version)).fetchone()

    def _binding_public(self, row):
        if row is None:
            return None
        return {'resource': row['resource'], 'title': row['title'], 'url': row['url'],
                'materials_version': row['materials_version'], 'teacher': row['teacher'],
                'created_at': row['created_at']}

    def _quiz_pass_evidence(self, student, module_id, bank_version):
        for row in self.pilot.quiz.history(student, module_id):
            if row['submitted_at'] and row['version'] == bank_version and row['score'] is not None:
                if row['score'] * 100 >= PASS_THRESHOLD_PCT * row['total']:
                    return {'attempt_id': row['id'], 'version': row['version'],
                            'score': row['score'], 'total': row['total']}
        return None

    def _version_payload(self, module_id, student):
        materials = self._materials(module_id)
        bank = self._quiz_bank(module_id)
        conn = self._connect()
        try:
            binding = self._binding_public(self._binding_row(conn, module_id, materials['version']))
        finally:
            conn.close()
        return {
            'clinical': self.pilot.versions[module_id],
            'practice': self.pilot.practice.versions[module_id],
            'materials': materials['version'],
            'quiz': quiz_bank_version(bank) if bank else '',
            'lecture': binding,
            'required': {
                activity: (self._latest_submission(student, module_id, activity, version) or {}).get('id')
                for activity, version in [
                    *((cid, self.pilot.versions[module_id]) for cid in self._clinical_ids(module_id)),
                    *((aid, self.pilot.practice.versions[module_id]) for aid in self._practice_required(module_id)),
                ]
            },
            'quiz_pass': self._quiz_pass_evidence(student, module_id,
                                                  quiz_bank_version(bank) if bank else ''),
        }

    def completion_version(self, module_id, student):
        payload = self._version_payload(module_id, student)
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _opened(self, student, module_id, materials_version):
        return self.pilot.reading.get(student, module_id, materials_version)

    def _latest_submission(self, student, module_id, case_id, version):
        for row in self.pilot.store.submissions(student=student, module=module_id):
            if row['case'] == case_id and row['version'] == version:
                return row
        return None

    def _clinical_review_ok(self, row):
        return row and row['reviews'] and row['reviews'][-1]['decision'] == 'accepted'

    def _practice_review_ok(self, row, kind):
        if not row:
            return False
        events = self.pilot.logbook.events([row['id']])[row['id']]
        if not events:
            return False
        last = events[-1]
        return last['decision'] == ('discussed' if kind == 'seminar' else 'accepted')

    def _student_checks(self, student, module_id):
        materials = self._materials(module_id)
        mv = materials['version']
        opened = self._opened(student, module_id, mv)
        conn = self._connect()
        try:
            binding = self._binding_public(self._binding_row(conn, module_id, mv))
        finally:
            conn.close()
        checks = []
        if binding:
            ok = binding['resource'] in opened
            reason = '' if ok else 'Откройте подтверждённую лекцию преподавателя.'
        else:
            ok = False
            reason = 'Преподаватель ещё не привязал лекцию модуля.'
        checks.append({'id': 'lecture', 'label': 'Лекция', 'ok': ok, 'done': int(ok), 'total': 1, 'reason': reason})
        sources = [r for g in materials['groups'] for r in g['items'] if r.get('kind') == 'source' and r.get('url')]
        src_done = sum(1 for r in sources if r['id'] in opened)
        checks.append({'id': 'source', 'label': 'Источники', 'ok': src_done > 0, 'done': min(src_done, 1), 'total': 1,
                       'reason': '' if src_done else 'Откройте хотя бы один обязательный источник.'})
        cv = self.pilot.versions[module_id]
        case_ids = self._clinical_ids(module_id)
        case_done = sum(1 for cid in case_ids if self._latest_submission(student, module_id, cid, cv))
        checks.append({'id': 'cases', 'label': 'Клинические задачи', 'ok': case_done == len(case_ids),
                       'done': case_done, 'total': len(case_ids),
                       'reason': '' if case_done == len(case_ids) else 'Отправьте ответы по всем задачам.'})
        pv = self.pilot.practice.versions[module_id]
        sem = [a for a in self.pilot.practice.sources.get(module_id, []) if a['kind'] == 'seminar']
        sem_done = sum(1 for a in sem if self._latest_submission(student, module_id, a['id'], pv))
        checks.append({'id': 'seminar', 'label': 'Семинар', 'ok': sem_done == len(sem), 'done': sem_done,
                       'total': len(sem), 'reason': '' if sem_done == len(sem) else 'Отправьте ответы на семинар.'})
        tb = [a for a in self.pilot.practice.sources.get(module_id, []) if a['kind'] == 'tumor_board']
        tb_done = sum(1 for a in tb if self._latest_submission(student, module_id, a['id'], pv))
        checks.append({'id': 'tumor_board', 'label': 'Разбор', 'ok': tb_done == len(tb), 'done': tb_done,
                       'total': len(tb), 'reason': '' if tb_done == len(tb) else 'Отправьте все этапы разбора.'})
        bank = self._quiz_bank(module_id)
        qv = quiz_bank_version(bank) if bank else ''
        evidence = self._quiz_pass_evidence(student, module_id, qv)
        checks.append({'id': 'quiz', 'label': 'Тест', 'ok': evidence is not None, 'done': 1 if evidence else 0,
                       'total': 1, 'reason': '' if evidence else f'Нужен зачёт не ниже {PASS_THRESHOLD_PCT}% по текущему банку.'})
        return checks, all(c['ok'] for c in checks)

    def _teacher_checks(self, student, module_id):
        cv, pv = self.pilot.versions[module_id], self.pilot.practice.versions[module_id]
        checks = []
        case_ids = self._clinical_ids(module_id)
        case_ok = all(self._clinical_review_ok(self._latest_submission(student, module_id, cid, cv))
                      for cid in case_ids)
        checks.append({'id': 'cases', 'label': 'Клинические задачи', 'ok': case_ok,
                       'done': sum(1 for cid in case_ids
                                   if self._clinical_review_ok(self._latest_submission(student, module_id, cid, cv))),
                       'total': len(case_ids),
                       'reason': '' if case_ok else 'Примите текущие ответы по клиническим задачам.'})
        sem = [a for a in self.pilot.practice.sources.get(module_id, []) if a['kind'] == 'seminar']
        sem_ok = all(self._practice_review_ok(self._latest_submission(student, module_id, a['id'], pv), 'seminar')
                     for a in sem)
        checks.append({'id': 'seminar', 'label': 'Семинар', 'ok': sem_ok,
                       'done': sum(1 for a in sem if self._practice_review_ok(
                           self._latest_submission(student, module_id, a['id'], pv), 'seminar')),
                       'total': len(sem),
                       'reason': '' if sem_ok else 'Отметьте обсуждение семинарских ответов.'})
        boards = {}
        for a in self.pilot.practice.sources.get(module_id, []):
            if a['kind'] == 'tumor_board' and a['stage_index'] == a['stage_total']:
                boards.setdefault(a['group_id'], a)
        tb_ok = all(self._practice_review_ok(
            self._latest_submission(student, module_id, a['id'], pv), 'tumor_board') for a in boards.values())
        checks.append({'id': 'tumor_board', 'label': 'Разбор', 'ok': tb_ok,
                       'done': sum(1 for a in boards.values() if self._practice_review_ok(
                           self._latest_submission(student, module_id, a['id'], pv), 'tumor_board')),
                       'total': len(boards),
                       'reason': '' if tb_ok else 'Примите финальные этапы разборов.'})
        return checks, all(c['ok'] for c in checks)

    def _request_rows(self, conn, student, module_id):
        rows = conn.execute(
            'SELECT * FROM completion_requests WHERE student=? AND module=? ORDER BY id DESC',
            (student, module_id)).fetchall()
        out = []
        for row in rows:
            events = conn.execute(
                'SELECT * FROM completion_events WHERE request_id=? ORDER BY id ASC', (row['id'],)).fetchall()
            out.append(self._request_public(row, events))
        return out

    def _request_public(self, row, events):
        return {'id': row['id'], 'student': row['student'], 'module': row['module'], 'version': row['version'],
                'key': row['request_key'], 'created_at': row['created_at'],
                'events': [self._event_public(e) for e in events]}

    @staticmethod
    def _event_public(row):
        return {'id': row['id'], 'request_id': row['request_id'], 'teacher': row['teacher'],
                'decision': row['decision'], 'comment': row['comment'], 'key': row['request_key'],
                'created_at': row['created_at']}

    def _status(self, student, module_id, version, history, student_ready, teacher_ready):
        current = next((r for r in history if r['version'] == version), None)
        if current and student_ready and teacher_ready and current['events'] and current['events'][-1]['decision'] == 'confirmed':
            return 'completed'
        if current and current['events'] and current['events'][-1]['decision'] == 'returned':
            return 'returned'
        if current:
            return 'submitted'
        return 'ready' if student_ready else 'blocked'

    def state(self, student, module_id):
        self.pilot.module(module_id)
        version = self.completion_version(module_id, student)
        checks, student_ready = self._student_checks(student, module_id)
        teacher_checks, teacher_ready = self._teacher_checks(student, module_id)
        conn = self._connect()
        try:
            binding = self._binding_public(self._binding_row(conn, module_id, self._materials(module_id)['version']))
            history = self._request_rows(conn, student, module_id)
        finally:
            conn.close()
        current = next((r for r in history if r['version'] == version), None)
        return {'module': module_id, 'student': student, 'version': version,
                'status': self._status(student, module_id, version, history, student_ready, teacher_ready),
                'student_ready': student_ready, 'teacher_ready': teacher_ready,
                'checks': checks, 'teacher_checks': teacher_checks,
                'lecture': binding, 'request': current, 'history': history}

    def _known_student(self, student_id):
        account = self.users.get(student_id)
        if not account or account['role'] != 'student':
            raise ApiError(404, 'Ординатор не найден.')

    def get_own(self, user, module_id):
        self.pilot.student(user)
        return self.state(user['id'], module_id)

    def get_student(self, user, student_id, module_id):
        self.pilot.teacher(user, module_id)
        self._known_student(student_id)
        return self.state(student_id, module_id)

    def queue(self, user):
        if user['role'] != 'teacher':
            raise ApiError(403, 'Очередь доступна назначенному преподавателю.')
        assigned = self.pilot.assignments.get(user['id'], set())
        conn = self._connect()
        try:
            rows = conn.execute('SELECT * FROM completion_requests ORDER BY id DESC').fetchall()
            out = []
            states = {}
            for row in rows:
                if row['module'] not in assigned:
                    continue
                identity = (row['student'], row['module'])
                if identity not in states:
                    states[identity] = self.state(*identity)
                state = states[identity]
                events = conn.execute(
                    'SELECT * FROM completion_events WHERE request_id=? ORDER BY id ASC', (row['id'],)).fetchall()
                item = self._request_public(row, events)
                item['stale'] = row['version'] != state['version']
                item['current_request'] = bool(state['request'] and state['request']['id'] == row['id'])
                item['effective_status'] = state['status']
                out.append(item)
            return out
        finally:
            conn.close()

    def lecture_view(self, user, module_id):
        self.pilot.teacher(user, module_id)
        materials = self._materials(module_id)
        candidates = [{'id': v['id'], 'title': v['title'], 'url': v['url']}
                      for v in materials['faculty_videos'] if v.get('url')]
        conn = self._connect()
        try:
            binding = self._binding_public(self._binding_row(conn, module_id, materials['version']))
        finally:
            conn.close()
        return {'module': module_id, 'materials_version': materials['version'],
                'current': binding, 'candidates': candidates}

    def lecture_bind(self, user, body):
        module_id = _text(body.get('module'), 'module')
        self.pilot.teacher(user, module_id)
        materials = self._materials(module_id)
        mv = _text(body.get('materials_version'), 'materials_version')
        if mv != materials['version']:
            raise ApiError(409, 'Версия материалов устарела. Обновите страницу.')
        resource = _text(body.get('resource'), 'resource')
        key = _text(body.get('key'), 'key', max_len=_KEY_MAX)
        found = next((c for c in materials['faculty_videos'] if c['id'] == resource and c.get('url')), None)
        if found is None:
            raise ApiError(400, 'Лекция не найдена среди допустимых кандидатов.')
        conn = self._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            try:
                cur = conn.execute(
                    'INSERT INTO completion_lecture_bindings'
                    ' (module,materials_version,resource,title,url,teacher,request_key,created_at)'
                    ' VALUES (?,?,?,?,?,?,?,?)',
                    (module_id, mv, resource, found['title'], found['url'], user['id'], key, _now()))
                conn.commit()
                row = conn.execute('SELECT * FROM completion_lecture_bindings WHERE id=?', (cur.lastrowid,)).fetchone()
                return self._binding_public(row)
            except sqlite3.IntegrityError:
                conn.rollback()
                row = conn.execute(
                    'SELECT * FROM completion_lecture_bindings WHERE teacher=? AND request_key=?',
                    (user['id'], key)).fetchone()
                if row is None:
                    raise ApiError(409, 'Конфликт ключа.')
                same = (row['module'] == module_id and row['materials_version'] == mv
                        and row['resource'] == resource)
                if not same:
                    raise ApiError(400, 'Ключ уже использован с другим содержимым.')
                return self._binding_public(row)
        finally:
            conn.close()

    def submit(self, user, body):
        self.pilot.student(user)
        module_id = _text(body.get('module'), 'module')
        self.pilot.module(module_id)
        key = _text(body.get('key'), 'key', max_len=_KEY_MAX)
        version = _text(body.get('version'), 'version')
        current = self.completion_version(module_id, user['id'])
        if version != current:
            raise ApiError(409, 'Версия завершения устарела. Обновите страницу.')
        _, student_ready = self._student_checks(user['id'], module_id)
        if not student_ready:
            raise ApiError(409, 'Заявка возможна только при выполнении всех требований ординатора.')
        conn = self._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            try:
                cur = conn.execute(
                    'INSERT INTO completion_requests (student,module,version,request_key,created_at) VALUES (?,?,?,?,?)',
                    (user['id'], module_id, version, key, _now()))
                conn.commit()
                row = conn.execute('SELECT * FROM completion_requests WHERE id=?', (cur.lastrowid,)).fetchone()
                return self._request_public(row, [])
            except sqlite3.IntegrityError:
                conn.rollback()
                row = conn.execute(
                    'SELECT * FROM completion_requests WHERE student=? AND request_key=?',
                    (user['id'], key)).fetchone()
                if row is None:
                    raise ApiError(409, 'Конфликт ключа.')
                same = row['module'] == module_id and row['version'] == version
                if not same:
                    raise ApiError(400, 'Ключ уже использован с другим содержимым.')
                events = conn.execute(
                    'SELECT * FROM completion_events WHERE request_id=? ORDER BY id ASC', (row['id'],)).fetchall()
                return self._request_public(row, events)
        finally:
            conn.close()

    def review(self, user, body):
        if user['role'] != 'teacher':
            raise ApiError(403, 'Подтверждение доступно назначенному преподавателю.')
        rid = body.get('request_id')
        if type(rid) is not int or isinstance(rid, bool):
            raise ApiError(400, 'Неверный номер заявки.')
        decision = body.get('decision')
        if decision not in ('confirmed', 'returned'):
            raise ApiError(400, "decision: допустимо 'confirmed' или 'returned'.")
        comment = body.get('comment')
        if not isinstance(comment, str):
            raise ApiError(400, 'comment: ожидается строка')
        comment = comment.strip()
        if len(comment) > _COMMENT_MAX:
            raise ApiError(400, f'comment: длиннее {_COMMENT_MAX} символов')
        if decision == 'returned' and not comment:
            raise ApiError(400, 'При возврате нужен комментарий.')
        key = _text(body.get('key'), 'key', max_len=_KEY_MAX)
        conn = self._connect()
        try:
            row = conn.execute('SELECT * FROM completion_requests WHERE id=?', (rid,)).fetchone()
            if row is None:
                raise ApiError(404, 'Заявка не найдена.')
            self.pilot.teacher(user, row['module'])
            current = self.completion_version(row['module'], row['student'])
            if row['version'] != current:
                raise ApiError(409, 'Заявка устарела относительно текущих материалов.')
            _, student_ready = self._student_checks(row['student'], row['module'])
            _, teacher_ready = self._teacher_checks(row['student'], row['module'])
            if decision == 'confirmed' and (not student_ready or not teacher_ready):
                raise ApiError(409, 'Подтверждение возможно только при готовности ординатора и преподавателя.')
            conn.execute('BEGIN IMMEDIATE')
            try:
                cur = conn.execute(
                    'INSERT INTO completion_events (request_id,teacher,decision,comment,request_key,created_at)'
                    ' VALUES (?,?,?,?,?,?)',
                    (rid, user['id'], decision, comment, key, _now()))
                conn.commit()
                ev = conn.execute('SELECT * FROM completion_events WHERE id=?', (cur.lastrowid,)).fetchone()
                return self._event_public(ev)
            except sqlite3.IntegrityError:
                conn.rollback()
                ev = conn.execute(
                    'SELECT * FROM completion_events WHERE teacher=? AND request_key=?',
                    (user['id'], key)).fetchone()
                if ev is None:
                    raise ApiError(409, 'Конфликт ключа.')
                same = ev['request_id'] == rid and ev['decision'] == decision and ev['comment'] == comment
                if not same:
                    raise ApiError(400, 'Ключ уже использован с другим содержимым.')
                return self._event_public(ev)
        finally:
            conn.close()

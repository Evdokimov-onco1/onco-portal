"""Append-only logbook of teacher decisions on practice submissions.

Lives in the same SQLite file as Store; the server authorises users and
passes the authoritative rubric snapshot. Teacher decisions are explicit:
no pass threshold is derived from scores.
"""
from contextlib import closing
from datetime import date, datetime, timezone
import json
import re
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS practice_reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL REFERENCES submissions(id),
    teacher       TEXT NOT NULL,
    decision      TEXT NOT NULL CHECK (decision IN ('accepted', 'returned', 'discussed')),
    comment       TEXT NOT NULL,
    request_key   TEXT NOT NULL,
    meeting_date  TEXT NOT NULL,
    marks         TEXT NOT NULL,
    rubric        TEXT NOT NULL,
    score         INTEGER NOT NULL,
    max_score     INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE (teacher, request_key)
);
"""
_KEY_MAX = 128
_COMMENT_MAX = 10000


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Logbook:
    def __init__(self, path):
        self.path = str(path)
        with closing(self._connect()) as db:
            db.executescript(_SCHEMA)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.isolation_level = None
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('PRAGMA busy_timeout = 30000')
        return db

    def add(self, teacher, submission_id, decision, comment, key, meeting_date, marks, rubric):
        if not isinstance(teacher, str) or not teacher.strip():
            raise ValueError('teacher: ожидается строка')
        if type(submission_id) is not int:
            raise ValueError('submission_id: ожидается целое число')
        if decision not in ('accepted', 'returned', 'discussed'):
            raise ValueError('decision: недопустимое решение')
        if not isinstance(key, str) or not key.strip() or len(key.strip()) > _KEY_MAX:
            raise ValueError(f'key: непустая строка до {_KEY_MAX} символов')
        if not isinstance(comment, str) or len(comment.strip()) > _COMMENT_MAX:
            raise ValueError(f'comment: строка до {_COMMENT_MAX} символов')
        key, comment = key.strip(), comment.strip()
        if decision == 'returned' and not comment:
            raise ValueError('При возврате на доработку нужен комментарий')
        if not isinstance(meeting_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', meeting_date):
            raise ValueError('meeting_date: ожидается дата ГГГГ-ММ-ДД')
        try:
            day = date.fromisoformat(meeting_date)
        except ValueError:
            raise ValueError('meeting_date: несуществующая дата')
        if day > date.today():
            raise ValueError('meeting_date: дата занятия не может быть в будущем')
        ids = [c['id'] for c in rubric]
        if not isinstance(marks, dict) or sorted(marks) != sorted(ids):
            raise ValueError('marks: нужны оценки ровно по всем критериям рубрики')
        for c in rubric:
            v = marks[c['id']]
            if type(v) is not int or not 0 <= v <= c['max_score']:
                raise ValueError(f'marks: критерий {c["id"]} оценивается от 0 до {c["max_score"]}')
        if decision == 'accepted' and any(c['critical'] and marks[c['id']] < c['max_score'] for c in rubric):
            raise ValueError('Критический критерий не выполнен: принять нельзя, используйте returned с комментарием')
        values = (submission_id, teacher, decision, comment, key, meeting_date, _dump(marks), _dump(rubric),
                  sum(marks.values()), sum(c['max_score'] for c in rubric))
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                old = db.execute('SELECT * FROM practice_reviews WHERE teacher = ? AND request_key = ?',
                                 (teacher, key)).fetchone()
                if old is not None:
                    db.rollback()
                    same = (old['submission_id'], old['teacher'], old['decision'], old['comment'],
                            old['request_key'], old['meeting_date'], old['marks'], old['rubric'],
                            old['score'], old['max_score']) == values
                    if not same:
                        raise ValueError('Ключ уже использован с другим содержимым проверки')
                    return self._event(old)
                if db.execute('SELECT 1 FROM submissions WHERE id = ?', (submission_id,)).fetchone() is None:
                    raise ValueError('Попытка с таким id не найдена')
                cur = db.execute('INSERT INTO practice_reviews (submission_id, teacher, decision, comment,'
                                 ' request_key, meeting_date, marks, rubric, score, max_score, created_at)'
                                 ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                 values + (datetime.now(timezone.utc).isoformat(),))
                db.commit()
            except BaseException:
                if db.in_transaction:
                    db.rollback()
                raise
            return self._event(db.execute('SELECT * FROM practice_reviews WHERE id = ?',
                                          (cur.lastrowid,)).fetchone())

    def events(self, submission_ids):
        """{submission_id: [Event oldest first]} for the given ids."""
        ids = list(dict.fromkeys(submission_ids))
        result = {i: [] for i in ids}
        with closing(self._connect()) as db:
            for n in range(0, len(ids), 500):
                chunk = ids[n:n + 500]
                rows = db.execute('SELECT * FROM practice_reviews WHERE submission_id IN (%s) ORDER BY id'
                                  % ','.join('?' * len(chunk)), chunk).fetchall()
                for row in rows:
                    result[row['submission_id']].append(self._event(row))
        return result

    @staticmethod
    def _event(row):
        return {'id': row['id'], 'teacher': row['teacher'], 'submission_id': row['submission_id'],
                'decision': row['decision'], 'comment': row['comment'], 'key': row['request_key'],
                'meeting_date': row['meeting_date'], 'marks': json.loads(row['marks']),
                'rubric': json.loads(row['rubric']), 'score': row['score'],
                'max_score': row['max_score'], 'created_at': row['created_at']}

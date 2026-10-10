"""Хранилище ответов и проверок для локального демо-портала.

Слой долговременности на SQLite. Хранилище НЕ выполняет авторизацию:
сервер проверяет личности студентов/преподавателей и назначения модулей
до вызова методов этого класса.

Гарантии:
- каждый метод открывает своё соединение (безопасно при потоках сервера);
- все запросы параметризованы, внешние ключи включены;
- записи append-only: отправленный ответ никогда не перезаписывается,
  проверки накапливаются для истории;
- идемпотентность по паре (student, key) для ответов и (teacher, key)
  для проверок: точный повтор возвращает ту же строку, конфликт — ValueError;
- метки времени — UTC в формате ISO 8601.

Файл БД не создаётся при импорте модуля; родительский каталог для БД
создаёт вызывающая сторона.
"""

import os
import sqlite3
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student     TEXT NOT NULL,
    module      TEXT NOT NULL,
    case_id     TEXT NOT NULL,          -- в словарях наружу уходит как "case"
    version     TEXT NOT NULL,
    answer      TEXT NOT NULL,
    request_key TEXT NOT NULL,          -- в словарях наружу уходит как "key"
    created_at  TEXT NOT NULL,
    UNIQUE (student, request_key)
);

CREATE TABLE IF NOT EXISTS reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL REFERENCES submissions(id),
    teacher       TEXT NOT NULL,
    decision      TEXT NOT NULL CHECK (decision IN ('accepted', 'returned')),
    comment       TEXT NOT NULL,
    request_key   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE (teacher, request_key)
);

CREATE TABLE IF NOT EXISTS drafts (
    student    TEXT NOT NULL,
    module     TEXT NOT NULL,
    case_id    TEXT NOT NULL,
    version    TEXT NOT NULL,
    draft_text TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (student, module, case_id, version)
);
"""

_ANSWER_MAX = 20000
_KEY_MAX = 128
_COMMENT_MAX = 10000
_DRAFT_MAX = 20000


def _now():
    """Текущее время UTC в ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def _text(value, name, *, max_len=None, allow_empty=False):
    """Проверка строкового поля. Нестроковые значения — ValueError."""
    if not isinstance(value, str):
        raise ValueError(f"{name}: ожидается строка")
    trimmed = value.strip()
    if not allow_empty and not trimmed:
        raise ValueError(f"{name}: не должно быть пустым")
    if max_len is not None and len(trimmed) > max_len:
        raise ValueError(f"{name}: длиннее {max_len} символов")
    return trimmed


class Store:
    """Долговременное хранилище попыток, проверок и черновиков."""

    def __init__(self, path):
        self._path = os.fspath(path)
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()

    def _connect(self):
        """Новое соединение: autocommit, явные транзакции, FK включены."""
        conn = sqlite3.connect(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None  # транзакции только через BEGIN/COMMIT
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------
    # Отправки
    # ------------------------------------------------------------------

    def submit(self, student, module, case, version, answer, key):
        """Новая попытка ответа. Повтор с тем же ключом — та же строка."""
        student = _text(student, "student")
        module = _text(module, "module")
        case = _text(case, "case")
        version = _text(version, "version")
        answer = _text(answer, "answer", max_len=_ANSWER_MAX)
        key = _text(key, "key", max_len=_KEY_MAX)

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute(
                    "INSERT INTO submissions"
                    " (student, module, case_id, version, answer, request_key, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (student, module, case, version, answer, key, _now()),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM submissions WHERE id = ?", (cur.lastrowid,)
                ).fetchone()
                return self._submission(conn, row)
            except sqlite3.IntegrityError:
                conn.rollback()
                row = conn.execute(
                    "SELECT * FROM submissions WHERE student = ? AND request_key = ?",
                    (student, key),
                ).fetchone()
                if row is None:
                    raise ValueError("Не удалось сохранить попытку")
                same = (
                    row["module"] == module
                    and row["case_id"] == case
                    and row["version"] == version
                    and row["answer"] == answer
                )
                if not same:
                    raise ValueError(
                        "Ключ уже использован с другим содержимым ответа"
                    )
                return self._submission(conn, row)
        finally:
            conn.close()

    def get(self, submission_id):
        """Попытка по id со списком проверок (старые первыми) или None."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM submissions WHERE id = ?", (submission_id,)
            ).fetchone()
            if row is None:
                return None
            return self._submission(conn, row)
        finally:
            conn.close()

    def submissions(self, student=None, module=None):
        """Список попыток, новые первыми; фильтры — точное равенство."""
        sql = "SELECT * FROM submissions"
        clauses, params = [], []
        if student is not None:
            clauses.append("student = ?")
            params.append(student)
        if module is not None:
            clauses.append("module = ?")
            params.append(module)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC"

        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [self._submission(conn, row) for row in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Проверки
    # ------------------------------------------------------------------

    def review(self, teacher, submission_id, decision, comment, key):
        """Проверка попытки преподавателем. История append-only."""
        teacher = _text(teacher, "teacher")
        key = _text(key, "key", max_len=_KEY_MAX)
        if not isinstance(submission_id, int) or isinstance(submission_id, bool):
            raise ValueError("submission_id: ожидается целое число")
        if decision not in ("accepted", "returned"):
            raise ValueError("decision: допустимо 'accepted' или 'returned'")
        if not isinstance(comment, str):
            raise ValueError("comment: ожидается строка")
        comment = comment.strip()
        if len(comment) > _COMMENT_MAX:
            raise ValueError(f"comment: длиннее {_COMMENT_MAX} символов")
        if decision == "returned" and not comment:
            raise ValueError("При возврате на доработку нужен комментарий")

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM submissions WHERE id = ?", (submission_id,)
            ).fetchone()
            if exists is None:
                conn.rollback()
                raise ValueError("Попытка с таким id не найдена")
            try:
                cur = conn.execute(
                    "INSERT INTO reviews"
                    " (submission_id, teacher, decision, comment, request_key, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (submission_id, teacher, decision, comment, key, _now()),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM reviews WHERE id = ?", (cur.lastrowid,)
                ).fetchone()
                return self._review(row)
            except sqlite3.IntegrityError:
                conn.rollback()
                row = conn.execute(
                    "SELECT * FROM reviews WHERE teacher = ? AND request_key = ?",
                    (teacher, key),
                ).fetchone()
                if row is None:
                    raise ValueError("Не удалось сохранить проверку")
                same = (
                    row["submission_id"] == submission_id
                    and row["decision"] == decision
                    and row["comment"] == comment
                )
                if not same:
                    raise ValueError(
                        "Ключ уже использован с другим содержимым проверки"
                    )
                return self._review(row)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Черновики
    # ------------------------------------------------------------------

    def save_draft(self, student, module, case, version, text):
        """Upsert черновика по (student, module, case, version)."""
        student = _text(student, "student")
        module = _text(module, "module")
        case = _text(case, "case")
        version = _text(version, "version")
        if not isinstance(text, str):
            raise ValueError("text: ожидается строка")
        if len(text) > _DRAFT_MAX:
            raise ValueError(f"text: длиннее {_DRAFT_MAX} символов")

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO drafts"
                " (student, module, case_id, version, draft_text, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (student, module, case_id, version)"
                " DO UPDATE SET draft_text = excluded.draft_text,"
                "               updated_at = excluded.updated_at",
                (student, module, case, version, text, _now()),
            )
            conn.commit()
        finally:
            conn.close()

    def drafts(self, student, module, version):
        """Черновики студента по модулю и версии: {case: text}."""
        student = _text(student, "student")
        module = _text(module, "module")
        version = _text(version, "version")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT case_id, draft_text FROM drafts"
                " WHERE student = ? AND module = ? AND version = ?",
                (student, module, version),
            ).fetchall()
            return {row["case_id"]: row["draft_text"] for row in rows}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Вспомогательное
    # ------------------------------------------------------------------

    def _submission(self, conn, row):
        """Строка submissions -> словарь API со списком проверок."""
        reviews = conn.execute(
            "SELECT * FROM reviews WHERE submission_id = ? ORDER BY id ASC",
            (row["id"],),
        ).fetchall()
        return {
            "id": row["id"],
            "student": row["student"],
            "module": row["module"],
            "case": row["case_id"],
            "version": row["version"],
            "answer": row["answer"],
            "key": row["request_key"],
            "created_at": row["created_at"],
            "reviews": [self._review(r) for r in reviews],
        }

    @staticmethod
    def _review(row):
        """Строка reviews -> словарь API."""
        return {
            "id": row["id"],
            "submission_id": row["submission_id"],
            "teacher": row["teacher"],
            "decision": row["decision"],
            "comment": row["comment"],
            "key": row["request_key"],
            "created_at": row["created_at"],
        }

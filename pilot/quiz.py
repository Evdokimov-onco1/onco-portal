"""Persistent quiz attempt store for the ONCO pilot (SQLite backend).

The store owns only the ``quiz_attempts`` table; unrelated tables that
may already exist in the same database file are left untouched. Every
public method opens a short-lived connection, uses parameterised SQL and
commits in a single transaction. No database file is created on import.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

PASS_THRESHOLD_PCT = 70
_META_FIELDS = ("explanation", "source_title", "source_url")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id           TEXT PRIMARY KEY,
    student      TEXT NOT NULL,
    module       TEXT NOT NULL,
    idem_key     TEXT NOT NULL,
    version      TEXT NOT NULL,
    snapshot     TEXT NOT NULL,
    answers      TEXT NOT NULL,
    score        INTEGER,
    total        INTEGER NOT NULL,
    passed       INTEGER,
    created_at   TEXT NOT NULL,
    submitted_at TEXT,
    UNIQUE (student, idem_key)
)
"""


def _utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _label(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError(f"{name} must be a non-empty string of <=128 chars")


def _letter(value, option_count):
    return (isinstance(value, str) and len(value) == 1
            and "A" <= value <= "Z"
            and ord(value) - ord("A") < option_count)


def _question(raw):
    if not isinstance(raw, dict):
        raise ValueError("each question must be an object")
    qid, stem = raw.get("id"), raw.get("stem")
    if not isinstance(qid, str) or not qid:
        raise ValueError("question id must be a non-empty string")
    if not isinstance(stem, str) or not stem:
        raise ValueError("question stem must be a non-empty string")
    options = raw.get("options")
    if (not isinstance(options, list) or not options
            or not all(isinstance(o, str) and o for o in options)):
        raise ValueError("question options must be a non-empty list of strings")
    if not _letter(raw.get("correct"), len(options)):
        raise ValueError("question correct must be a letter naming an option")
    q = {"id": qid, "stem": stem, "options": list(options),
         "correct": raw["correct"]}
    for field in _META_FIELDS:
        value = raw.get(field)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"question {field} must be a string")
            q[field] = value
    return q


def _version(questions):
    canonical = json.dumps(
        sorted(questions, key=lambda q: q["id"]),
        sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _answers(raw, snapshot, complete):
    if not isinstance(raw, dict):
        raise ValueError("answers must be an object")
    limits = {q["id"]: len(q["options"]) for q in snapshot}
    clean = {}
    for qid, letter in raw.items():
        if not isinstance(qid, str) or qid not in limits:
            raise ValueError("answer references an unknown question id")
        if not _letter(letter, limits[qid]):
            raise ValueError("answer must be an option letter")
        clean[qid] = letter
    if complete and len(clean) != len(limits):
        raise ValueError("every question must be answered exactly once")
    return clean


def _public(row):
    submitted = row["submitted_at"] is not None
    questions = []
    for q in json.loads(row["snapshot"]):
        item = {"id": q["id"], "stem": q["stem"], "options": q["options"]}
        if submitted:
            item["correct"] = q["correct"]
            item.update({f: q[f] for f in _META_FIELDS if f in q})
        questions.append(item)
    return {
        "id": row["id"],
        "student": row["student"],
        "module": row["module"],
        "version": row["version"],
        "created_at": row["created_at"],
        "submitted_at": row["submitted_at"],
        "questions": questions,
        "answers": json.loads(row["answers"]),
        "score": row["score"],
        "total": row["total"],
        "passed": None if row["passed"] is None else bool(row["passed"]),
    }


class QuizStore:
    """Quiz attempts persisted in a shared SQLite database file."""

    def __init__(self, path):
        self._path = str(path)

    def _connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute(_SCHEMA)
        return conn

    @contextmanager
    def _tx(self):
        conn = self._connect()
        try:
            # Lock before reading: a concurrent save must not overwrite final answers.
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _owned(self, conn, student, attempt_id):
        row = None
        if isinstance(attempt_id, str):
            row = conn.execute(
                "SELECT * FROM quiz_attempts WHERE id = ?",
                (attempt_id,)).fetchone()
        if row is None or row["student"] != student:
            raise ValueError("attempt not found")
        return row

    def start(self, student, module, questions, key):
        _label(student, "student")
        _label(module, "module")
        _label(key, "key")
        if not isinstance(questions, list) or not questions:
            raise ValueError("questions must be a non-empty list")
        snapshot = [_question(q) for q in questions]
        if len({q["id"] for q in snapshot}) != len(snapshot):
            raise ValueError("question ids must be unique")
        version = _version(snapshot)
        random.shuffle(snapshot)
        aid = str(uuid.uuid4())
        with self._tx() as conn:
            try:
                conn.execute(
                    "INSERT INTO quiz_attempts"
                    " (id, student, module, idem_key, version, snapshot,"
                    "  answers, total, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?)",
                    (aid, student, module, key, version,
                     json.dumps(snapshot, ensure_ascii=False),
                     len(snapshot), _utcnow()))
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT * FROM quiz_attempts"
                    " WHERE student = ? AND idem_key = ?",
                    (student, key)).fetchone()
                if (row is None or row["module"] != module
                        or row["version"] != version):
                    raise ValueError(
                        "key was already used with a different module or bank")
                return _public(row)
            return _public(conn.execute(
                "SELECT * FROM quiz_attempts WHERE id = ?",
                (aid,)).fetchone())

    def get(self, student, attempt_id):
        _label(student, "student")
        if not isinstance(attempt_id, str):
            return None
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM quiz_attempts WHERE id = ?",
                (attempt_id,)).fetchone()
            if row is None or row["student"] != student:
                return None
            return _public(row)

    def history(self, student, module):
        _label(student, "student")
        _label(module, "module")
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT * FROM quiz_attempts"
                " WHERE student = ? AND module = ?"
                " ORDER BY created_at DESC, rowid DESC",
                (student, module)).fetchall()
            return [_public(row) for row in rows]

    def save(self, student, attempt_id, answers):
        _label(student, "student")
        with self._tx() as conn:
            row = self._owned(conn, student, attempt_id)
            clean = _answers(answers, json.loads(row["snapshot"]),
                             complete=False)
            if row["submitted_at"] is not None:
                if clean == json.loads(row["answers"]):
                    return _public(row)
                raise ValueError("submitted attempt cannot be changed")
            conn.execute(
                "UPDATE quiz_attempts SET answers = ? WHERE id = ?",
                (json.dumps(clean), row["id"]))
            return _public(conn.execute(
                "SELECT * FROM quiz_attempts WHERE id = ?",
                (row["id"],)).fetchone())

    def submit(self, student, attempt_id, answers):
        _label(student, "student")
        with self._tx() as conn:
            row = self._owned(conn, student, attempt_id)
            snapshot = json.loads(row["snapshot"])
            clean = _answers(answers, snapshot, complete=True)
            if row["submitted_at"] is None:
                score = sum(clean[q["id"]] == q["correct"] for q in snapshot)
                passed = score * 100 >= PASS_THRESHOLD_PCT * len(snapshot)
                conn.execute(
                    "UPDATE quiz_attempts"
                    " SET answers = ?, score = ?, passed = ?, submitted_at = ?"
                    " WHERE id = ? AND submitted_at IS NULL",
                    (json.dumps(clean), score, int(passed),
                     _utcnow(), row["id"]))
            row = conn.execute(
                "SELECT * FROM quiz_attempts WHERE id = ?",
                (row["id"],)).fetchone()
            if clean != json.loads(row["answers"]):
                raise ValueError(
                    "attempt already submitted with different answers")
            return _public(row)

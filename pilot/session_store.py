"""Хранилища сессий пилота.

MemorySessions — локальный режим (как раньше: dict в памяти).
SqliteSessions — персистентные сессии в ОТДЕЛЬНОМ файле SQLite: общие для всех
процессов mod_wsgi; схема основной БД пилота не меняется (совместимость отката).
"""
import secrets
from contextlib import contextmanager
import sqlite3
import threading
import time

TTL = 8 * 3600


class MemorySessions:
    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()

    def create(self, username, ttl=TTL, auth_version=None):
        token = secrets.token_urlsafe(32)
        ver = auth_version if auth_version is not None else 1
        with self._lock:
            now = time.time()
            self._sessions = {k: v for k, v in self._sessions.items() if v[1] > now}
            self._sessions[token] = (username, now + ttl, ver)
        return token

    def create_with_version(self, username, auth_version, ttl=TTL):
        return self.create(username, ttl=ttl, auth_version=auth_version)

    def user(self, token):
        with self._lock:
            record = self._sessions.get(token)
        if not record or record[1] <= time.time():
            return None
        return record[0]

    def session_auth_version(self, token):
        with self._lock:
            record = self._sessions.get(token)
        if not record or record[1] <= time.time():
            return None
        return record[2] if len(record) > 2 else 1

    def destroy(self, token):
        with self._lock:
            self._sessions.pop(token, None)

    def destroy_all_for_user(self, username):
        with self._lock:
            self._sessions = {k: v for k, v in self._sessions.items() if v[0] != username}


class SqliteSessions:
    def __init__(self, path):
        self.path = str(path)
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('''CREATE TABLE IF NOT EXISTS sessions(
                token    TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                expires  REAL NOT NULL,
                auth_version INTEGER NOT NULL DEFAULT 1)''')
            cols = {r[1] for r in con.execute('PRAGMA table_info(sessions)')}
            if 'auth_version' not in cols:
                con.execute('ALTER TABLE sessions ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 1')
            con.execute('COMMIT')

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.execute('PRAGMA busy_timeout=10000')
        try:
            with con:
                yield con
        finally:
            con.close()

    def create(self, username, ttl=TTL, auth_version=1):
        token = secrets.token_urlsafe(32)
        with self._connect() as con:
            con.execute('DELETE FROM sessions WHERE expires<=?', (time.time(),))
            con.execute('INSERT INTO sessions(token,username,expires,auth_version) VALUES(?,?,?,?)',
                        (token, username, time.time() + ttl, auth_version))
        return token

    def create_with_version(self, username, auth_version, ttl=TTL):
        return self.create(username, ttl=ttl, auth_version=auth_version)

    def session_auth_version(self, token):
        if not token:
            return None
        with self._connect() as con:
            row = con.execute('SELECT auth_version,expires FROM sessions WHERE token=?',
                              (token,)).fetchone()
        if not row or row[1] <= time.time():
            return None
        return row[0]

    def destroy_all_for_user(self, username):
        with self._connect() as con:
            con.execute('DELETE FROM sessions WHERE username=?', (username,))

    def user(self, token):
        if not token:
            return None
        with self._connect() as con:
            row = con.execute('SELECT username,expires FROM sessions WHERE token=?',
                              (token,)).fetchone()
            if not row:
                return None
            if row[1] <= time.time():
                con.execute('DELETE FROM sessions WHERE token=?', (token,))
                return None
            return row[0]

    def destroy(self, token):
        with self._connect() as con:
            con.execute('DELETE FROM sessions WHERE token=?', (token,))

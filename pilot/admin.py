"""Administrative permissions are separate from teaching roles; no password export."""
import json
import time
from collections.abc import Mapping
from pilot.practice import ApiError


class AdminStore:
    def __init__(self, accounts):
        self.accounts = accounts
        with accounts._connect() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS admin_grants(user_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS admin_settings(
                    user_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1,
                    modules TEXT NOT NULL DEFAULT '[]');
                CREATE TABLE IF NOT EXISTS admin_audit(
                    id INTEGER PRIMARY KEY, actor TEXT NOT NULL, target TEXT NOT NULL,
                    action TEXT NOT NULL, details TEXT NOT NULL, created REAL NOT NULL);
            ''')

    def is_admin(self, uid):
        with self.accounts._connect() as con:
            return con.execute('SELECT 1 FROM admin_grants WHERE user_id=?', (uid,)).fetchone() is not None

    def enabled(self, uid):
        with self.accounts._connect() as con:
            row = con.execute('SELECT enabled FROM admin_settings WHERE user_id=?', (uid,)).fetchone()
        return row is None or bool(row[0])

    def modules(self, uid, fallback):
        with self.accounts._connect() as con:
            row = con.execute('SELECT modules FROM admin_settings WHERE user_id=?', (uid,)).fetchone()
        return set(json.loads(row[0])) if row else set(fallback)

    def require(self, user):
        if not self.is_admin(user['id']) or not self.enabled(user['id']):
            raise ApiError(403, 'Раздел доступен только администратору.')

    def grant_verified(self, email):
        """Server-side bootstrap only, never exposed as a public API."""
        uid = self.accounts.resolve_login(email)
        account = self.accounts.get_account(uid) if uid else None
        from pilot.auth import normalize_email
        if not account or account['email'] != normalize_email(email) or not account['email_verified'] or not self.enabled(uid):
            raise ValueError('Нужен существующий подтверждённый активный аккаунт.')
        with self.accounts._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('INSERT OR IGNORE INTO admin_grants(user_id) VALUES(?)', (uid,))
            con.execute('INSERT INTO admin_audit(actor,target,action,details,created) VALUES(?,?,?,?,?)',
                        ('server-bootstrap', uid, 'grant_admin', '{}', time.time()))
        return uid

    def overview(self, user, assignments, modules):
        self.require(user)
        with self.accounts._connect() as con:
            rows = con.execute('SELECT id,email,name,role,email_verified,auth_version FROM accounts ORDER BY name,id').fetchall()
            audit = [dict(r) for r in con.execute('SELECT id,actor,target,action,details,created FROM admin_audit ORDER BY id DESC LIMIT 100')]
        return {'users': [dict(r, enabled=self.enabled(r['id']), is_admin=self.is_admin(r['id']),
                               modules=sorted(assignments.get(r['id'], set()))) for r in rows],
                'modules': [{'id': k, 'title': m['module_title']} for k,m in modules.items()],
                'audit': audit}

    def update(self, user, body, modules):
        self.require(user)
        uid, role, enabled = body.get('id'), body.get('role'), body.get('enabled')
        chosen, version = body.get('modules'), body.get('version')
        if not isinstance(uid, str) or len(uid) > 254 or role not in ('student','teacher'):
            raise ApiError(400, 'Проверьте пользователя и роль.')
        if not isinstance(enabled, bool) or type(version) is not int:
            raise ApiError(400, 'Проверьте статус и версию пользователя.')
        if not isinstance(chosen, list) or len(chosen)>len(modules) or any(not isinstance(x,str) or x not in modules for x in chosen):
            raise ApiError(400, 'Выберите существующие модули.')
        if len(set(chosen)) != len(chosen) or (role=='student' and chosen):
            raise ApiError(400, 'Назначения модулей доступны преподавателям без повторов.')
        with self.accounts._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if not con.execute('SELECT 1 FROM admin_grants WHERE user_id=?',(user['id'],)).fetchone():
                raise ApiError(403, 'Права администратора изменились.')
            if uid == user['id'] or con.execute('SELECT 1 FROM admin_grants WHERE user_id=?',(uid,)).fetchone():
                raise ApiError(403, 'Изменение администраторов выполняется владельцем сервера.')
            row=con.execute('SELECT auth_version,email_verified FROM accounts WHERE id=?',(uid,)).fetchone()
            if not row:
                raise ApiError(404, 'Пользователь не найден.')
            if row['auth_version'] != version:
                raise ApiError(409, 'Пользователь изменился. Обновите список.')
            if role=='teacher' and not row['email_verified']:
                raise ApiError(400, 'Преподаватель должен подтвердить почту.')
            con.execute('UPDATE accounts SET role=?,auth_version=auth_version+1 WHERE id=?',(role,uid))
            con.execute('INSERT OR REPLACE INTO admin_settings(user_id,enabled,modules) VALUES(?,?,?)',
                        (uid,int(enabled),json.dumps(sorted(chosen))))
            con.execute('INSERT INTO admin_audit(actor,target,action,details,created) VALUES(?,?,?,?,?)',
                        (user['id'],uid,'update_access',json.dumps({'role':role,'enabled':enabled,'modules':sorted(chosen)}),time.time()))
        return {'ok': True}


class AssignmentView(Mapping):
    def __init__(self, admin, fallback):
        self.admin, self.fallback = admin, fallback

    def __getitem__(self, uid):
        return self.admin.modules(uid, self.fallback.get(uid, set()))

    def __iter__(self):
        return iter(self.admin.accounts.list_ids())

    def __len__(self):
        return len(self.admin.accounts.list_ids())

    def get(self, uid, default=None):
        return self.admin.modules(uid, self.fallback.get(uid, default or set()))

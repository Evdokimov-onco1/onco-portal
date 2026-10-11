#!/usr/bin/env python3
"""Идемпотентная установка staging-пакета на Timeweb.

Запуск на хосте (SSH/webconsole):  python3 install_staging.py staging-package.tar.gz
Трогает ТОЛЬКО потомков STAGING_ROOT. ДО любой записи проверяется:
корень realpath-точен, ВСЕ цели чтения/записи не симлинки и остаются
внутри корня, во всём дереве root нет ни одного симлинка (даже
внутреннего), существующие users.json/wsgi-config.json/rollback-manifest.json
валидны (fail closed — битые файлы = отказ, а не затирание).
"""
import json
import os
import secrets
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

from staging_common import (  # noqa: E402
    PKG, WEB, atomic_write, check_members, check_release_id, check_root,
    guard, refuse, restore_entry, scan_no_symlinks, snapshot_entry,
    validate_existing_private, verify_manifest, write_entry,
)

STAGING_ROOT = Path('/home/c/cl801264/onco-staging-20261011')
HOST = 'onco-staging.mmcc-education.ru'

PRIVATE_TARGETS = ('users.json', 'staging-credentials.json',
                   'wsgi-config.json', 'rollback-manifest.json',
                   'pilot.sqlite3', 'pilot-sessions.sqlite3', 'accounts.sqlite3')

TOOL_FILES = ('rollback_staging.py', 'staging_common.py', 'enable_auth.py')


def seed_users(private, app_dir):
    users_file = private / 'users.json'
    if users_file.exists():
        print('users.json уже есть — аккаунты не тронуты')
        return
    sys.path.insert(0, str(app_dir))
    from pilot.server import make_password_hash  # noqa: E402
    creds = {}
    users = {}
    for login, name, role in (('stage-student', 'Ординатор (staging)', 'student'),
                              ('stage-teacher', 'Преподаватель (staging)', 'teacher')):
        pwd = secrets.token_urlsafe(12)
        account = {'name': name, 'role': role,
                   'password_hash': make_password_hash(pwd)}
        if role == 'teacher':
            account['modules'] = 'all'
        users[login] = account
        creds[login] = {'password': pwd, 'role': role}
    atomic_write(users_file,
                 json.dumps(users, ensure_ascii=False, indent=2).encode())
    users_file.chmod(0o600)
    creds_file = private / 'staging-credentials.json'
    atomic_write(creds_file, json.dumps(
        {'host': HOST, 'accounts': creds,
         'note': 'Только синтетический staging; не выводить в логи.'},
        ensure_ascii=False, indent=2).encode())
    creds_file.chmod(0o600)
    print(f'Синтетические аккаунты созданы -> {creds_file} (600, пароль не печатается)')


def install(archive, root=None):
    root = check_root(root or STAGING_ROOT)
    archive = Path(archive).resolve()
    web = root / WEB
    private = root / 'private'
    releases = root / 'releases'
    backups = root / 'backups'

    scan_no_symlinks(root)
    for t in (web, private, releases, backups,
              *(root / name for name in TOOL_FILES),
              web / 'app.py', web / '.htaccess',
              *(private / name for name in PRIVATE_TARGETS)):
        guard(t, root)
    prev = validate_existing_private(private)

    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    release_id, n = f'release-{ts}', 1
    while (releases / release_id).exists() or \
            (backups / f'backup-{release_id}').exists():
        n += 1
        release_id = f'release-{ts}-{n}'
    check_release_id(release_id)
    backup_dir = backups / f'backup-{release_id}'

    releases.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=releases) as tmp:
        with tarfile.open(archive) as tar:
            check_members(tar)
            tar.extractall(tmp)
        src = Path(tmp) / PKG
        if not (src / 'MANIFEST.json').is_file():
            refuse('в архиве нет MANIFEST.json')
        verify_manifest(src)
        release = releases / release_id
        shutil.move(str(src), release)

    backup_web = backup_dir / WEB
    if web.is_dir():
        shutil.copytree(web, backup_web, symlinks=False)
    else:
        backup_web.mkdir(parents=True)
    print(f'Бэкап public_html -> {backup_web}')

    saved = snapshot_entry(web)
    try:
        private.mkdir(exist_ok=True)
        private.chmod(0o700)
        for name in ('pilot.sqlite3', 'pilot-sessions.sqlite3', 'users.json'):
            if (private / name).exists():
                print(f'{name} существует — не затираю')
        conf = private / 'wsgi-config.json'
        if not conf.exists():
            atomic_write(conf, (release / 'private' /
                                'wsgi-config.json').read_bytes())
            conf.chmod(0o600)
        seed_users(private, release / 'app')

        write_entry(release, private, web)
        for name in TOOL_FILES:
            tool = release / name
            if tool.is_file():
                atomic_write(root / name, tool.read_bytes())

        atomic_write(private / 'rollback-manifest.json', json.dumps({
            'release': release_id, 'previous_release': prev,
            'backup': str(backup_dir.relative_to(root)),
            'rollback': 'python3 rollback_staging.py — переключает вход на '
                        'previous_release; при его отсутствии восстанавливает '
                        'preinstall public_html из backup; private/ не трогает',
        }, ensure_ascii=False, indent=2).encode())
    except BaseException:
        restore_entry(web, saved)
        raise
    print(f'OK: {release_id}. Портал: https://{HOST}/ (после выпуска SSL). '
          f'Проверка: python3 smoke_staging.py')
    return release_id


def main():
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_file():
        sys.exit('Использование: python3 install_staging.py staging-package.tar.gz')
    install(sys.argv[1])


if __name__ == '__main__':
    main()

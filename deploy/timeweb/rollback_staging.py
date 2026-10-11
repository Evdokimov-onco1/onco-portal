#!/usr/bin/env python3
"""Откат staging-портала.

Запуск из корня staging:  python3 rollback_staging.py
При previous_release — переключение на предыдущий неизменяемый релиз.
При первой установке (previous_release=null) — точное восстановление
public_html из backup; private/ (БД, аккаунты) не трогает.
"""
import json
import shutil
import sys
from pathlib import Path

from staging_common import (
    WEB, atomic_write, check_root, check_release_id, guard, refuse,
    scan_no_symlinks, sync_public_html_from_backup, validate_rollback_manifest,
    verify_manifest, write_entry,
)

STAGING_ROOT = Path('/home/c/cl801264/onco-staging-20261011')


def rollback(root=None):
    root = check_root(root or STAGING_ROOT)
    scan_no_symlinks(root)
    private = guard(root / 'private', root)
    web = guard(root / WEB, root)
    releases = guard(root / 'releases', root)
    mfile = guard(private / 'rollback-manifest.json', root)
    if not mfile.is_file():
        refuse('нет private/rollback-manifest.json — нечего откатывать')
    try:
        m = json.loads(mfile.read_text())
    except (OSError, ValueError) as e:
        refuse(f'private/rollback-manifest.json не читается: {e}')

    release_id, prev, backup_path = validate_rollback_manifest(m, root)
    if release_id is None:
        refuse('активный релиз не задан — нечего откатывать')

    backup_web = guard(backup_path / WEB, root)
    guard(web / 'app.py', root)
    guard(web / '.htaccess', root)

    if prev is None:
        sync_public_html_from_backup(web, backup_web, root)
        atomic_write(mfile, json.dumps({
            'release': None,
            'previous_release': None,
            'backup': m['backup'],
            'rolled_back': True,
            'restored_preinstall': True,
            'rollback': 'первая установка отменена — public_html восстановлен из backup',
        }, ensure_ascii=False, indent=2).encode())
        print('OK: public_html восстановлен из preinstall backup; private/ не тронут')
        return None

    check_release_id(prev)
    release = guard(releases / prev, root)
    if not release.is_dir() or not (release / 'MANIFEST.json').is_file():
        refuse(f'релиз {prev} не найден или повреждён')
    verify_manifest(release)

    write_entry(release, private, web)
    htaccess_src = backup_web / '.htaccess'
    if htaccess_src.is_file():
        atomic_write(web / '.htaccess', htaccess_src.read_bytes())
        (web / '.htaccess').chmod(0o644)
    else:
        shutil.copy2(release / 'public' / '.htaccess', web / '.htaccess')

    atomic_write(mfile, json.dumps({
        'release': prev,
        'previous_release': release_id,
        'backup': m['backup'],
        'rolled_back': True,
        'rollback': 'python3 rollback_staging.py — вернёт релиз, '
                    'который был активен до этого отката',
    }, ensure_ascii=False, indent=2).encode())
    print(f'OK: вход переключён на {prev}; private/ не тронут')
    return prev


if __name__ == '__main__':
    rollback()

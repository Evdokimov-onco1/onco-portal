#!/usr/bin/env python3
"""Сборка staging-пакета для Timeweb из явного allowlist (см. PACKAGE.txt).

Запуск из корня портала:  python3 deploy/timeweb/build_staging.py
Результат: deploy/timeweb/dist/staging-package.tar.gz + MANIFEST.json внутри.
Ничего приватного (локальные БД, launcher, квитанции, логи, тесты, фикстуры,
аккаунты) в пакет не попадает — список фиксирован.
"""
import hashlib
import json
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'dist' / 'staging-package.tar.gz'
HOST = 'onco-staging.mmcc-education.ru'
PKG = 'staging-package'


def find_root():
    """Корень портала ищется по маркеру, а не по глубине __file__:
    parents[N] ломается при любом переносе каталога deploy."""
    for parent in HERE.parents:
        if (parent / 'pilot' / 'server.py').is_file() and \
                (parent / 'data' / 'orp-data.json').is_file():
            return parent
    sys.exit('Не найден корень портала (pilot/server.py + data/orp-data.json)')


ROOT = find_root()

# Явный allowlist: относительный путь в репо -> путь внутри пакета
APP_FILES = [
    'pilot/server.py', 'pilot/wsgi.py', 'pilot/session_store.py', 'pilot/store.py',
    'pilot/quiz.py', 'pilot/materials.py', 'pilot/logbook.py', 'pilot/practice.py',
    'pilot/completion.py', 'pilot/auth.py', 'pilot/mailer.py',
    'pilot/web/index.html', 'pilot/web/app.js', 'pilot/web/learning.js',
    'pilot/web/practice.js', 'pilot/web/completion.js', 'pilot/web/style.css',
    'data/orp-data.json', 'data/video-suggestions.json',
    'docs/audit-2026-10-10/FACULTY_VIDEO_CATALOGUE.csv',
]
APP_DIRS = ['modules']
PUBLIC_FILES = ['deploy/timeweb/app/app.py', 'deploy/timeweb/app/.htaccess']
TOOL_FILES = ['deploy/timeweb/enable_auth.py', 'deploy/timeweb/rollback_staging.py',
              'deploy/timeweb/staging_common.py']
FORBIDDEN = ('test_', '.sqlite', 'local_launcher', 'receipt', 'qa-logs',
             'make_users', 'task.txt', 'video-integration-input', 'fixture')


def sha256(path):
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def collect(root=ROOT):
    """Собирает содержимое пакета в память: {dest_in_tar: bytes}.

    dest всегда начинается с 'staging-package/' — установщик проверяет
    манифест относительно распакованного корня пакета."""
    missing = [f for f in APP_FILES + PUBLIC_FILES + TOOL_FILES
               if not (root / f).is_file()]
    for d in APP_DIRS:
        if not (root / d).is_dir():
            missing.append(d)
    if missing:
        sys.exit(f'Отсутствуют файлы allowlist: {missing}')
    staged = {}

    def add(src, dest):
        if src.is_symlink():
            sys.exit(f'симлинк в исходниках: {src}')
        data = src.read_bytes()
        for bad in FORBIDDEN:
            if bad in dest:
                sys.exit(f'Запрещённое имя в пакете: {dest}')
        staged[dest] = data

    for rel in APP_FILES:
        add(root / rel, f'{PKG}/app/' + rel)
    for rel in APP_DIRS:
        for f in sorted((root / rel).rglob('*')):
            if '__pycache__' in f.parts or f.suffix == '.pyc':
                continue
            if f.is_symlink():
                sys.exit(f'симлинк в исходниках: {f}')
            if f.is_file():
                add(f, f'{PKG}/app/' + str(f.relative_to(root)))
    for rel in PUBLIC_FILES:
        add(root / rel, f'{PKG}/public/' + Path(rel).name)
    for rel in TOOL_FILES:
        add(root / rel, f'{PKG}/' + Path(rel).name)
    staged[f'{PKG}/private/wsgi-config.json'] = json.dumps(
        {'host': HOST}, ensure_ascii=False, indent=2).encode() + b'\n'

    manifest = {dest: hashlib.sha256(data).hexdigest()
                for dest, data in staged.items()}
    staged[f'{PKG}/MANIFEST.json'] = (json.dumps(
        manifest, ensure_ascii=False, indent=2) + '\n').encode()
    return staged, manifest


def build_package(out=OUT, root=ROOT):
    """Пишет tar.gz пакета и возвращает манифест {dest: sha256}."""
    staged, manifest = collect(root)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for dest, data in staged.items():
            target = base / dest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        with tarfile.open(out, 'w:gz') as tar:
            tar.add(base / PKG, arcname=PKG)
    return manifest


def main():
    manifest = build_package()
    print(f'OK: {OUT} — {len(manifest)} файлов, '
          f'{OUT.stat().st_size // 1024} KB. Host: {HOST}')


if __name__ == '__main__':
    main()

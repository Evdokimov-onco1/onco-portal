#!/usr/bin/env python3
"""Офлайн-генератор users.json для hosted-режима пилота.

Запускается локально (не на хостинге) из корня репозитория-копии.
Пароли в файл не попадают — только pbkdf2-хэши. Для staging допустимы
синтетические аккаунты; реальный ростер формируется отдельно и не коммитится.

Пример:
  python3 deploy/timeweb/make_users.py ~/onco-pilot-private/users.json \
      --account ira:student:'Ира Синтетикова':Pass-ira-1 \
      --account prof:teacher:'Проф Синтетиков':Pass-prof-2:all
"""
import argparse
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pilot.server import make_password_hash  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path, help='куда записать users.json (вне public_html)')
    parser.add_argument('--account', action='append', required=True,
                        help='id:role:Имя[:password[:modules]] — password лучше '
                             'не передавать аргументом; если опущен, спросит getpass')
    args = parser.parse_args()
    users = {}
    for spec in args.account:
        parts = spec.split(':')
        if len(parts) < 3:
            sys.exit(f'неверная запись --account: {spec!r}')
        uid, role, name = parts[0], parts[1], parts[2]
        if role not in ('student', 'teacher'):
            sys.exit(f'роль должна быть student|teacher: {uid!r}')
        password = parts[3] if len(parts) > 3 and parts[3] else getpass.getpass(f'Пароль {uid}: ')
        modules = parts[4] if len(parts) > 4 else ('all' if role == 'teacher' else '')
        account = {'name': name, 'role': role,
                   'password_hash': make_password_hash(password)}
        if modules:
            account['modules'] = modules if modules == 'all' else modules.split(',')
        users[uid] = account
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(users, ensure_ascii=False, indent=2) + '\n')
    args.out.chmod(0o600)
    print(f'OK: {args.out} ({len(users)} аккаунтов, права 600). '
          'Пароли не сохранены — только pbkdf2-хэши.')


if __name__ == '__main__':
    main()

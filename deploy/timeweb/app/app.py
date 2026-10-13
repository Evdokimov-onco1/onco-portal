"""WSGI-точка входа портала для staging на Timeweb (mod_wsgi ExecCGI).

Перед загрузкой на хостинг заполнить два пути ниже. Код и приватные файлы
лежат ВНЕ public_html; в веб-каталоге остаются только этот файл и .htaccess.
Никаких учётных данных здесь нет — аккаунты и БД в приватном каталоге.
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

# Заполнить при деплое (рецензируемые значения, не секреты):
APP_ROOT = Path('/home/<USER>/onco-pilot')            # каталог с пакетом pilot/
PRIVATE_DIR = Path('/home/<USER>/onco-pilot-private')  # БД, сессии, users.json, backups/

CONFIG = json.loads((PRIVATE_DIR / 'wsgi-config.json').read_text(encoding='utf-8'))

sys.path.insert(0, str(APP_ROOT))
from pilot import wsgi  # noqa: E402

APP_ENV = {
    'PILOT_HOST': CONFIG['host'],
    'PILOT_DB': str(PRIVATE_DIR / 'pilot.sqlite3'),
    'PILOT_SESSION_DB': str(PRIVATE_DIR / 'pilot-sessions.sqlite3'),
    'PILOT_USERS_FILE': str(PRIVATE_DIR / 'users.json'),
    'PILOT_DATA': str(APP_ROOT / 'data' / 'orp-data.json'),
}
# Only server-side auth/mail settings are read from the private configuration.
for key in ('PILOT_SEQUENTIAL_MODULES', 'PILOT_AUTH_ENABLED', 'PILOT_AUTH_REGISTRATION', 'PILOT_MAIL_FROM',
            'PILOT_SENDMAIL_PATH', 'PILOT_SMTP_HOST', 'PILOT_SMTP_PORT',
            'PILOT_SMTP_USER', 'PILOT_SMTP_PASSWORD'):
    if key in CONFIG:
        APP_ENV[key] = CONFIG[key]
APP_ENV['PILOT_ACCOUNTS_DB'] = str(PRIVATE_DIR / 'accounts.sqlite3')
APP_ENV['PILOT_PUBLIC_URL'] = 'https://' + CONFIG['host']
application = wsgi.make_app(APP_ENV)

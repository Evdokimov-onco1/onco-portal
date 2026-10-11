"""Диагностический WSGI-вход для staging-проверки Timeweb.

Это НЕ приложение портала. Единственная задача — подтвердить, что на
shared-хостинге поднят mod_wsgi, и показать фактические версии интерпретатора
и SQLite (панель показывает Python 3.4, SSH — 3.10.12; что использует веб —
неизвестно до этой проверки). Никаких переменных окружения, путей и секретов
в ответ не выводится.
"""
import json
import sqlite3
import sys


def application(environ, start_response):
    body = json.dumps({
        'diagnostic': 'onco-pilot-wsgi-check',
        'wsgi': True,
        'python': sys.version.split()[0],
        'sqlite': sqlite3.sqlite_version,
    }, ensure_ascii=False).encode('utf-8')
    start_response('200 OK', [
        ('Content-Type', 'application/json; charset=utf-8'),
        ('Content-Length', str(len(body))),
        ('Cache-Control', 'no-store'),
    ])
    return [body]

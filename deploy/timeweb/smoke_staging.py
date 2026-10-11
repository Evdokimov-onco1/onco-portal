#!/usr/bin/env python3
"""Дымовая проверка staging-портала после установки (только этот хост).

Запуск: python3 smoke_staging.py
"""
import http.cookiejar
import json
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOST = 'onco-staging.mmcc-education.ru'
STAGING_ROOT = Path('/home/c/cl801264/onco-staging-20261011')
BASE = f'https://{HOST}'
CREDS = STAGING_ROOT / 'private' / 'staging-credentials.json'
TIMEOUT = 30

class _NoForeignRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Не следовать редиректам на другой хост."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.hostname and parsed.hostname.lower().rstrip('.') != HOST:
            raise urllib.error.HTTPError(
                newurl, code, f'cross-host redirect to {parsed.hostname}', headers, fp)
        return urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl)


jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(jar),
    _NoForeignRedirectHandler(),
)



def call(path, method='GET', body=None, with_auth=False):
    req = urllib.request.Request(BASE + path, method=method)
    if body is not None:
        payload = json.dumps(body).encode()
        req.data = payload
        req.add_header('Content-Type', 'application/json')
        if with_auth:
            req.add_header('Origin', BASE)
            req.add_header('X-Pilot-Request', '1')
    try:
        r = opener.open(req, timeout=TIMEOUT)
        return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')
    except (urllib.error.URLError, socket.timeout) as e:
        sys.exit(f'FAIL network/timeout: {e}')


def check(name, ok, detail=''):
    print(('PASS' if ok else 'FAIL'), name, detail)
    if not ok:
        sys.exit(1)


def main():
    assert urllib.parse.urlparse(BASE).scheme == 'https'
    st, _ = call('/')
    check('GET /', st == 200, str(st))
    st, body = call('/learning.js')
    check('learning.js marker', st == 200 and 'suggested-player' in body, str(st))

    creds = json.loads(CREDS.read_text())['accounts']['stage-student']
    st, _ = call('/api/login', 'POST',
                 {'username': 'stage-student', 'password': creds['password']},
                 with_auth=True)
    check('login', st == 200, str(st))
    st, body = call('/api/session')
    check('session', st == 200 and 'stage-student' in body, str(st))

    st, mod = call('/api/modules/M01')
    check('GET module', st == 200, str(st))
    view = json.loads(mod)
    version = view.get('version')
    check('module version', bool(version))
    case_id = view['cases'][0]['id']
    st, _ = call('/api/drafts', 'POST',
                 {'module': 'M01', 'case': case_id, 'version': version,
                  'text': 'smoke-draft'}, with_auth=True)
    check('draft save', st == 200, str(st))
    st, mod = call('/api/modules/M01')
    check('draft persisted',
          st == 200 and json.loads(mod).get('drafts', {}).get(case_id)
          == 'smoke-draft', str(st))

    st, _ = call('/api/logout', 'POST', {}, with_auth=True)
    check('logout', st == 200, str(st))
    st, _ = call('/api/session')
    check('session closed', st == 401, str(st))
    print('SMOKE OK — только staging, продакшн не затронут')


if __name__ == '__main__':
    main()

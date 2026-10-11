#!/usr/bin/env python3
"""Локальные регрессионные проверки staging-установщика (изолированные).

Запуск из корня портала:
    python3 -B deploy/timeweb/test_install_staging.py
"""
import io
import json
import os
import runpy
import stat
import sys
import tarfile
import tempfile
import unittest.mock as mock
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
PORTAL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PORTAL_ROOT))

import build_staging          # noqa: E402
import install_staging        # noqa: E402
import rollback_staging       # noqa: E402
from pilot.server import make_password_hash  # noqa: E402

PKG = build_staging.PKG


def make_root(tmp):
    root = Path(tmp) / 'root'
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def expect_refuse(fn, *args):
    try:
        fn(*args)
    except SystemExit:
        return
    raise AssertionError(f'ожидался отказ (SystemExit): {fn.__name__}')


def read_entry(root):
    return (root / 'public_html' / 'app.py').read_text()


def valid_users_blob():
    return json.dumps({
        'legacy': {
            'name': 'Legacy User',
            'role': 'student',
            'password_hash': make_password_hash('secret'),
        },
    })


def test_install_twice(pkg, tmp):
    root = make_root(tmp)
    r1 = install_staging.install(pkg, root)
    r2 = install_staging.install(pkg, root)
    assert r1 != r2 and r2.startswith('release-')
    assert (root / 'releases' / r1 / 'app' / 'pilot' / 'server.py').is_file()
    assert str(root / 'releases' / r2 / 'app') in read_entry(root)
    m = json.loads((root / 'private' / 'rollback-manifest.json').read_text())
    assert m['release'] == r2 and m['previous_release'] == r1


def test_same_second_release_ids(pkg, tmp):
    from datetime import datetime, timezone
    root = make_root(tmp)
    fixed = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    fake_dt = mock.MagicMock()
    fake_dt.now.return_value = fixed
    fake_dt.timezone = timezone
    fake_dt.datetime = datetime
    with mock.patch.object(install_staging, 'datetime', fake_dt):
        r1 = install_staging.install(pkg, root)
        r2 = install_staging.install(pkg, root)
    assert r1 == 'release-20260101T000000Z'
    assert r2 == 'release-20260101T000000Z-2'
    assert (root / 'backups' / f'backup-{r1}').is_dir()
    assert (root / 'backups' / f'backup-{r2}').is_dir()


def test_users_and_config(pkg, tmp):
    root = make_root(tmp)
    install_staging.install(pkg, root)
    private = root / 'private'
    users = json.loads((private / 'users.json').read_text())
    assert set(users) == {'stage-student', 'stage-teacher'}
    for uid, acc in users.items():
        assert acc['role'] in ('student', 'teacher') and acc['name']
        assert acc['password_hash'].startswith('pbkdf2$'), uid
    assert users['stage-teacher'].get('modules') == 'all'
    assert stat.S_IMODE((private / 'users.json').stat().st_mode) == 0o600
    creds = private / 'staging-credentials.json'
    assert stat.S_IMODE(creds.stat().st_mode) == 0o600
    conf = json.loads((private / 'wsgi-config.json').read_text())
    assert conf['host'] == install_staging.HOST


def test_existing_db_and_users_preserved(pkg, tmp):
    root = make_root(tmp)
    private = root / 'private'
    private.mkdir()
    sentinel_db = b'SYNTHETIC-DB'
    (private / 'pilot.sqlite3').write_bytes(sentinel_db)
    users_blob = valid_users_blob()
    (private / 'users.json').write_text(users_blob)
    install_staging.install(pkg, root)
    assert (private / 'pilot.sqlite3').read_bytes() == sentinel_db
    assert (private / 'users.json').read_text() == users_blob
    assert not (private / 'staging-credentials.json').exists()


def test_invalid_users_refused(pkg, tmp):
    root = make_root(tmp)
    private = root / 'private'
    private.mkdir()
    (private / 'users.json').write_text('{"u": {"x": 1}}')
    expect_refuse(install_staging.install, pkg, root)


def test_symlink_refusal(pkg, tmp):
    root = make_root(tmp)
    outside = Path(tmp) / 'outside'
    outside.mkdir()
    (root / 'public_html').symlink_to(outside)
    expect_refuse(install_staging.install, pkg, root)
    assert not list(outside.iterdir())

    real = make_root(Path(tmp) / 'sub-real')
    alias = Path(tmp) / 'alias-root'
    alias.symlink_to(real)
    expect_refuse(install_staging.install, pkg, alias)

    for bad in ('link', 'dots'):
        evil = Path(tmp) / f'evil-{bad}.tar.gz'
        with tarfile.open(evil, 'w:gz') as tar:
            if bad == 'link':
                m = tarfile.TarInfo(f'{PKG}/evil')
                m.type = tarfile.SYMTYPE
                m.linkname = '/etc/passwd'
                tar.addfile(m)
            else:
                m = tarfile.TarInfo(f'{PKG}/../evil')
                data = b'x'
                m.size = len(data)
                tar.addfile(m, io.BytesIO(data))
        expect_refuse(install_staging.install, evil, make_root(Path(tmp) / f'r-{bad}'))


def test_private_symlink_refused(pkg, tmp):
    root = make_root(tmp)
    private = root / 'private'
    private.mkdir()
    (private / 'trap').symlink_to('/tmp')
    expect_refuse(install_staging.install, pkg, root)


def test_manifest_extra_refused(pkg, tmp):
    root = make_root(tmp)
    evil = Path(tmp) / 'extra-member.tar.gz'
    with tarfile.open(pkg, 'r:gz') as src, tarfile.open(evil, 'w:gz') as dst:
        for m in src.getmembers():
            dst.addfile(m, src.extractfile(m))
        extra = tarfile.TarInfo(f'{PKG}/extra.txt')
        payload = b'evil'
        extra.size = len(payload)
        dst.addfile(extra, io.BytesIO(payload))
    expect_refuse(install_staging.install, evil, root)


def test_activation_failure_restores_entry(pkg, tmp):
    root = make_root(tmp)
    web = root / 'public_html'
    web.mkdir()
    (web / 'probe.txt').write_text('keep')

    def boom(*_a, **_k):
        raise RuntimeError('injected')

    with mock.patch.object(install_staging, 'write_entry', boom):
        try:
            install_staging.install(pkg, root)
        except RuntimeError:
            pass
        else:
            raise AssertionError('ожидался RuntimeError при write_entry')
    assert (web / 'probe.txt').read_text() == 'keep'
    assert not (web / 'app.py').exists()


def test_rollback(pkg, tmp):
    root = make_root(tmp)
    r1 = install_staging.install(pkg, root)
    r2 = install_staging.install(pkg, root)
    assert rollback_staging.rollback(root) == r1
    assert str(root / 'releases' / r1 / 'app') in read_entry(root)
    m = json.loads((root / 'private' / 'rollback-manifest.json').read_text())
    assert m['release'] == r1 and m['rolled_back'] is True
    assert rollback_staging.rollback(root) == r2
    assert str(root / 'releases' / r2 / 'app') in read_entry(root)


def test_install_after_rollback(pkg, tmp):
    root = make_root(tmp)
    r1 = install_staging.install(pkg, root)
    install_staging.install(pkg, root)
    rollback_staging.rollback(root)
    r3 = install_staging.install(pkg, root)
    m = json.loads((root / 'private' / 'rollback-manifest.json').read_text())
    assert m['previous_release'] == r1 and m['release'] == r3


def test_smoke_import(pkg, tmp):
    ns = runpy.run_path(str(Path(__file__).parent / 'smoke_staging.py'))
    assert callable(ns['main'])


def test_first_rollback_restores_preinstall(pkg, tmp):
    root = make_root(tmp)
    web = root / 'public_html'
    web.mkdir()
    (web / 'probe.txt').write_text('preinstall')
    install_staging.install(pkg, root)
    assert (web / 'app.py').is_file()
    rollback_staging.rollback(root)
    assert (web / 'probe.txt').read_text() == 'preinstall'
    assert not (web / 'app.py').exists()
    assert (root / 'private' / 'users.json').exists()


def test_entry_imports(pkg, tmp):
    root = make_root(tmp)
    install_staging.install(pkg, root)
    ns = runpy.run_path(str(root / 'public_html' / 'app.py'))
    assert callable(ns.get('application'))
    assert (root / 'private' / 'pilot.sqlite3').exists()


def test_persistent_sessions(pkg, tmp):
    root = make_root(tmp)
    install_staging.install(pkg, root)
    ns = runpy.run_path(str(root / 'public_html' / 'app.py'))
    app = ns['application']
    creds = json.loads((root / 'private' / 'staging-credentials.json').read_text())
    pwd = creds['accounts']['stage-student']['password']
    host = install_staging.HOST

    def run(method, path, body=None, cookie='', mutation=False):
        payload = json.dumps(body if body is not None else {})
        env = {
            'REQUEST_METHOD': method,
            'PATH_INFO': path,
            'wsgi.url_scheme': 'https',
            'HTTP_HOST': host,
            'HTTP_COOKIE': cookie,
            'wsgi.input': io.BytesIO(payload.encode()),
            'CONTENT_LENGTH': str(len(payload.encode())),
            'CONTENT_TYPE': 'application/json',
        }
        if mutation:
            env['HTTP_ORIGIN'] = f'https://{host}'
            env['HTTP_X_PILOT_REQUEST'] = '1'
        headers = []
        status_line = ['']

        def start(status, hdrs, exc_info=None):
            status_line[0] = status
            headers[:] = hdrs

        body_out = b''.join(app(env, start)).decode()
        set_cookie = next((h[1] for h in headers if h[0].lower() == 'set-cookie'), '')
        return int(status_line[0].split()[0]), body_out, set_cookie

    st, login_body, cookie = run(
        'POST', '/api/login',
        {'username': 'stage-student', 'password': pwd}, mutation=True)
    assert st == 200, login_body
    assert 'onco_pilot=' in cookie
    cookie_hdr = cookie.split(';')[0]
    _, session_body, _ = run('GET', '/api/session', cookie=cookie_hdr)
    assert 'stage-student' in session_body


def test_rollback_tools_at_root(pkg, tmp):
    root = make_root(tmp)
    install_staging.install(pkg, root)
    assert (root / 'rollback_staging.py').is_file()
    assert (root / 'staging_common.py').is_file()


def main():
    tests = (
        test_install_twice,
        test_same_second_release_ids,
        test_users_and_config,
        test_existing_db_and_users_preserved,
        test_invalid_users_refused,
        test_symlink_refusal,
        test_private_symlink_refused,
        test_manifest_extra_refused,
        test_activation_failure_restores_entry,
        test_rollback,
        test_install_after_rollback,
        test_smoke_import,
        test_first_rollback_restores_preinstall,
        test_entry_imports,
        test_persistent_sessions,
        test_rollback_tools_at_root,
    )
    with tempfile.TemporaryDirectory() as build_tmp:
        pkg = Path(build_tmp) / 'staging-package.tar.gz'
        build_staging.build_package(pkg)
        for t in tests:
            with tempfile.TemporaryDirectory() as tmp:
                t(pkg, tmp)
            print('PASS', t.__name__)
    print(f'ALL {len(tests)} TESTS OK — staging root/сеть/аккаунты не затронуты')


if __name__ == '__main__':
    main()

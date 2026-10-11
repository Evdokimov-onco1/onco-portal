#!/usr/bin/env python3
"""Enable auth only in the isolated ONCO Timeweb root; preserve all existing data."""
import json
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = Path('/home/c/cl801264/onco-staging-20261011')

def main():
    if Path.cwd().resolve() != ROOT or ROOT.is_symlink():
        raise SystemExit('Run only in the isolated ONCO staging root.')
    private = ROOT / 'private'
    if private.is_symlink() or not private.is_dir():
        raise SystemExit('Invalid private directory.')
    config_path = private / 'wsgi-config.json'
    entry = ROOT / 'public_html' / 'app.py'
    for p in (config_path, entry, private/'users.json', private/'pilot.sqlite3',
              private/'pilot-sessions.sqlite3', private/'accounts.sqlite3'):
        if p.is_symlink():
            raise SystemExit('Symlink refused.')
    config = json.loads(config_path.read_text())
    if config.get('host') != 'onco-staging.mmcc-education.ru':
        raise SystemExit('Unexpected host.')
    manifest = json.loads((private/'rollback-manifest.json').read_text())
    release_id = manifest['release']
    if Path(release_id).name != release_id:
        raise SystemExit('Invalid release.')
    app = ROOT / 'releases' / release_id / 'app'
    if app.resolve().parent.parent != (ROOT/'releases').resolve():
        raise SystemExit('Unexpected app path.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = ROOT/'backups'/('before-auth-'+stamp)
    backup.mkdir(mode=0o700)
    os.umask(0o077)
    for name in ('pilot.sqlite3','pilot-sessions.sqlite3','accounts.sqlite3'):
        src = private/name
        if src.exists():
            a = sqlite3.connect('file:'+str(src)+'?mode=ro',uri=True)
            b = sqlite3.connect(backup/name)
            try:
                a.backup(b)
                if b.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Backup integrity check failed.')
            finally:
                a.close(); b.close()
    (backup/'wsgi-config.json').write_bytes(config_path.read_bytes())
    (backup/'app.py').write_bytes(entry.read_bytes())
    sys.path.insert(0,str(app))
    from pilot.auth import AccountStore
    from pilot.wsgi import load_users
    store = AccountStore(private/'accounts.sqlite3')
    store.seed_once(load_users(private/'users.json'))
    (private/'accounts.sqlite3').chmod(0o600)
    config.update(PILOT_AUTH_ENABLED='1',PILOT_AUTH_REGISTRATION='1',
                  PILOT_SENDMAIL_PATH='/usr/sbin/sendmail',
                  PILOT_MAIL_FROM='cl801264@vh464.timeweb.ru')
    tmp = private/'wsgi-config.auth-next.json'
    tmp.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    tmp.chmod(0o600)
    os.replace(tmp,config_path)
    entry.touch()
    print('AUTH_ENABLED',release_id,'BACKUP',backup.name)
    print('Existing user IDs and progress preserved. Historical database was not accessed.')

if __name__ == '__main__':
    main()

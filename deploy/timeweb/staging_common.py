"""Общие примитивы install/rollback staging (копируются в корень хоста вместе с rollback)."""
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath

PKG = 'staging-package'
WEB = 'public_html'

_HASH_FORMAT = re.compile(
    r'^pbkdf2\$[1-9]\d*\$[0-9a-fA-F]{8,}\$[0-9a-fA-F]{32,}$')
_SHA256 = re.compile(r'[0-9a-f]{64}')
REQUIRED_REL = ('app/pilot/server.py', 'app/pilot/wsgi.py',
                'public/app.py', 'public/.htaccess',
                'private/wsgi-config.json')


def refuse(msg):
    sys.exit(f'ОТКАЗ: {msg}')


def check_root(root):
    root = Path(root)
    if not root.is_dir():
        refuse(f'нет каталога {root}')
    if Path(os.path.realpath(root)) != root:
        refuse(f'{root} содержит симлинки (realpath уходит в '
               f'{os.path.realpath(root)})')
    return root


def guard(path, root):
    p = Path(path)
    if p.is_symlink():
        refuse(f'симлинк: {p}')
    try:
        Path(os.path.realpath(p)).relative_to(root)
    except ValueError:
        refuse(f'{p} выходит за пределы {root}')
    return p


def scan_no_symlinks(root):
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                refuse(f'симлинк внутри {root}: {p}')


def check_release_id(name):
    if name is None:
        return None
    if not isinstance(name, str) or not name.startswith('release-') or \
            PurePosixPath(name).name != name:
        refuse(f'недопустимый id релиза: {name!r}')
    return name


def check_backup_name(name, release_id):
    """backup-<release_id> внутри backups/."""
    if not isinstance(name, str) or not name.startswith('backup-release-'):
        refuse(f'недопустимое имя бэкапа: {name!r}')
    if PurePosixPath(name).name != name:
        refuse(f'недопустимое имя бэкапа: {name!r}')
    if release_id and name != f'backup-{release_id}':
        refuse(f'бэкап {name!r} не соответствует релизу {release_id!r}')
    return name


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_members(tar):
    seen = set()
    for m in tar.getmembers():
        if m.name in seen:
            refuse(f'повтор имени в архиве: {m.name}')
        seen.add(m.name)
        name = PurePosixPath(m.name)
        if m.issym() or m.islnk():
            refuse(f'ссылка в архиве: {m.name}')
        if not (m.isfile() or m.isdir()):
            refuse(f'не файл/каталог в архиве: {m.name} (type={m.type!r})')
        if name.is_absolute() or '..' in name.parts:
            refuse(f'выход за корень архива: {m.name}')
        if not name.parts or name.parts[0] != PKG:
            refuse(f'путь вне {PKG}/: {m.name}')


def verify_manifest(pkg_dir, require_required=True):
    pkg_dir = Path(pkg_dir)
    try:
        manifest = json.loads((pkg_dir / 'MANIFEST.json').read_text())
    except (OSError, ValueError) as e:
        refuse(f'MANIFEST.json не читается: {e}')
    if not isinstance(manifest, dict) or not manifest:
        refuse('MANIFEST.json пуст или не является объектом')
    prefix = PKG + '/'
    listed = set()
    for key, want in manifest.items():
        if not isinstance(key, str) or not key.startswith(prefix):
            refuse(f'ключ вне {PKG}/: {key!r}')
        rel = key[len(prefix):]
        parts = PurePosixPath(rel).parts
        if not rel or rel == 'MANIFEST.json' or \
                PurePosixPath(rel).is_absolute() or '..' in parts:
            refuse(f'недопустимый путь в манифесте: {key!r}')
        if rel in listed:
            refuse(f'дубликат в манифесте: {key}')
        if not isinstance(want, str) or not _SHA256.fullmatch(want):
            refuse(f'не sha256-хэш у {key!r}')
        f = pkg_dir / rel
        if f.is_symlink() or not f.is_file() or sha256(f) != want:
            refuse(f'manifest не сошёлся: {key}')
        listed.add(rel)
    actual = set()
    for dirpath, dirnames, filenames in os.walk(pkg_dir):
        for name in dirnames + filenames:
            if (Path(dirpath) / name).is_symlink():
                refuse(f'симлинк в распакованном пакете: '
                       f'{Path(dirpath) / name}')
        for name in filenames:
            p = Path(dirpath) / name
            if p.is_file():
                actual.add(str(p.relative_to(pkg_dir)))
    actual.discard('MANIFEST.json')
    extra = sorted(actual - listed)
    if extra:
        refuse(f'файлы вне манифеста: {extra[:10]}')
    if require_required:
        missing = [rel for rel in REQUIRED_REL if rel not in listed]
        if missing:
            refuse(f'в пакете нет обязательных файлов: {missing}')
    return manifest


def atomic_write(path, data):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=f'.{path.name}.tmp-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def snapshot_entry(web):
    web = Path(web)
    return {name: ((web / name).read_bytes()
                   if (web / name).is_file() else None)
            for name in ('app.py', '.htaccess')}


def restore_entry(web, saved):
    web = Path(web)
    for name, data in saved.items():
        dst = web / name
        if data is None:
            if dst.is_symlink() or dst.exists():
                dst.unlink()
        else:
            atomic_write(dst, data)


def write_entry(release, private, web):
    tpl = (release / 'public' / 'app.py').read_text()
    mark_app = "/home/<USER>/onco-pilot'"
    mark_priv = "/home/<USER>/onco-pilot-private'"
    if mark_app not in tpl or mark_priv not in tpl:
        refuse('в шаблоне public/app.py нет ожидаемых placeholders')
    web = Path(web)
    web.mkdir(exist_ok=True)
    entry = (tpl
             .replace(mark_app, str(release / 'app') + "'")
             .replace(mark_priv, str(private) + "'"))
    atomic_write(web / 'app.py', entry.encode())
    (web / 'app.py').chmod(0o644)
    atomic_write(web / '.htaccess',
                 (release / 'public' / '.htaccess').read_bytes())
    (web / '.htaccess').chmod(0o644)


def sync_public_html_from_backup(web, backup_web, root):
    """Точное восстановление public_html из слепка (включая «app.py не было»)."""
    import shutil
    web = guard(web, root)
    backup_web = guard(backup_web, root)
    web.mkdir(exist_ok=True)
    for child in list(web.iterdir()):
        guard(child, root)
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    if backup_web.is_dir():
        for child in backup_web.iterdir():
            guard(child, root)
            dst = web / child.name
            if child.is_dir():
                shutil.copytree(child, dst, symlinks=False)
            else:
                shutil.copy2(child, dst)


def validate_rollback_manifest(m, root, strict_backup_pair=False):
    if not isinstance(m, dict):
        refuse('rollback-manifest.json не является объектом')
    release = m.get('release')
    if release is not None:
        check_release_id(release)
    prev = m.get('previous_release')
    if prev is not None:
        check_release_id(prev)
    backup = m.get('backup')
    if not isinstance(backup, str) or not backup:
        refuse('rollback-manifest.json без backup')
    backup_path = guard(root / backup, root)
    if backup_path.parent != root / 'backups':
        refuse('бэкап должен находиться непосредственно в backups/')
    if not backup_path.is_dir():
        refuse(f'каталог бэкапа отсутствует: {backup}')
    if not backup_path.name.startswith('backup-release-'):
        refuse(f'недопустимое имя бэкапа: {backup_path.name!r}')
    if strict_backup_pair and release is not None:
        check_backup_name(backup_path.name, release)
    return release, prev, backup_path


def validate_existing_private(private):
    users = private / 'users.json'
    if users.exists():
        try:
            data = json.loads(users.read_text())
        except (OSError, ValueError) as e:
            refuse(f'private/users.json не читается: {e}')
        if not (isinstance(data, dict) and data and all(
                isinstance(a, dict)
                and a.get('role') in ('student', 'teacher')
                and a.get('name')
                and _HASH_FORMAT.match(str(a.get('password_hash', '')))
                for a in data.values())):
            refuse('private/users.json не проходит схему аккаунтов')
    conf = private / 'wsgi-config.json'
    if conf.exists():
        try:
            cfg = json.loads(conf.read_text())
        except (OSError, ValueError) as e:
            refuse(f'private/wsgi-config.json не читается: {e}')
        if not isinstance(cfg, dict) or not str(cfg.get('host', '')).strip():
            refuse('private/wsgi-config.json без host')
    prev_active = None
    rm = private / 'rollback-manifest.json'
    if rm.exists():
        try:
            manifest = json.loads(rm.read_text())
        except (OSError, ValueError) as e:
            refuse(f'private/rollback-manifest.json не читается: {e}')
        validate_rollback_manifest(manifest, private.parent,
                                   strict_backup_pair=not manifest.get('rolled_back', False))
        prev_active = manifest.get('release')
        if prev_active is not None:
            check_release_id(prev_active)
    return prev_active

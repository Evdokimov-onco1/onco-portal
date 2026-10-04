#!/usr/bin/env python3
"""Verify the self-contained ONCO snapshot without modifying working files.

Run from any directory: python3 tools/verify_handoff.py
Only the build timestamp ('date') is ignored in the rebuild comparison.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    manifest = json.loads((ROOT / 'sources/manifest.sha256.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        path = (ROOT / item['path']).resolve()
        path.relative_to(ROOT)
        raw = path.read_bytes()
        require(len(raw) == item['bytes'], 'Размер изменился: ' + item['path'])
        require(hashlib.sha256(raw).hexdigest() == item['sha256'], 'SHA-256 изменился: ' + item['path'])
    print('Исходники: проверены %d контрольных сумм.' % len(manifest['files']), flush=True)

    with zipfile.ZipFile(ROOT / 'archive/stage6-v34/STAGE6_v34_FINALQA.zip') as archive:
        files = [i for i in archive.infolist() if not i.is_dir() and not i.filename.startswith('__MACOSX/')]
        require(len(files) == 72, 'Ожидалось 72 файла исходного архива')
        require(archive.testzip() is None, 'Повреждён исходный ZIP')
    require(len(list((ROOT / 'sources/stage6').glob('М-*.md'))) == 61, 'Ожидалось 61 Markdown-модуль')
    current = json.loads((ROOT / 'data/orp-data.json').read_text(encoding='utf-8'))
    require(len(current['modules']) == 61, 'Ожидался 61 модуль')
    require(len(current['questions']) == 633, 'Ожидалось 633 вопроса')
    require(len(current['calendar']) == 63, 'Ожидалось 63 занятия')
    for module in current['modules']:
        name = module.get('docx', '')
        require(bool(name) and (ROOT / 'modules' / name).is_file(), 'Нет Word-файла: ' + module['module_id'])
    name = current.get('calendar_docx', '')
    require(bool(name) and (ROOT / 'modules' / name).is_file(), 'Нет Word-календаря')

    subprocess.run([sys.executable, str(ROOT / 'tools/check_data.py')], check=True, cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix='onco-verify-') as directory:
        output = Path(directory) / 'rebuilt.json'
        subprocess.run([
            sys.executable, str(ROOT / 'tools/build_data.py'),
            '--stage6', str(ROOT / 'sources/stage6'), '--out', str(output)
        ], check=True, cwd=ROOT)
        rebuilt = json.loads(output.read_text(encoding='utf-8'))
        for data in (current, rebuilt):
            data.pop('date', None)
        differing = [key for key in sorted(set(current) | set(rebuilt)) if current.get(key) != rebuilt.get(key)]
        require(not differing, 'Сборка отличается по полям: ' + ', '.join(differing))
    print('OK: архив цел, файлы доступны, сборка совпадает с V4 во всех полях, кроме даты запуска.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print('FAIL: ' + str(exc), file=sys.stderr)
        sys.exit(1)

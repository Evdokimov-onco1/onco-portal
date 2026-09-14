#!/usr/bin/env python3
"""Проверка data/orp-data.json: форматы ID, висячие ссылки, покрытие модулей связями.

Запуск:  python3 tools/check_data.py [путь к json]
Выход 1, если найдены висячие ссылки или дубли ID.
"""
import collections, json, re, sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / 'data' / 'orp-data.json')
d = json.loads(path.read_text(encoding='utf-8'))

def norm(s):
    m = re.search(r'[МM]\s*-?\s*0*(\d+)', str(s or ''))
    return 'M%02d' % int(m.group(1)) if m else str(s or '').strip()

def parse_list(s):
    out = []
    for part in re.sub(r'\([^)]*\)', '', str(s or '')).split(','):
        part = part.strip()
        if not part:
            continue
        r = re.search(r'[МM]\s*-?\s*0*(\d+)\s*[–—-]\s*[МM]?\s*-?\s*0*(\d+)', part)
        if r:
            out += ['M%02d' % i for i in range(int(r.group(1)), int(r.group(2)) + 1)]
        elif re.search(r'[МM]\s*-?\s*\d', part):
            out.append(norm(part))
    return out

errors = []
mods = [norm(m['module_id']) for m in d['modules']]
dupes = [k for k, v in collections.Counter(mods).items() if v > 1]
if dupes:
    errors.append('дубли module_id: %s' % dupes)
modset = set(mods)
lib = d['library']
ids = {
    'tool': {t['id'] for t in lib['clinical_tools']},
    'sim': {s['id'] for s in lib['simulators']},
    'vp': {v['id'] for v in d['virtual_patients']},
    'osce': {s['id'] for s in d['osce']['stations']},
    'tb': {c['id'] for c in d['tumor_board']['cases']},
}
for m in d['modules']:
    mid = norm(m['module_id'])
    ct = m.get('clinical_tools') or {}
    tools = ct if isinstance(ct, list) else sum((ct.get(k, []) for k in ('mandatory', 'optional', 'journal')), [])
    for kind, refs in (('tool', tools), ('sim', m.get('external_simulators', [])), ('vp', m.get('virtual_patients', [])),
                       ('osce', m.get('osce_links', [])), ('tb', m.get('tumorboard_links', []))):
        for r in refs:
            if r not in ids[kind]:
                errors.append('%s: неизвестный %s %s' % (mid, kind, r))

qmods = collections.Counter(norm(q['module']) for q in d['questions'])
for q in d['questions']:
    if norm(q['module']) not in modset:
        errors.append('%s: вопрос ссылается на неизвестный модуль %s' % (q['id'], q['module']))
    if q.get('correct') not in list('ABCD')[:len(q.get('options', []))]:
        errors.append('%s: правильный ответ %r вне вариантов' % (q['id'], q.get('correct')))

rf_cov = collections.Counter(norm(x) for g in lib['rf_guidelines'] for x in g.get('module_ids', []))
book_cov = collections.Counter(x for b in lib['books_guides'] for x in parse_list(b.get('modules')))
for name, cov in (('rf_guidelines', rf_cov), ('books_guides', book_cov)):
    for k in cov:
        if k not in modset:
            errors.append('%s ссылается на неизвестный модуль %s' % (name, k))

def n_with(pred):
    return sum(1 for m in d['modules'] if pred(m))

print('версия данных: %s (%s)' % (d.get('version'), d.get('date')))
print('модули: %d (1-й год %d, 2-й год %d)' % (len(mods), sum(1 for m in d['modules'] if str(m['pedagogical_year']) == '1'), sum(1 for m in d['modules'] if str(m['pedagogical_year']) == '2')))
print('вопросы: %d, модулей без вопросов: %d' % (len(d['questions']), len([m for m in modset if not qmods[m]])))
print('библиотека: КР РФ %d, учебники %d, инструменты %d, симуляторы %d' % (len(lib['rf_guidelines']), len(lib['books_guides']), len(lib['clinical_tools']), len(lib['simulators'])))
print('VP %d, OSCE %d, TB %d' % (len(ids['vp']), len(ids['osce']), len(ids['tb'])))
print('покрытие модулей: КР РФ %d, учебники %d, инструменты %d, симуляторы %d, VP %d, OSCE %d, TB %d (из %d)' % (
    len([m for m in modset if rf_cov[m]]), len([m for m in modset if book_cov[m]]),
    n_with(lambda m: any((m.get('clinical_tools') or {}).get(k) for k in ('mandatory', 'optional', 'journal')) if isinstance(m.get('clinical_tools'), dict) else bool(m.get('clinical_tools'))),
    n_with(lambda m: m.get('external_simulators')), n_with(lambda m: m.get('virtual_patients')),
    n_with(lambda m: m.get('osce_links')), n_with(lambda m: m.get('tumorboard_links')), len(modset)))
declared = sum(1 for m in d['modules'] if int(m.get('test_questions') or 0) != qmods[norm(m['module_id'])])
print('модулей, где test_questions не совпадает с реальным числом вопросов: %d' % declared)
if errors:
    print('\nОШИБКИ (%d):' % len(errors))
    for e in errors[:50]:
        print(' -', e)
    sys.exit(1)
print('\nвисячих ссылок нет')

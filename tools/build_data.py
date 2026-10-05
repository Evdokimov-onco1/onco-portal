#!/usr/bin/env python3
"""Сборка data/orp-data.json из трёх источников:

  1. базовый JSON руководителя (V3, 31.08.2026): модули, библиотека, VP, OSCE, Tumor Board;
  2. публикационный комплект stage6 (v34, 10.09.2026): банк тестов, 61 DOCX-модуль, index.html с календарём;
  3. Markdown-версии DOCX из sources/stage6: блок А (что читать), Б2 (задачи), Б3 (вопросы, чек-лист).

Запуск из корня репозитория:
  python3 tools/build_data.py --stage6 sources/stage6 [--out data/orp-data.json]
"""
import argparse, collections, datetime, html, json, re, sys, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def norm(s):
    m = re.search(r'[МM]\s*-?\s*0*(\d+)', str(s or ''))
    return 'M%02d' % int(m.group(1)) if m else str(s or '').strip()

LINK = re.compile(r'\[([^\]]*)\]\((https?://[^)\s]+)\)')

def strip_md(s):
    s = LINK.sub(r'\1', s)
    s = re.sub(r'\*\*|\*|`', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def first_url(s):
    m = LINK.search(s)
    return m.group(2) if m else ''

def split_cells(line):
    line = line.strip()
    if line.startswith('|'): line = line[1:]
    if line.endswith('|'): line = line[:-1]
    return [c.strip() for c in line.split(' | ')] if ' | ' in line else [c.strip() for c in line.split('|')]

def parse_table(lines):
    """lines: строки таблицы markdown -> список словарей по заголовкам."""
    rows = [l for l in lines if l.strip().startswith('|')]
    if len(rows) < 2: return []
    heads = [strip_md(c) for c in split_cells(rows[0])]
    out = []
    for r in rows[2:]:
        cells = split_cells(r)
        if len(cells) < len(heads): cells += [''] * (len(heads) - len(cells))
        out.append(dict(zip(heads, cells)))
    return out

def row3(r):
    """Строка таблицы -> (заголовок, пояснение, url) независимо от названий колонок."""
    v = list(r.values())
    return (strip_md(v[0]) if v else '', strip_md(v[1]) if len(v) > 1 else '', first_url(' '.join(v)))

def parse_bullets(lines):
    out = []
    for l in lines:
        if not l.lstrip().startswith(('* ', '- ')): continue
        body = l.lstrip()[2:].strip()
        title = strip_md(LINK.search(body).group(1)) if LINK.search(body) else strip_md(body.split(' — ')[0])
        note = strip_md(body.split(' — ', 1)[1]) if ' — ' in body else ''
        out.append({'title': title, 'url': first_url(body), 'note': note})
    return out

def sections(md):
    """Разбить markdown на секции по заголовкам '## **А1. ...**', '### **...**', '# **Блок ...**'."""
    cur = None; groups = collections.OrderedDict(); sub = None
    for line in md.splitlines():
        m = re.match(r'^(#{1,3})\s+\*\*(.+?)\*\*\s*$', line.strip())
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            if level <= 2:
                cur = title; sub = None; groups.setdefault(cur, collections.OrderedDict())[''] = []
            else:
                sub = title
                if cur is None: cur = title; groups.setdefault(cur, collections.OrderedDict())
                groups[cur][sub] = []
            continue
        if cur is None: continue
        groups[cur][sub or ''].append(line)
    return groups

def find_section(groups, prefix):
    for k in groups:
        if k.startswith(prefix): return groups[k]
    return None

def parse_module_md(md):
    g = sections(md)
    out = {'reading': {}, 'clinical_cases': [], 'oral_discussion_questions': [], 'skills_checklist': []}
    R = out['reading']

    a1 = find_section(g, 'А1')
    if a1:
        R['guidelines'] = [dict(zip(('title', 'note', 'url'), row3(r))) for r in parse_table(a1['']) if row3(r)[0]]
    a2 = find_section(g, 'А2')
    if a2: R['reviews'] = parse_bullets(a2[''])
    a3 = find_section(g, 'А3')
    if a3:
        ks = []
        for sub, lines in a3.items():
            for r in parse_table(lines):
                t, note, url = row3(r)
                if t: ks.append({'group': strip_md(sub), 'title': t, 'note': note, 'url': url})
        R['key_studies'] = ks
    a4 = find_section(g, 'А4')
    if a4: R['lectures'] = parse_bullets(a4[''])
    # А6 — жирные абзацы внутри секции А5
    a5 = find_section(g, 'А5')
    if a5:
        upd = []; seen_a6 = False
        for l in a5['']:
            if l.startswith('**А6'): seen_a6 = True; continue
            if seen_a6 and l.startswith('**'):
                m = re.match(r'\*\*(.+?)\*\*\s*(.*)', l)
                if m: upd.append({'title': strip_md(m.group(1)).rstrip('.'), 'note': re.sub(r'\s*Открыть источник\.?$', '', strip_md(m.group(2))), 'url': first_url(l)})
        if upd: R['updates_2026'] = upd

    b2 = find_section(g, 'Б2')
    if b2:
        for sub, lines in b2.items():
            if not sub: continue
            case = {'title': strip_md(sub), 'vignette': '', 'questions': '', 'answer': '', 'sources': []}
            for l in lines:
                s = l.strip()
                if not s: continue
                if s.startswith('**Вопросы'): case['questions'] = strip_md(s)
                elif s.startswith('*Эталонный ответ'): case['answer'] = strip_md(s).replace('Эталонный ответ. ', '', 1)
                elif s.startswith('Источники:'): case['sources'] = [{'title': strip_md(t), 'url': u} for t, u in LINK.findall(s)]
                elif not case['questions'] and not case['answer']: case['vignette'] += (' ' if case['vignette'] else '') + strip_md(s)
            out['clinical_cases'].append(case)
    b3 = find_section(g, 'Б3')
    if b3:
        for sub, lines in b3.items():
            if sub.startswith('Вопросы'): out['oral_discussion_questions'] = [b['title'] if not b['note'] else b['title'] + ' — ' + b['note'] for b in parse_bullets(lines)]
            if sub.startswith('Чек-лист'): out['skills_checklist'] = [strip_md(r.get('Навык', '')) for r in parse_table(lines) if strip_md(r.get('Навык', ''))]
    return out

def parse_index(path):
    s = path.read_text(encoding='utf-8')
    rows = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', s, flags=re.S):
        cells = [html.unescape(re.sub(r'<[^>]+>', ' ', c)).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, flags=re.S)]
        link = re.findall(r'href="([^"]+\.docx)"', tr)
        if len(cells) >= 5 and link:
            rows.append({'n': int(re.sub(r'\D', '', cells[0]) or 0), 'date': cells[1], 'title': cells[2], 'lecturer': cells[3], 'section': cells[4],
                         'module': norm(urllib.parse.unquote(link[0]))})
    return rows

def parse_bank(path):
    s = path.read_text(encoding='utf-8')
    m = re.search(r'window\.__ONCO_BANK__=(\{.*?\});?\s*</script>', s, flags=re.S)
    return json.loads(m.group(1))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=str(ROOT / 'archive/supervisor-package-v4/ONCO_RESIDENCY_PORTAL_DATA_V3_INTERACTIVE.json'))
    ap.add_argument('--stage6', required=True)
    ap.add_argument('--modules-dir', default=str(ROOT / 'modules'))
    ap.add_argument('--out', default=str(ROOT / 'data/orp-data.json'))
    a = ap.parse_args()
    stage6 = Path(a.stage6); mdir = Path(a.modules_dir)

    D = json.loads(Path(a.base).read_text(encoding='utf-8'))
    bank = parse_bank(stage6 / 'Tilda_Банк_тестов_FINAL_v34.html')
    calendar = parse_index(stage6 / 'index.html')
    docx = {norm(p.name): p.name for p in mdir.glob('М-*.docx')}
    md_files = {norm(p.name): p for p in stage6.glob('М-*.md')}
    cal_docx = next(iter(p.name for p in mdir.glob('Календарный_план*.docx')), '')

    # --- модули: нормализованные ID + обогащение ---
    by_cal = collections.defaultdict(list)
    for r in calendar: by_cal[r['module']].append(r)
    stats = collections.Counter()
    for m in D['modules']:
        mid = norm(m['module_id']); m['module_id'] = mid
        m['pedagogical_year'] = str(m['pedagogical_year'])
        m['docx'] = docx.get(mid, '')
        m['calendar'] = [{'n': r['n'], 'date': r['date'], 'lecturer': r['lecturer'], 'section': r['section'], 'title': r['title']} for r in by_cal.get(mid, [])]
        m['lecturer'] = m['calendar'][0]['lecturer'] if m['calendar'] else ''
        m['section'] = m['calendar'][0]['section'] if m['calendar'] else ''
        if mid in md_files:
            parsed = parse_module_md(md_files[mid].read_text(encoding='utf-8'))
            m['reading'] = parsed['reading']
            if parsed['clinical_cases']: m['clinical_cases'] = parsed['clinical_cases']
            if parsed['oral_discussion_questions']: m['oral_discussion_questions'] = parsed['oral_discussion_questions']
            if parsed['skills_checklist']: m['skills_checklist'] = parsed['skills_checklist']
            for k, v in parsed['reading'].items(): stats['reading.' + k] += len(v)
            stats['cases'] += len(parsed['clinical_cases']); stats['checklist'] += len(parsed['skills_checklist'])
        else:
            m['reading'] = {}
            stats['md_missing'] += 1
    mod_by_id = {m['module_id']: m for m in D['modules']}

    # --- банк v34 -> questions ---
    qs = []; n = 0
    for mod in bank['m']:
        mid = norm(mod['c']); mm = mod_by_id.get(mid)
        for t in mod['q']:
            n += 1
            stem, options, correct, expl = t[0], t[1], t[2], t[3]
            src_t = t[4] if len(t) > 4 else ''; src_u = t[5] if len(t) > 5 else ''
            qs.append({'id': 'Q%04d' % n, 'module': mid, 'year': mm['pedagogical_year'] if mm else '',
                       'topic': mod.get('s', ''), 'stem': stem,
                       'options': [re.sub(r'^[A-DА-Г]\.\s*', '', o) for o in options],
                       'correct': correct, 'explanation': expl, 'source_title': src_t, 'source_url': src_u})
    D['questions'] = qs
    qcount = collections.Counter(q['module'] for q in qs)
    for m in D['modules']: m['test_questions'] = qcount[m['module_id']]

    # --- нормализация ID в библиотеке и в ссылках ---
    for g in D['library']['rf_guidelines']: g['module_ids'] = [norm(x) for x in g.get('module_ids', [])]

    # --- сводная категория библиотеки из А1 всех модулей ---
    agg = collections.OrderedDict()
    for m in D['modules']:
        for g in (m.get('reading') or {}).get('guidelines', []):
            key = (g['url'] or g['title']).lower()
            e = agg.setdefault(key, {'id': '', 'title': g['title'], 'url': g['url'], 'notes': g['note'], 'modules': []})
            e['modules'].append(m['module_id'])
    intl = []
    for i, e in enumerate(agg.values(), 1):
        e['id'] = 'GL-%03d' % i; e['modules'] = sorted(set(e['modules'])); intl.append(e)
    D['library']['module_guidelines'] = intl

    D['calendar'] = calendar
    D['calendar_docx'] = cal_docx
    D['version'] = 'ONCO_PORTAL_DATA_V4'
    D['date'] = datetime.date.today().isoformat()
    D['sources'] = {'modules_vp_osce_tb': 'ONCO_RESIDENCY_PORTAL_DATA_V3_INTERACTIVE (31.08.2026)',
                    'questions': 'Банк тестов v34 FINAL (stage6, 10.09.2026)',
                    'reading_cases_checklists': 'DOCX-модули stage6 (блоки А, Б2, Б3)',
                    'calendar': 'index.html stage6 (63 позиции)'}

    Path(a.out).write_text(json.dumps(D, ensure_ascii=False, indent=1), encoding='utf-8')
    print('модули %d, вопросы %d, календарь %d строк, docx %d, md %d' % (len(D['modules']), len(qs), len(calendar), len(docx), len(md_files)))
    print('извлечено из DOCX:', dict(stats))
    print('сводных рекомендаций из А1:', len(intl))
    print('записано', a.out, '%.1f МБ' % (Path(a.out).stat().st_size / 1e6))

if __name__ == '__main__':
    main()

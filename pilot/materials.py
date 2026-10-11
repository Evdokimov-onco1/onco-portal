"""Read canonical learning materials without changing clinical content."""
from contextlib import closing
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit


def http_url(value):
    if not isinstance(value, str):
        return ''
    parsed = urlsplit(value)
    return value if parsed.scheme in ('http', 'https') and parsed.netloc else ''


class Materials:
    def __init__(self, data, catalogue_path=None, suggestions_path=None):
        self.data = data
        self.videos = []
        if catalogue_path and Path(catalogue_path).exists():
            with Path(catalogue_path).open(encoding='utf-8-sig', newline='') as f:
                self.videos = list(csv.DictReader(f))
        self.suggestions = {'videos': {}, 'lectures': []}
        if suggestions_path and Path(suggestions_path).exists():
            self.set_suggestions(json.loads(Path(suggestions_path).read_text(encoding='utf-8')))

    def set_suggestions(self, raw):
        """Preview map 'onco-video-links/v1': additive lecture suggestions only."""
        videos, lectures = {}, []
        if isinstance(raw, dict) and raw.get('schema') == 'onco-video-links/v1':
            videos = {v['video_id']: v for v in raw.get('videos', [])
                      if isinstance(v, dict) and isinstance(v.get('video_id'), str)}
            lectures = [l for l in raw.get('lectures', [])
                        if isinstance(l, dict) and isinstance(l.get('lecture_id'), str)]
        self.suggestions = {'videos': videos, 'lectures': lectures}

    def _suggested_videos(self, module_id):
        """Provisional per-lecture suggestions for one module; never auto-approved."""
        out = []
        for lec in self.suggestions['lectures']:
            if module_id not in lec.get('modules', []):
                continue
            video = self.suggestions['videos'].get(lec.get('video_id'), {})
            out.append({
                'id': 'suggested-' + lec['lecture_id'],
                'lecture_id': lec['lecture_id'],
                'video_id': lec.get('video_id', ''),
                'title': lec.get('title', ''),
                'speaker': lec.get('speaker', ''),
                'note': lec.get('speaker', ''),
                'url': http_url(lec.get('youtube_start_url')) or http_url(lec.get('youtube_url')),
                'mp4_url': http_url(video.get('mp4_url')),
                'kind': 'suggested_video',
                'suggested': True,
                'boundary_status': 'provisional',
                'launch_offset_seconds': lec.get('launch_offset_seconds'),
                'estimated_start': lec.get('estimated_start'),
                'estimated_end': lec.get('estimated_end'),
                'truncation_risk': bool(lec.get('truncation_risk')),
                'truncation_warning': lec.get('truncation_warning'),
                'mapping_status': 'предложение по карте 2026-10-11; преподавателем не утверждено',
                'playback_status': 'границы предварительные; по звуку не проверено'})
        return out

    def view(self, m):
        module_id = m['module_id']
        groups = []
        names = {'guidelines': 'Рекомендации и обязательные источники',
                 'reviews': 'Обзоры и учебники', 'key_studies': 'Ключевые исследования',
                 'updates_2026': 'Обновления из исходного пакета',
                 'lectures': 'Видеоархивы и внешние учебные платформы'}
        for key, title in names.items():
            items = []
            for n, original in enumerate(m.get('reading', {}).get(key, [])):
                item = {k: original.get(k, '') for k in ('title', 'note', 'group')}
                item.update(id=f'{key}-{n+1}', url=http_url(original.get('url')),
                            kind='archive' if key == 'lectures' else 'source')
                items.append(item)
            groups.append({'id': key, 'title': title, 'items': items})
        candidates = []
        for row in self.videos:
            if module_id in row.get('candidate_modules', '').split(';'):
                candidates.append({'id': 'faculty-'+row['n'], 'title': row['title'],
                    'note': row['speaker_display'], 'url': http_url(row['url']),
                    'kind': 'candidate_video', 'mapping_status': row['mapping_status'],
                    'playback_status': row['playback_status']})
        tools = []
        selected = {i for values in m.get('clinical_tools', {}).values() for i in values}
        library = self.data.get('library', {})
        for t in library.get('clinical_tools', []):
            if t['id'] in selected:
                tools.append({**t, 'url': http_url(t.get('url'))})
        sims = [{**s, 'url': http_url(s.get('url'))} for s in library.get('simulators', [])
                if s['id'] in m.get('external_simulators', [])]
        osce = [{k: s.get(k, '') for k in ('id', 'title', 'task', 'materials', 'meta')}
                for s in self.data.get('osce', {}).get('stations', []) if s['id'] in m.get('osce_links', [])]
        # Stage content remains private until a written-stage workflow is connected.
        boards = [{'id': b['id'], 'title': b['title'], 'instruction': b.get('instruction', ''),
                   'stage_count': len(b.get('stages', [])), 'meta': b.get('meta', {})}
                  for b in self.data.get('tumor_board', {}).get('cases', [])
                  if b['id'] in m.get('tumorboard_links', [])]
        vps = [{'id': v['id'], 'title': v['title'], 'objectives': v.get('objectives', [])}
               for v in self.data.get('virtual_patients', []) if v['id'] in m.get('virtual_patients', [])]
        result = {'groups': groups, 'faculty_videos': candidates, 'lecture': m.get('lecture', ''),
                  'calendar': m.get('calendar', []), 'oral': m.get('oral_discussion_questions', []),
                  'seminar_basis': m.get('seminar_basis', ''), 'checklist': m.get('skills_checklist', []),
                  'osce': osce, 'tumor_board': boards, 'virtual_patients': vps, 'tools': tools,
                  'simulators': sims, 'docx': m.get('docx', '')}
        result['version'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        # Suggestions are appended after hashing: they must not change the
        # materials version or invalidate existing teacher bindings/opens.
        result['faculty_videos'] = candidates + self._suggested_videos(module_id)
        return result


class ReadingStore:
    def __init__(self, path):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS resource_opens (
                student TEXT, module TEXT, version TEXT, resource TEXT, opened_at TEXT,
                PRIMARY KEY(student,module,version,resource))''')

    def mark(self, student, module, version, resource):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT OR IGNORE INTO resource_opens VALUES (?,?,?,?,?)',
                       (student, module, version, resource, datetime.now(timezone.utc).isoformat()))

    def get(self, student, module, version):
        with closing(sqlite3.connect(self.path)) as db, db:
            return dict(db.execute('SELECT resource,opened_at FROM resource_opens WHERE student=? AND module=? AND version=?',
                                   (student, module, version)))

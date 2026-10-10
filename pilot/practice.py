"""Written seminar, OSCE and tumour-board practice on top of Store + Logbook.

Source texts are passed through unchanged. Hidden parts (examiner standard,
debrief, rubric, later tumour-board stages) leave the server only for the
assigned teacher or after the student's own submission in the current version.
This does not mark a module as complete.
"""
import copy
import hashlib
import json

PREFIX = 'P:'
KINDS = {'seminar': 'seminar', 'osce': 'osce', 'tb': 'tumor_board'}
DECISIONS = {'seminar': ('discussed', 'returned'), 'osce': ('accepted', 'returned'),
             'tumor_board': ('accepted', 'returned')}
SEMINAR_NOTE = 'Подготовьте ответ до семинара; преподаватель отметит обсуждение, дату занятия и комментарий.'


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def rubric(checklist):
    return [{'id': str(i + 1), 'label': c.get('Критерий', ''), 'max_score': int(c.get('Баллы', 0)),
             'critical': str(c.get('Критическая ошибка?', '')).strip().upper() == 'ДА'}
            for i, c in enumerate(checklist or [])]


def kind_of(activity_id):
    return KINDS.get(activity_id.split(':')[1] if activity_id.count(':') >= 2 else '', '')


def build(m, stations, boards):
    """Full (teacher-side) activity sources for one module, in display order."""
    items = []

    def add(**a):
        items.append({'group_id': '', 'stage_index': 1, 'stage_total': 1, 'instruction': '',
                      'standard': '', 'debrief': '', 'rubric': [], **a})
    for n, q in enumerate(m.get('oral_discussion_questions', [])):
        add(id=f'P:seminar:{n+1}', kind='seminar', title=f'Вопрос к семинару №{n+1}', prompts=[q],
            instruction=SEMINAR_NOTE)
    for sid in m.get('osce_links', []):
        s = stations.get(sid)
        if s:
            add(id=f'P:osce:{sid}', kind='osce', title=s.get('title', sid), prompts=[s.get('task', ''), s.get('materials', '')],
                standard=s.get('examiner_standard', ''), debrief=s.get('debrief', ''), rubric=rubric(s.get('checklist')))
    for bid in m.get('tumorboard_links', []):
        b = boards.get(bid)
        stages = b.get('stages', []) if b else []
        for i, st in enumerate(stages):
            final = i == len(stages) - 1
            content = st.get('content', [])
            add(id=f'P:tb:{bid}:{i+1}', kind='tumor_board', title=f'{b.get("title", bid)} — этап {i+1} из {len(stages)}',
                prompts=list(content) if isinstance(content, list) else [content],
                instruction=b.get('instruction', ''), group_id=bid, stage_index=i + 1, stage_total=len(stages),
                debrief=b.get('debrief', '') if final else '', rubric=rubric(b.get('checklist')) if final else [])
    return items


class Practice:
    def __init__(self, pilot, data):
        self.pilot = pilot
        stations = {s['id']: s for s in data.get('osce', {}).get('stations', [])}
        boards = {b['id']: b for b in data.get('tumor_board', {}).get('cases', [])}
        self.sources = {k: build(m, stations, boards) for k, m in pilot.modules.items()}
        self.versions = {k: hashlib.sha256(json.dumps(v, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
                         for k, v in self.sources.items()}

    # -- helpers -------------------------------------------------------
    def source(self, module_id, activity_id):
        return next((a for a in self.sources.get(module_id, []) if a['id'] == activity_id), None)

    def rows(self, **filters):
        rows = [r for r in self.pilot.store.submissions(**filters) if r['case'].startswith(PREFIX)]
        events = self.pilot.logbook.events([r['id'] for r in rows])
        return [{**r, 'logbook': events[r['id']]} for r in rows]

    def current(self, module_id, student):
        """Own current-version rows grouped by activity, newest first."""
        version, grouped = self.versions[module_id], {}
        if student:
            for r in self.rows(student=student, module=module_id):
                if r['version'] == version:
                    grouped.setdefault(r['case'], []).append(r)
        return grouped

    @staticmethod
    def locked(a, done):
        return a['kind'] == 'tumor_board' and any(
            f'P:tb:{a["group_id"]}:{j}' not in done for j in range(1, a['stage_index']))

    def activities(self, module_id, student, full):
        done = self.current(module_id, student)
        result = []
        for a in self.sources[module_id]:
            locked = not full and self.locked(a, done)
            view = {k: a[k] for k in ('id', 'kind', 'title', 'group_id', 'stage_index', 'stage_total')}
            view.update(locked=locked, prompts=[], instruction='', standard='', debrief='', rubric=[],
                        attempts=done.get(a['id'], []))
            if not locked:
                view.update(prompts=list(a['prompts']), instruction=a['instruction'])
                if full or a['id'] in done:
                    view.update(standard=a['standard'], debrief=a['debrief'], rubric=copy.deepcopy(a['rubric']))
            result.append(view)
        return result

    def editable(self, user, body):
        self.pilot.student(user)
        module_id, activity_id, version = (body.get(k) for k in ('module', 'activity', 'version'))
        if not all(isinstance(v, str) for v in (module_id, activity_id, version)):
            raise ApiError(400, 'Укажите модуль, задание и версию.')
        self.pilot.module(module_id)
        if version != self.versions[module_id]:
            raise ApiError(409, 'Материал изменился. Скопируйте черновик и обновите страницу.')
        a = self.source(module_id, activity_id)
        if a is None:
            raise ApiError(404, 'Задание не найдено.')
        if self.locked(a, self.current(module_id, user['id'])):
            raise ApiError(409, 'Этап откроется после отправки ответов на предыдущие этапы.')
        return module_id, activity_id, version

    # -- endpoints -----------------------------------------------------
    def view(self, user, module_id):
        self.pilot.module(module_id)
        teacher = user['role'] == 'teacher'
        if teacher:
            self.pilot.teacher(user, module_id)
        version = self.versions[module_id]
        drafts = {} if teacher else {k: v for k, v in self.pilot.store.drafts(user['id'], module_id, version).items()
                                     if k.startswith(PREFIX)}
        return {'module': module_id, 'version': version, 'drafts': drafts,
                'activities': self.activities(module_id, None if teacher else user['id'], teacher)}

    def draft(self, user, body):
        module_id, activity_id, version = self.editable(user, body)
        self.pilot.store.save_draft(user['id'], module_id, activity_id, version, body.get('text'))
        return {'saved': True}

    def answer(self, user, body):
        module_id, activity_id, version = self.editable(user, body)
        row = self.pilot.store.submit(user['id'], module_id, activity_id, version, body.get('answer'), body.get('key'))
        self.pilot.store.save_draft(user['id'], module_id, activity_id, version, '')
        return {**row, 'logbook': self.pilot.logbook.events([row['id']])[row['id']]}

    def queue(self, user):
        if user['role'] != 'teacher':
            raise ApiError(403, 'Очередь доступна преподавателю.')
        assigned = self.pilot.assignments.get(user['id'], set())
        result = []
        for r in self.rows():
            if r['module'] in assigned:
                a = self.source(r['module'], r['case'])
                result.append({**r, 'title': a['title'] if a else r['case'], 'kind': kind_of(r['case']),
                               'stale': r['version'] != self.versions.get(r['module'])})
        return result

    def get(self, user, sid):
        row = self.pilot.store.get(sid)
        if row is None or not row['case'].startswith(PREFIX):
            raise ApiError(404, 'Ответ не найден.')
        if user['role'] == 'teacher':
            self.pilot.teacher(user, row['module'])
        elif row['student'] != user['id']:
            raise ApiError(404, 'Ответ не найден.')
        return row

    def submission(self, user, sid):
        row = self.get(user, sid)
        module_id, current = row['module'], self.versions[row['module']]
        teacher = user['role'] == 'teacher'
        history = [{**r, 'stale': r['version'] != current} for r in self.rows(student=row['student'], module=module_id)
                   if r['case'] == row['case']]
        for r in history:
            if r['stale'] and not teacher:  # an old rubric snapshot must not pre-reveal the current one
                r['logbook'] = [{**e, 'rubric': []} for e in r['logbook']]
        activity = next((a for a in self.activities(module_id, row['student'], teacher)
                         if a['id'] == row['case']), None)
        return {'row': next(r for r in history if r['id'] == sid), 'activity': activity,
                'current_version': current, 'history': history}

    def review(self, user, body):
        if user['role'] != 'teacher':
            raise ApiError(403, 'Проверка доступна только назначенному преподавателю.')
        sid = body.get('submission_id')
        if type(sid) is not int:
            raise ApiError(400, 'Неверный номер ответа.')
        row = self.get(user, sid)
        a = self.source(row['module'], row['case'])
        if row['version'] != self.versions[row['module']] or a is None:
            raise ApiError(409, 'Задание изменилось после отправки. Сначала нужна сверка исходной редакции.')
        decision = body.get('decision')
        if decision not in DECISIONS[a['kind']]:
            raise ApiError(400, 'Допустимые решения: ' + ', '.join(DECISIONS[a['kind']]) + '.')
        return self.pilot.logbook.add(user['id'], sid, decision, body.get('comment'), body.get('key'),
                                      body.get('meeting_date'), body.get('marks'), a['rubric'])

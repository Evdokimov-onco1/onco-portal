"""Read-only teacher roster using the existing completion rules and assignments."""
from pilot.practice import ApiError, PREFIX


def students_overview(pilot, user, module_id=None):
    if user['role'] != 'teacher':
        raise ApiError(403, 'Обзор доступен назначенному преподавателю.')
    assigned = pilot.assignments.get(user['id'], set())
    modules = [{'id': mid, 'title': m['module_title'], 'year': m['pedagogical_year']}
               for mid, m in sorted(pilot.modules.items()) if mid in assigned]
    if module_id is not None:
        pilot.teacher(user, module_id)
        pilot.module(module_id)
    elif modules:
        module_id = modules[0]['id']
    else:
        return {'modules': [], 'module': None, 'students': []}

    # Most recent submission for each activity in its current content version.
    # Archived versions remain available in review history, not pending counters.
    current = {}
    for row in pilot.store.submissions(module=module_id):
        expected = (pilot.practice.versions[module_id] if row['case'].startswith(PREFIX)
                    else pilot.versions[module_id])
        if row['version'] == expected:
            key = (row['student'], row['case'])
            if key not in current or row['id'] > current[key]['id']:
                current[key] = row
    practice_ids = [r['id'] for r in current.values() if r['case'].startswith(PREFIX)]
    events = pilot.logbook.events(practice_ids)
    students = []
    for sid, account in pilot.users.items():
        if account.get('role') != 'student':
            continue
        progress = pilot.completion.state(sid, module_id)
        rows = [r for (student, _), r in current.items() if student == sid]
        clinical_pending = sum(not r['reviews'] for r in rows if not r['case'].startswith(PREFIX))
        practice_pending = sum(not events.get(r['id']) for r in rows if r['case'].startswith(PREFIX))
        students.append({
            'id': sid, 'name': account['name'], 'status': progress['status'],
            'checks_done': sum(bool(c['ok']) for c in progress['checks']),
            'checks_total': len(progress['checks']),
            'teacher_done': sum(bool(c['ok']) for c in progress['teacher_checks']),
            'teacher_total': len(progress['teacher_checks']),
            'pending_clinical': clinical_pending, 'pending_practice': practice_pending,
            'latest_submission_at': max((r['created_at'] for r in rows), default=None),
        })
    students.sort(key=lambda r: (-(r['pending_clinical'] + r['pending_practice']),
                                 r['name'].casefold(), r['id']))
    return {'modules': modules, 'module': module_id, 'students': students}

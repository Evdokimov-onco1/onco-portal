"""Independent black-box checks for GET /api/completion/lectures (teacher-only overview)."""
import copy
import json

import pilot.completion_fixture as fixture
from pilot.completion_fixture import CompletionFixture

THREE = copy.deepcopy(fixture.DATA)
for mid, secret in (('M02', 'SECRET M02 SOLUTION'), ('M03', 'SECRET M03 SOLUTION')):
    m = copy.deepcopy(fixture.DATA['modules'][0])
    m['module_id'], m['module_title'] = mid, 'Synthetic ' + mid
    m['clinical_cases'][0]['answer'] = secret
    THREE['modules'].append(m)


class ThreeModuleFixture(CompletionFixture):
    def setUp(self):
        original = fixture.DATA
        fixture.DATA = THREE
        try:
            super().setUp()
        finally:
            fixture.DATA = original


class LectureOverviewAuthTest(CompletionFixture):
    def test_anonymous_denied(self):
        code, body = self.get(self.anonymous(), '/api/completion/lectures')
        self.assertEqual(code, 401)
        self.assertIn('error', body)

    def test_student_denied(self):
        for client in (self.a, self.b):
            code, body = self.get(client, '/api/completion/lectures')
            self.assertEqual(code, 403)
            self.assertIn('error', body)
            self.assertNotIn('modules', body)

    def test_teacher_without_assignments_sees_empty_totals(self):
        self.server.pilot.assignments['teacher'] = set()
        code, body = self.get(self.t, '/api/completion/lectures')
        self.assertEqual(code, 200)
        self.assertEqual(body['summary'], {'total': 0, 'bound': 0, 'candidates': 0, 'missing': 0})
        self.assertEqual(body['modules'], [])


class LectureOverviewScopeTest(ThreeModuleFixture):
    def test_teacher_sees_only_assigned_modules_and_totals(self):
        self.server.pilot.assignments['teacher'] = {'M01', 'M02'}
        self.bind_lecture()  # binds the M01 faculty-video candidate
        code, body = self.get(self.t, '/api/completion/lectures')
        self.assertEqual(code, 200)
        self.assertEqual([m['module'] for m in body['modules']], ['M01', 'M02'])
        by_module = {m['module']: m for m in body['modules']}
        self.assertEqual(by_module['M01']['status'], 'bound')
        self.assertEqual(by_module['M01']['current']['resource'], self.lecture_id)
        self.assertEqual(by_module['M01']['candidate_count'], 1)
        self.assertEqual(by_module['M02']['status'], 'missing')
        self.assertIsNone(by_module['M02']['current'])
        self.assertEqual(by_module['M02']['candidate_count'], 0)
        self.assertEqual(body['summary'], {'total': 2, 'bound': 1, 'candidates': 0, 'missing': 1})
        self.assertEqual(body['summary']['total'], len(body['modules']))
        raw = json.dumps(body, ensure_ascii=False)
        for secret in ('SECRET MODEL SOLUTION', 'SECRET M02 SOLUTION', 'SECRET M03 SOLUTION',
                       'HIDDEN STANDARD', 'TB DEBRIEF SECRET', 'STAGE TWO SECRET',
                       'M03', 'correct', 'Synthetic 0'):
            self.assertNotIn(secret, raw)


if __name__ == '__main__':
    import unittest
    unittest.main()

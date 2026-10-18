"""Teacher overview invariants with synthetic content and real persistence."""
import json
from pathlib import Path
import tempfile
import unittest

from pilot.server import Pilot
from pilot.practice import ApiError
from pilot.teacher import students_overview


class TeacherOverviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        data = root / 'data.json'
        data.write_text(json.dumps({'modules': [{
            'module_id': mid, 'module_title': 'Synthetic '+mid,
            'pedagogical_year': '1', 'oral_discussion_questions': ['Explain'],
            'clinical_cases': [{'title': 'Task', 'vignette': 'Synthetic',
                                'questions': 'Why?', 'answer': 'PRIVATE STANDARD'}]
        } for mid in ('M01', 'M02')]}))
        users = {'teacher': {'name': 'Teacher', 'role': 'teacher'},
                 'student-c': {'name': 'Third student', 'role': 'student',
                               'password': 'NEVER EXPOSE', 'email': 'private@example.invalid'},
                 'student-empty': {'name': 'No submissions', 'role': 'student'}}
        self.pilot = Pilot(root / 'test.db', data, users=users)
        self.pilot.assignments['teacher'] = {'M01'}
        self.teacher = {'id': 'teacher', 'role': 'teacher'}

    def overview(self):
        return students_overview(self.pilot, self.teacher, 'M01')

    def submit(self, key, version=None, activity='C1'):
        return self.pilot.store.submit('student-c', 'M01', activity,
                                      version or self.pilot.versions['M01'], 'PRIVATE ANSWER', key)

    def row(self):
        return next(s for s in self.overview()['students'] if s['id'] == 'student-c')

    def test_student_and_unassigned_teacher_denied(self):
        with self.assertRaises(ApiError):
            students_overview(self.pilot, {'id': 'student-c', 'role': 'student'})
        with self.assertRaises(ApiError):
            students_overview(self.pilot, self.teacher, 'M02')
        self.assertEqual([m['id'] for m in self.overview()['modules']], ['M01'])

    def test_empty_assignments_and_students_without_submissions(self):
        self.assertEqual(len(self.overview()['students']), 2)
        empty = next(s for s in self.overview()['students'] if s['id'] == 'student-empty')
        self.assertIsNone(empty['latest_submission_at'])
        self.assertEqual(empty['pending_clinical'], 0)
        self.pilot.assignments['teacher'] = set()
        self.assertEqual(students_overview(self.pilot, self.teacher),
                         {'modules': [], 'module': None, 'students': []})

    def test_latest_revision_counted_once_old_content_ignored(self):
        self.submit('v1')
        self.submit('v2')
        self.submit('stale', 'obsolete')
        self.assertEqual(self.row()['pending_clinical'], 1)
        self.pilot.versions['M01'] = 'replacement'
        self.assertEqual(self.row()['pending_clinical'], 0)

    def test_clinical_return_resubmit_accept(self):
        row = self.submit('v1')
        self.pilot.store.review('teacher', row['id'], 'returned', 'Clarify', 'review1')
        self.assertEqual(self.row()['pending_clinical'], 0)
        row2 = self.submit('v2')
        self.assertEqual(self.row()['pending_clinical'], 1)
        self.pilot.store.review('teacher', row2['id'], 'accepted', '', 'review2')
        self.assertEqual(self.row()['pending_clinical'], 0)

    def test_practice_uses_logbook_not_clinical_reviews(self):
        row = self.submit('seminar', self.pilot.practice.versions['M01'], 'P:seminar:1')
        self.assertEqual(self.row()['pending_practice'], 1)
        self.assertEqual(self.row()['pending_clinical'], 0)
        self.pilot.logbook.add('teacher', row['id'], 'discussed', '', 'discussion',
                               '2026-01-01', {}, [])
        self.assertEqual(self.row()['pending_practice'], 0)

    def test_summary_does_not_export_answers_or_account_secrets(self):
        self.submit('v1')
        serialized = json.dumps(self.overview())
        for private in ('PRIVATE ANSWER', 'PRIVATE STANDARD', 'NEVER EXPOSE', 'private@example.invalid'):
            self.assertNotIn(private, serialized)
        self.assertEqual(self.row()['name'], 'Third student')
        self.assertEqual(self.row()['status'], self.pilot.completion.state('student-c', 'M01')['status'])


if __name__ == '__main__':
    unittest.main()

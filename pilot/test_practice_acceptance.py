"""Independent acceptance scenarios. Entirely synthetic teaching content."""
import json
import tempfile
from pathlib import Path
import unittest
from pilot import test_server as fixtures


class PracticeAcceptance(unittest.TestCase):
    start_server = fixtures.HttpTest.start_server
    close = fixtures.HttpTest.close
    client = fixtures.HttpTest.client
    request = fixtures.HttpTest.request

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / 'acceptance.db'
        self.data = self.root / 'data.json'
        self.data.write_text(json.dumps({'modules': [{
            'module_id': 'M01', 'module_title': 'Synthetic training', 'pedagogical_year': '1',
            'clinical_cases': [], 'oral_discussion_questions': ['Explain the synthetic choice.'],
            'osce_links': ['S01'], 'tumorboard_links': ['TB01']}],
            'osce': {'stations': [{'id': 'S01', 'title': 'Synthetic station',
                'task': 'Describe your method.', 'materials': 'Synthetic handout',
                'examiner_standard': 'PRIVATE STATION STANDARD', 'debrief': 'PRIVATE STATION DEBRIEF',
                'checklist': [{'Критерий': 'Synthetic critical action', 'Баллы': '2', 'Критическая ошибка?': 'ДА'}]}]},
            'tumor_board': {'cases': [{'id': 'TB01', 'title': 'Synthetic board', 'instruction': 'Explain each decision.',
                'stages': [{'stage': 1, 'content': ['PUBLIC FIRST STAGE']},
                           {'stage': 2, 'content': ['PRIVATE SECOND STAGE']}],
                'debrief': 'PRIVATE BOARD DEBRIEF',
                'checklist': [{'Критерий': 'Synthetic decision', 'Баллы': '2'}]}]}}))
        self.start_server()
        self.addCleanup(self.close)
        self.a, self.b, self.t = self.client(), self.client(), self.client()
        for client, user in [(self.a, 'student-a'), (self.b, 'student-b'), (self.t, 'teacher')]:
            self.assertEqual(self.request(client, '/api/login', {'username': user, 'password': 'demo-'+user})[0], 200)

    def view(self, client=None):
        code, data = self.request(client or self.a, '/api/practice/M01')
        self.assertEqual(code, 200, data)
        return data

    def send(self, activity, answer='Synthetic written preparation', key=None, client=None):
        body = {'module': 'M01', 'activity': activity, 'version': self.view(client)['version'],
                'answer': answer, 'key': key or activity}
        code, data = self.request(client or self.a, '/api/practice/answers', body)
        self.assertEqual(code, 200, data)
        return data

    def test_tb_data_unlocks_only_for_owner_after_committed_answer(self):
        view = self.view()
        self.assertNotIn('PRIVATE SECOND STAGE', json.dumps(view))
        self.assertNotIn('PRIVATE BOARD DEBRIEF', json.dumps(view))
        late = {'module': 'M01', 'activity': 'P:tb:TB01:2', 'version': view['version'], 'answer': 'skip', 'key': 'skip'}
        self.assertGreaterEqual(self.request(self.a, '/api/practice/answers', late)[0], 400)
        body = {'module': 'M01', 'activity': 'P:tb:TB01:1', 'version': view['version'], 'text': 'draft only'}
        self.assertEqual(self.request(self.a, '/api/practice/drafts', body)[0], 200)
        self.assertNotIn('PRIVATE SECOND STAGE', json.dumps(self.view()))
        self.send('P:tb:TB01:1')
        self.assertIn('PRIVATE SECOND STAGE', json.dumps(self.view()))
        self.assertNotIn('PRIVATE SECOND STAGE', json.dumps(self.view(self.b)))
        self.assertNotIn('PRIVATE BOARD DEBRIEF', json.dumps(self.view()))
        self.send('P:tb:TB01:2')
        self.assertIn('PRIVATE BOARD DEBRIEF', json.dumps(self.view()))

    def test_logbook_return_revision_discussion_and_clinical_isolation(self):
        row = self.send('P:seminar:1')
        self.assertEqual(self.request(self.t, '/api/queue')[1], [])
        self.assertEqual(self.request(self.a, '/api/modules/M01')[1]['attempts'], [])
        event = {'submission_id': row['id'], 'decision': 'returned', 'comment': 'Clarify reasoning',
                 'key': 'review1', 'meeting_date': '2026-01-01', 'marks': {}}
        self.assertEqual(self.request(self.a, '/api/practice/reviews', event)[0], 403)
        code, returned = self.request(self.t, '/api/practice/reviews', event)
        self.assertEqual(code, 200, returned)
        next_row = self.send('P:seminar:1', 'Improved synthetic preparation', 'revision2')
        event.update(submission_id=next_row['id'], decision='discussed', key='review2')
        self.assertEqual(self.request(self.t, '/api/practice/reviews', event)[0], 200)
        activity = self.view()['activities'][0]
        self.assertEqual(len(activity['attempts']), 2)
        self.assertEqual(activity['attempts'][0]['logbook'][-1]['decision'], 'discussed')
        self.assertEqual(activity['attempts'][1]['logbook'][-1]['decision'], 'returned')
        self.assertEqual(self.request(self.b, '/api/practice/submissions/'+str(row['id']))[0], 404)
        self.assertGreaterEqual(self.request(self.t, '/api/reviews', {'submission_id': row['id'],
            'decision': 'accepted', 'comment': '', 'key': 'bypass'})[0], 400)

    def test_osce_standard_gating_and_authoritative_critical_rubric(self):
        self.assertNotIn('PRIVATE STATION STANDARD', json.dumps(self.view()))
        row = self.send('P:osce:S01')
        own = next(a for a in self.view()['activities'] if a['id'] == 'P:osce:S01')
        self.assertEqual(own['standard'], 'PRIVATE STATION STANDARD')
        self.assertNotIn('PRIVATE STATION STANDARD', json.dumps(self.view(self.b)))
        rubric = own['rubric']; self.assertEqual(len(rubric), 1)
        event = {'submission_id': row['id'], 'decision': 'accepted', 'comment': '', 'key': 'critical',
                 'meeting_date': '2026-01-01', 'marks': {rubric[0]['id']: 0}, 'rubric': [], 'teacher': 'forged'}
        self.assertGreaterEqual(self.request(self.t, '/api/practice/reviews', event)[0], 400)
        event['marks'] = {rubric[0]['id']: 2}
        code, accepted = self.request(self.t, '/api/practice/reviews', event)
        self.assertEqual(code, 200, accepted)
        self.assertEqual(accepted['teacher'], 'teacher')
        self.assertEqual(accepted['max_score'], 2)
        self.assertEqual(accepted['score'], 2)
        self.server.pilot.assignments['teacher'] = set()
        self.assertEqual(self.request(self.t, '/api/practice/queue')[1], [])
        self.assertEqual(self.request(self.t, '/api/practice/reviews', event)[0], 403)


if __name__ == '__main__':
    unittest.main()

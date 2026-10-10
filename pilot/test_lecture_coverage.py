"""Teacher lecture coverage overview — synthetic HTTP checks."""
import copy
from contextlib import closing
import json
import sqlite3

from pilot.completion_fixture import CompletionFixture, DATA, FACULTY_VIDEO


def _m02_module():
    m = copy.deepcopy(DATA['modules'][0])
    m['module_id'] = 'M02'
    m['module_title'] = 'Second synthetic module'
    return m


class LectureCoverageTests(CompletionFixture):
    def lectures(self, client=None):
        return self.get(client or self.t, '/api/completion/lectures')

    def test_permissions_and_scope(self):
        self.assertIn(self.lectures(self.anonymous())[0], (401, 403))
        self.assertEqual(self.lectures(self.a)[0], 403)
        code, body = self.lectures()
        self.assertEqual(code, 200)
        self.assertEqual(body['summary']['total'], 1)
        self.assertEqual(len(body['modules']), 1)
        self.assertEqual(body['modules'][0]['module'], 'M01')
        data = json.loads(self.data.read_text())
        data['modules'].append(_m02_module())
        self.data.write_text(json.dumps(data, ensure_ascii=False))
        self.stop()
        self.start_server()
        self.server.pilot.assignments['teacher'] = {'M02'}
        self.t = self.login('teacher')
        code, body = self.lectures()
        self.assertEqual(code, 200)
        self.assertEqual(body['summary']['total'], 1)
        self.assertEqual(body['modules'][0]['module'], 'M02')
        self.assertEqual(body['modules'][0]['status'], 'missing')

    def test_counts_bind_and_candidate_parity(self):
        code, body = self.lectures()
        self.assertEqual(code, 200)
        self.assertEqual(body['summary'], {'total': 1, 'bound': 0, 'candidates': 1, 'missing': 0})
        row = body['modules'][0]
        self.assertEqual(row['status'], 'candidates')
        self.assertEqual(row['candidate_count'], 1)
        self.assertIsNone(row['current'])
        cat = self.get(self.t, '/api/completion/lecture/M01')[1]
        self.assertEqual(row['candidate_count'], len(cat['candidates']))
        self.bind_lecture()
        code, body = self.lectures()
        self.assertEqual(body['summary'], {'total': 1, 'bound': 1, 'candidates': 0, 'missing': 0})
        bound = body['modules'][0]
        self.assertEqual(bound['status'], 'bound')
        self.assertIsNotNone(bound['current'])
        self.assertEqual(bound['current']['resource'], self.lecture_id)

    def test_stale_binding_not_counted_as_bound(self):
        self.bind_lecture()
        self.assertEqual(self.lectures()[1]['summary']['bound'], 1)
        self.server.pilot.materials.videos[0]['title'] = 'Synthetic lecture revised'
        code, body = self.lectures()
        self.assertEqual(code, 200)
        self.assertEqual(body['summary'], {'total': 1, 'bound': 0, 'candidates': 1, 'missing': 0})
        self.assertEqual(body['modules'][0]['status'], 'candidates')
        self.assertIsNone(body['modules'][0]['current'])

    def test_listing_is_read_only(self):
        with closing(sqlite3.connect(self.db)) as conn:
            before = conn.execute('SELECT COUNT(*) FROM completion_lecture_bindings').fetchone()[0]
        for _ in range(3):
            self.assertEqual(self.lectures()[0], 200)
        with closing(sqlite3.connect(self.db)) as conn:
            after = conn.execute('SELECT COUNT(*) FROM completion_lecture_bindings').fetchone()[0]
        self.assertEqual(before, after)

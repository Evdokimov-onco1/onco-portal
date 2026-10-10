"""Logbook durability checks on synthetic rows in isolated temporary DBs."""
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from pilot.logbook import Logbook
from pilot.store import Store

RUBRIC = [{'id': '1', 'label': 'Synthetic A', 'max_score': 1, 'critical': False},
          {'id': '2', 'label': 'Synthetic B', 'max_score': 2, 'critical': True}]
TODAY = date.today().isoformat()


class LogbookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'pilot.db'
        self.store = Store(self.path)
        self.log = Logbook(self.path)
        self.sid = self.store.submit('student-a', 'M01', 'P:osce:S01', 'v1', 'Synthetic answer', 'k1')['id']

    def add(self, **over):
        args = dict(teacher='teacher', submission_id=self.sid, decision='accepted', comment='ok', key='r1',
                    meeting_date=TODAY, marks={'1': 1, '2': 2}, rubric=RUBRIC)
        args.update(over)
        return self.log.add(**args)

    def test_event_snapshot_scores_and_replay(self):
        rubric = [dict(c) for c in RUBRIC]
        event = self.add(rubric=rubric, marks={'1': 0, '2': 2})
        rubric[0]['label'] = 'changed later'
        self.assertEqual((event['score'], event['max_score']), (2, 3))
        self.assertEqual(event['rubric'], RUBRIC)
        self.assertEqual(self.add(marks={'1': 0, '2': 2})['id'], event['id'])
        for over in ({'comment': 'other'}, {'marks': {'1': 1, '2': 2}}, {'decision': 'returned'},
                     {'meeting_date': (date.today() - timedelta(days=1)).isoformat()}):
            with self.assertRaises(ValueError):
                self.add(**{'marks': {'1': 0, '2': 2}, **over})
        second = self.add(key='r2', decision='returned', comment='Rework')
        self.assertEqual([e['id'] for e in self.log.events([self.sid])[self.sid]], [event['id'], second['id']])

    def test_marks_dates_and_critical_guard(self):
        bad = [{'marks': {'1': 1}}, {'marks': {'1': 1, '2': 2, '3': 0}}, {'marks': {'1': True, '2': 2}},
               {'marks': {'1': 2, '2': 2}}, {'marks': {'1': -1, '2': 2}}, {'marks': {'1': 1.0, '2': 2}},
               {'marks': [1, 2]}, {'marks': {'1': 1, '2': 1}},  # critical criterion not fully earned
               {'meeting_date': (date.today() + timedelta(days=1)).isoformat()},
               {'meeting_date': '2026-02-30'}, {'meeting_date': '10.10.2026'}, {'meeting_date': None},
               {'decision': 'returned', 'comment': '  '}, {'decision': 'approved'}, {'key': ''},
               {'submission_id': '1'}, {'submission_id': 9999}, {'comment': None}]
        for over in bad:
            with self.subTest(over=over), self.assertRaises(ValueError):
                self.add(**over)
        event = self.add(decision='returned', comment='Critical step missed', marks={'1': 1, '2': 1})
        self.assertEqual(event['decision'], 'returned')
        self.assertEqual(self.add(key='d', decision='discussed', marks={}, rubric=[])['max_score'], 0)

    def test_parallel_replay_is_one_event(self):
        gate = threading.Barrier(6)
        ids, errors = [], []
        def worker():
            try:
                gate.wait(timeout=5)
                ids.append(self.add()['id'])
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(ids), 6)
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(self.log.events([self.sid])[self.sid]), 1)

    def test_survives_reopen_and_foreign_key(self):
        event = self.add()
        reopened = Logbook(self.path)
        self.assertEqual(reopened.events([self.sid, 12345]), {self.sid: [event], 12345: []})
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA foreign_keys = ON')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO practice_reviews (submission_id, teacher, decision, comment, request_key,"
                           " meeting_date, marks, rubric, score, max_score, created_at)"
                           " VALUES (777, 't', 'accepted', '', 'x', ?, '{}', '[]', 0, 0, 'now')", (TODAY,))
        db.close()


if __name__ == '__main__':
    unittest.main()

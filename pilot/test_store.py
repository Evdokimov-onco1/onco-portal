"""Тесты pilot.store. Запуск из корня репозитория:

    python3 -m unittest pilot.test_store
"""

import os
import tempfile
import threading
import unittest

from pilot.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "store.db")
        self.store = Store(self.path)

    def _submit(self, **over):
        args = {
            "student": "s1",
            "module": "m1",
            "case": "c1",
            "version": "v1",
            "answer": "ответ",
            "key": "k1",
        }
        args.update(over)
        return self.store.submit(**args)

    # --------------------------------------------------------------
    # Отправки
    # --------------------------------------------------------------

    def test_persistence_after_reopen(self):
        first = self._submit()
        reopened = Store(self.path)
        self.assertEqual(reopened.get(first["id"]), first)
        self.assertIsInstance(first["id"], int)
        self.assertTrue(first["created_at"])
        self.assertEqual(first["reviews"], [])

    def test_multiple_attempts_retained_newest_first(self):
        a = self._submit(key="k1", answer="a1")
        b = self._submit(key="k2", answer="a2")
        items = self.store.submissions(student="s1")
        self.assertEqual([x["id"] for x in items], [b["id"], a["id"]])

    def test_submit_exact_replay_returns_same_row(self):
        first = self._submit()
        again = self._submit()
        self.assertEqual(again, first)
        self.assertEqual(len(self.store.submissions()), 1)

    def test_submit_conflicting_replay_rejected(self):
        self._submit()
        with self.assertRaises(ValueError):
            self._submit(answer="другой ответ")
        self.assertEqual(len(self.store.submissions()), 1)

    def test_concurrent_duplicate_submit_one_row(self):
        results, errors = [], []

        def worker():
            try:
                results.append(self._submit())
            except Exception as exc:  # noqa: BLE001 — собираем для ассерта
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 8)
        self.assertEqual(len({r["id"] for r in results}), 1)
        self.assertEqual(len(self.store.submissions()), 1)

    def test_invalid_answer_rejected(self):
        for bad in ("", "   ", None, 42, "x" * 20001):
            with self.assertRaises(ValueError):
                self._submit(answer=bad)
        for bad in ("", "   ", None, 5):
            with self.assertRaises(ValueError):
                self._submit(student=bad)
        self.assertEqual(self.store.submissions(), [])

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.store.get(9999))

    def test_submissions_filters(self):
        self._submit(student="s1", module="m1", key="k1")
        self._submit(student="s1", module="m2", key="k2")
        self._submit(student="s2", module="m1", key="k3")
        self.assertEqual(len(self.store.submissions()), 3)
        self.assertEqual(len(self.store.submissions(student="s1")), 2)
        self.assertEqual(len(self.store.submissions(module="m1")), 2)
        self.assertEqual(len(self.store.submissions(student="s1", module="m2")), 1)

    # --------------------------------------------------------------
    # Проверки
    # --------------------------------------------------------------

    def test_review_replay_and_history(self):
        sub = self._submit()
        r1 = self.store.review("t1", sub["id"], "returned", "переделать", "rk1")
        self.assertEqual(
            self.store.review("t1", sub["id"], "returned", "переделать", "rk1"),
            r1,
        )
        with self.assertRaises(ValueError):
            self.store.review("t1", sub["id"], "accepted", "", "rk1")
        r2 = self.store.review("t1", sub["id"], "accepted", "", "rk2")
        got = self.store.get(sub["id"])
        self.assertEqual([r["id"] for r in got["reviews"]], [r1["id"], r2["id"]])
        # первоначальный ответ не изменился
        self.assertEqual(got["answer"], sub["answer"])

    def test_returned_requires_reason(self):
        sub = self._submit()
        for bad in ("", "   "):
            with self.assertRaises(ValueError):
                self.store.review("t1", sub["id"], "returned", bad, "rk1")
        ok = self.store.review("t1", sub["id"], "accepted", "", "rk2")
        self.assertEqual(ok["decision"], "accepted")
        with self.assertRaises(ValueError):
            self.store.review("t1", sub["id"], "maybe", "x", "rk3")

    def test_review_missing_submission(self):
        with self.assertRaises(ValueError):
            self.store.review("t1", 9999, "accepted", "", "rk1")

    # --------------------------------------------------------------
    # Черновики
    # --------------------------------------------------------------

    def test_drafts_isolation_by_student_and_version(self):
        self.store.save_draft("s1", "m1", "c1", "v1", "черновик s1 v1")
        self.store.save_draft("s1", "m1", "c1", "v2", "черновик s1 v2")
        self.store.save_draft("s2", "m1", "c1", "v1", "черновик s2")
        self.store.save_draft("s1", "m1", "c2", "v1", "второй кейс")

        self.assertEqual(
            self.store.drafts("s1", "m1", "v1"),
            {"c1": "черновик s1 v1", "c2": "второй кейс"},
        )
        self.assertEqual(self.store.drafts("s1", "m1", "v2"), {"c1": "черновик s1 v2"})
        self.assertEqual(self.store.drafts("s2", "m1", "v1"), {"c1": "черновик s2"})

    def test_draft_upsert_and_empty(self):
        self.store.save_draft("s1", "m1", "c1", "v1", "старое")
        self.store.save_draft("s1", "m1", "c1", "v1", "")
        self.assertEqual(self.store.drafts("s1", "m1", "v1"), {"c1": ""})
        with self.assertRaises(ValueError):
            self.store.save_draft("s1", "m1", "c1", "v1", "x" * 20001)

    def test_drafts_persist_after_reopen(self):
        self.store.save_draft("s1", "m1", "c1", "v1", "текст")
        reopened = Store(self.path)
        self.assertEqual(reopened.drafts("s1", "m1", "v1"), {"c1": "текст"})


if __name__ == "__main__":
    unittest.main()

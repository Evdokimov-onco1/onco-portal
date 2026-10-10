"""Synthetic-bank tests for pilot.quiz.QuizStore.

Run: python3 -m unittest pilot.test_quiz
"""

import os
import sqlite3
import tempfile
import threading
import unittest

from pilot.quiz import QuizStore

_HIDDEN = ("correct", "explanation", "source_title", "source_url")


def bank(n, prefix="q", options=4):
    return [{
        "id": f"{prefix}{i}",
        "stem": f"Synthetic stem {i}?",
        "options": [f"option {j}" for j in range(options)],
        "correct": "B",
        "explanation": f"Because {i}",
        "source_title": f"Synthetic source {i}",
        "source_url": f"https://example.test/{i}",
    } for i in range(n)]


def answers_for(questions, n_correct):
    """Answer dict: first `n_correct` questions right, the rest wrong."""
    out = {}
    for i, q in enumerate(questions):
        if i < n_correct:
            out[q["id"]] = q["correct"]
        else:
            out[q["id"]] = next(
                chr(65 + j) for j in range(len(q["options"]))
                if chr(65 + j) != q["correct"])
    return out


class QuizStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "quiz.db")
        self.store = QuizStore(self.path)

    def _submit(self, total, right):
        qs = bank(total, prefix=f"s{total}_{right}_")
        a = self.store.start("stu", "mod", qs, f"key-{total}-{right}")
        return self.store.submit("stu", a["id"], answers_for(qs, right))

    def test_full_bank_retained_and_order_survives_reopen(self):
        qs = bank(30)
        a = self.store.start("stu", "mod", qs, "k1")
        self.assertEqual(len(a["questions"]), 30)
        self.assertEqual({q["id"] for q in a["questions"]},
                         {q["id"] for q in qs})
        self.assertEqual(a["total"], 30)
        order = [q["id"] for q in a["questions"]]
        reopened = QuizStore(self.path).get("stu", a["id"])
        self.assertEqual([q["id"] for q in reopened["questions"]], order)

    def test_no_answers_or_meta_leak_before_submit(self):
        a = self.store.start("stu", "mod", bank(5), "k1")
        for q in a["questions"]:
            for field in _HIDDEN:
                self.assertNotIn(field, q)
        self.assertEqual(a["answers"], {})
        self.assertIsNone(a["score"])
        self.assertIsNone(a["passed"])
        self.assertIsNone(a["submitted_at"])

    def test_scoring_and_threshold(self):
        self.assertTrue(self._submit(10, 7)["passed"])    # 70%
        self.assertFalse(self._submit(23, 16)["passed"])  # 69.6% rounds to 70
        self.assertFalse(self._submit(16, 11)["passed"])  # 68.75%
        self.assertTrue(self._submit(16, 12)["passed"])   # 75%
        r = self._submit(10, 7)
        self.assertEqual((r["score"], r["total"]), (7, 10))

    def test_partial_save_survives_reopen(self):
        qs = bank(5)
        a = self.store.start("stu", "mod", qs, "k1")
        saved = self.store.save("stu", a["id"], {"q0": "A", "q3": "C"})
        self.assertEqual(saved["answers"], {"q0": "A", "q3": "C"})
        reopened = QuizStore(self.path).get("stu", a["id"])
        self.assertEqual(reopened["answers"], {"q0": "A", "q3": "C"})
        self.assertIsNone(reopened["submitted_at"])

    def test_save_replaces_draft(self):
        a = self.store.start("stu", "mod", bank(4), "k1")
        self.store.save("stu", a["id"], {"q0": "A"})
        saved = self.store.save("stu", a["id"], {"q1": "B"})
        self.assertEqual(saved["answers"], {"q1": "B"})

    def test_partial_submit_rejected_and_not_finalized(self):
        a = self.store.start("stu", "mod", bank(4), "k1")
        with self.assertRaises(ValueError):
            self.store.submit("stu", a["id"], {"q0": "A", "q1": "B"})
        with self.assertRaises(ValueError):
            self.store.submit("stu", a["id"], {})
        after = self.store.get("stu", a["id"])
        self.assertIsNone(after["submitted_at"])
        self.assertIsNone(after["score"])

    def test_invalid_answers_rejected(self):
        a = self.store.start("stu", "mod", bank(3), "k1")
        base = {"q0": "A"}
        for bad in ({"q0": "E"},            # letter beyond options
                    {"q0": "Z"}, {"q0": "a"}, {"q0": "AB"},
                    {"q0": 1}, {"q0": None}, {"q0": ["A"]},
                    {"nope": "A"},           # unknown id
                    {1: "A"},                # non-string id
                    {**base, "extra": "B"},  # extras
                    "not-a-dict", ["q0"], None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.store.save("stu", a["id"], bad)

    def test_ownership(self):
        a = self.store.start("stu", "mod", bank(3), "k1")
        self.assertIsNone(self.store.get("other", a["id"]))
        self.assertIsNone(self.store.get("stu", "no-such-id"))
        with self.assertRaises(ValueError):
            self.store.save("other", a["id"], {"q0": "A"})
        with self.assertRaises(ValueError):
            self.store.submit("other", a["id"], answers_for(bank(3), 3))
        with self.assertRaises(ValueError):
            self.store.save("stu", "no-such-id", {"q0": "A"})

    def test_finalized_attempt_immutable(self):
        qs = bank(4)
        a = self.store.start("stu", "mod", qs, "k1")
        answers = answers_for(qs, 4)
        res = self.store.submit("stu", a["id"], answers)
        replay = self.store.submit("stu", a["id"], dict(answers))
        self.assertEqual(replay["id"], res["id"])
        self.assertEqual(replay["submitted_at"], res["submitted_at"])
        changed = dict(answers)
        changed["q0"] = next(c for c in "ABCD" if c != answers["q0"])
        with self.assertRaises(ValueError):
            self.store.submit("stu", a["id"], changed)
        with self.assertRaises(ValueError):
            self.store.save("stu", a["id"], {"q0": "A"})
        same = self.store.save("stu", a["id"], dict(answers))
        self.assertEqual(same["answers"], answers)

    def test_submit_reveals_correctness_and_meta(self):
        qs = bank(3)
        a = self.store.start("stu", "mod", qs, "k1")
        res = self.store.submit("stu", a["id"], answers_for(qs, 3))
        by_id = {q["id"]: q for q in res["questions"]}
        for q in qs:
            item = by_id[q["id"]]
            self.assertEqual(item["correct"], q["correct"])
            self.assertEqual(item["explanation"], q["explanation"])
            self.assertEqual(item["source_title"], q["source_title"])
            self.assertEqual(item["source_url"], q["source_url"])

    def test_start_replay_and_key_conflict(self):
        qs = bank(4)
        a = self.store.start("stu", "mod", qs, "k1")
        b = self.store.start("stu", "mod", [dict(q) for q in qs], "k1")
        self.assertEqual(b["id"], a["id"])
        self.assertEqual(b["created_at"], a["created_at"])
        with self.assertRaises(ValueError):
            self.store.start("stu", "other-mod", qs, "k1")
        with self.assertRaises(ValueError):
            self.store.start("stu", "mod", bank(4, prefix="x"), "k1")
        c = self.store.start("stu", "mod", qs, "k2")
        self.assertNotEqual(c["id"], a["id"])
        d = self.store.start("other", "mod", qs, "k1")
        self.assertNotEqual(d["id"], a["id"])  # key is per-student

    def test_version_stable_across_input_order(self):
        qs = bank(6)
        a = self.store.start("stu", "mod", qs, "k1")
        b = self.store.start("stu", "mod", list(reversed(qs)), "k2")
        self.assertEqual(a["version"], b["version"])

    def test_concurrent_save_cannot_overwrite_submitted_answers(self):
        for n in range(8):
            qs = bank(10)
            a = self.store.start("stu", "mod", qs, f"save-race-{n}")
            complete = answers_for(qs, 7)
            barrier = threading.Barrier(2)
            errors = []
            def save():
                barrier.wait()
                try:
                    self.store.save("stu", a["id"], {"q0": "A"})
                except ValueError:
                    pass  # submit may have committed first
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=save)
            thread.start()
            barrier.wait()
            final = self.store.submit("stu", a["id"], complete)
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            saved = self.store.get("stu", a["id"])
            self.assertEqual(saved["answers"], complete)
            self.assertEqual(saved["score"], 7)
            self.assertEqual(saved["submitted_at"], final["submitted_at"])

    def test_concurrent_duplicate_start(self):
        qs = bank(5)
        barrier = threading.Barrier(8)
        results, errors = [], []

        def worker():
            try:
                barrier.wait(timeout=10)
                results.append(
                    self.store.start("stu", "mod", qs, "race")["id"])
            except Exception as exc:  # noqa: BLE001 - collect for assertion
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(len(results), 8)

    def test_snapshot_immune_to_caller_mutation(self):
        qs = bank(4)
        a = self.store.start("stu", "mod", qs, "k1")
        original = {q["id"]: (q["stem"], list(q["options"]))
                    for q in a["questions"]}
        qs[0]["stem"] = "MUTATED"
        qs[0]["options"][0] = "MUTATED"
        qs[0]["correct"] = "A"
        qs.clear()
        after = self.store.get("stu", a["id"])
        self.assertEqual(len(after["questions"]), 4)
        for q in after["questions"]:
            self.assertEqual((q["stem"], q["options"]), original[q["id"]])

    def test_history_newest_first_per_module(self):
        qs = bank(3)
        ids = [self.store.start("stu", "mod", qs, f"h{i}")["id"]
               for i in range(3)]
        self.store.start("stu", "other-mod", qs, "hx")
        self.store.start("other", "mod", qs, "hx")
        hist = self.store.history("stu", "mod")
        self.assertEqual([h["id"] for h in hist], list(reversed(ids)))

    def test_invalid_start_inputs_rejected(self):
        qs = bank(3)
        good = ("stu", "mod", qs, "k1")
        for args in (("", "mod", qs, "k1"), ("stu", "mod", qs, "k" * 129),
                     ("stu", "mod", [], "k1"), ("stu", "mod", "x", "k1"),
                     ("stu", "mod", qs, ""), (None,) + good[1:]):
            with self.assertRaises(ValueError, msg=repr(args)):
                self.store.start(*args)
        dup = [dict(qs[0]), dict(qs[0])]
        dup[1]["id"] = qs[0]["id"]
        with self.assertRaises(ValueError):
            self.store.start("stu", "mod", dup, "k2")
        bad = dict(qs[0])
        bad["correct"] = "E"
        with self.assertRaises(ValueError):
            self.store.start("stu", "mod", [bad], "k3")
        bad = dict(qs[0])
        bad["options"] = []
        with self.assertRaises(ValueError):
            self.store.start("stu", "mod", [bad], "k4")

    def test_unrelated_tables_untouched(self):
        conn = sqlite3.connect(self.path)
        conn.execute("CREATE TABLE keep_me (x TEXT)")
        conn.execute("INSERT INTO keep_me VALUES ('precious')")
        conn.commit()
        conn.close()
        self.store.start("stu", "mod", bank(3), "k1")
        conn = sqlite3.connect(self.path)
        rows = conn.execute("SELECT x FROM keep_me").fetchall()
        conn.close()
        self.assertEqual(rows, [("precious",)])

    def test_no_db_created_on_import_or_init(self):
        other = os.path.join(self._tmp.name, "virgin.db")
        QuizStore(other)
        self.assertFalse(os.path.exists(other))


if __name__ == "__main__":
    unittest.main()

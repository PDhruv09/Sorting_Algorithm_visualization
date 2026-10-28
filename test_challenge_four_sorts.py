"""Four-sort catalog, grading privacy and safe version transition tests."""
from collections import Counter
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from challenge_api import COOKIE
from challenge_bank import ALGORITHMS, PREVIOUS_VERSION, VERSION, animation, grade, make_questions
from challenge_store import ChallengeStore
from test_challenge import EMAIL, HEADERS, make_app


class FourSortTests(unittest.TestCase):
    def test_catalog_and_every_choice_exclude_removed_sorts(self):
        self.assertEqual({"insertion", "selection", "quick", "merge"}, set(ALGORITHMS))
        questions = make_questions()
        self.assertEqual(Counter(insertion=4, selection=4, merge=4, quick=3),
                         Counter(question["algorithm"] for question in questions))
        self.assertNotRegex(json.dumps(questions).lower(), r"bucket|counting|frequency|tallied")
        for question in questions:
            self.assertEqual(4, len(question["reasoning_choices"]))
            self.assertEqual(1, sum(choice["correct"] for choice in question["reasoning_choices"]))
            self.assertEqual(sorted(question["values"]), animation(question)[-1]["values"])
        for name in ALGORITHMS:
            # Question wording is unique across all 15 prompts for each option.
            from challenge_bank import reasoning_text
            self.assertEqual(15, len({reasoning_text(name, position) for position in range(15)}))

    def test_binary_visible_points_and_private_half_credit(self):
        question = make_questions()[0]
        right = next(choice["id"] for choice in question["reasoning_choices"] if choice["correct"])
        wrong = next(choice["id"] for choice in question["reasoning_choices"] if not choice["correct"])
        other = next(name for name in ALGORITHMS if name != question["algorithm"])
        for identification, reasoning, visible, internal in (
            (question["algorithm"], right, 1, 1),
            (question["algorithm"], wrong, 0, 0.5),
            (other, right, 0, 0.5),
            (other, wrong, 0, 0),
        ):
            with self.subTest(identification=identification, reasoning=reasoning):
                result = grade([question], {"0": {"identification": identification, "reasoning": reasoning}})
                self.assertEqual(visible, result["score"])
                self.assertEqual(internal, result["internal_score"])
                self.assertEqual(1, result["total"])

    def test_old_attempt_is_unchanged_and_old_cookie_cannot_resume_in_new_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "versions.sqlite3"
            with patch.dict(os.environ, {"CHALLENGE_TEST_VERSION": PREVIOUS_VERSION}):
                old_store = ChallengeStore(path)
                old_store.set_student(EMAIL)
                with TestClient(make_app(path)) as old_client:
                    old = old_client.post("/api/challenge/access", json={"email": EMAIL}, headers=HEADERS).json()
                    cookie = old_client.cookies.get(COOKIE)
                with old_store.connection() as database:
                    old_questions = json.loads(database.execute("SELECT questions FROM attempts WHERE id = ?", (old["attempt_id"],)).fetchone()[0])
                for position, question in enumerate(old_questions):
                    choice = next(choice["id"] for choice in question["reasoning_choices"] if choice["correct"])
                    old = old_store.save(cookie, position, question["algorithm"], choice, old["revision"])
                old = old_store.submit(cookie, old["revision"])
                self.assertEqual((30, 30), (old["score"], old["max_score"]))
                with old_store.connection() as database:
                    original = dict(database.execute("SELECT * FROM attempts WHERE id = ?", (old["attempt_id"],)).fetchone())
            with patch.dict(os.environ, {"CHALLENGE_TEST_VERSION": VERSION}):
                with TestClient(make_app(path)) as client:
                    stale = client.get("/api/challenge/current", headers={"Cookie": f"{COOKIE}={cookie}"})
                    self.assertEqual(401, stale.status_code)
                    self.assertIn("updated", stale.json()["detail"])
                    current = client.post("/api/challenge/access", json={"email": EMAIL}, headers=HEADERS).json()
                    self.assertEqual(set(ALGORITHMS), set(current["options"]))
                    self.assertNotEqual(old["attempt_id"], current["attempt_id"])
                    self.assertNotRegex(json.dumps(current).lower(), r"bucket|counting")
                    choice = current["question"]["reasoning_choices"][0]["id"]
                    for removed in ("counting", "bucket"):
                        rejected = client.put("/api/challenge/answers/0", headers=HEADERS, json={
                            "identification": removed, "reasoning": choice, "revision": 0})
                        self.assertEqual(422, rejected.status_code)
                    self.assertEqual(0, client.get("/api/challenge/current").json()["saved_count"])
                with ChallengeStore(path).connection() as database:
                    preserved = dict(database.execute("SELECT * FROM attempts WHERE id = ?", (old["attempt_id"],)).fetchone())
                    self.assertEqual(original, preserved)
                    self.assertEqual(2, database.execute("SELECT count(*) FROM attempts").fetchone()[0])
            # Historical attempts can still be reviewed under an explicit old-version configuration.
            with patch.dict(os.environ, {"CHALLENGE_TEST_VERSION": PREVIOUS_VERSION}):
                with TestClient(make_app(path)) as client:
                    resumed = client.post("/api/challenge/access", json={"email": EMAIL}, headers=HEADERS).json()
                    self.assertEqual(old["attempt_id"], resumed["attempt_id"])
                    self.assertIn("bucket", resumed["options"])
                    self.assertEqual((30, 30), (resumed["score"], resumed["max_score"]))

    def test_historical_multiple_choice_grade_remains_out_of_30(self):
        questions = make_questions(PREVIOUS_VERSION)
        answers = {str(index): {"identification": question["algorithm"],
            "reasoning": next(choice["id"] for choice in question["reasoning_choices"] if choice["correct"])}
            for index, question in enumerate(questions)}
        result = grade(questions, answers, PREVIOUS_VERSION)
        self.assertEqual((30, 30), (result["score"], result["total"]))


if __name__ == "__main__":
    unittest.main()

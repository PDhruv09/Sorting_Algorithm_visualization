import json
import importlib.util
import os
import sqlite3
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from challenge_api import COOKIE, ChallengeProtection, create_router
from challenge_bank import ALGORITHMS, LEGACY_VERSION, PREVIOUS_VERSION, VERSION, animation, make_questions
from challenge_store import ChallengeStore


HEADERS = {"X-Challenge-Request": "1"}
EMAIL = "tester@ucsd.edu"


def make_app(path):
    app = FastAPI()
    app.add_middleware(ChallengeProtection)
    app.include_router(create_router(path))
    return app


class ProxyOriginTests(unittest.TestCase):
    def test_public_https_origin_over_internal_http(self):
        app = FastAPI()
        app.add_middleware(ChallengeProtection)

        @app.post("/api/challenge/access")
        def access():
            return {"accepted": True}

        with patch.dict(os.environ, {"CHALLENGE_PUBLIC_ORIGIN": "https://example.test"}):
            with TestClient(app, base_url="http://internal") as client:
                response = client.post("/api/challenge/access", json={}, headers={**HEADERS, "Origin": "https://example.test"})
                self.assertEqual(200, response.status_code)
                for origin in ("https://evil.test", "http://example.test", "null"):
                    response = client.post("/api/challenge/access", json={}, headers={**HEADERS, "Origin": origin, "X-Forwarded-Host": "evil.test", "X-Forwarded-Proto": "https"})
                    self.assertEqual(403, response.status_code)
                response = client.post("/api/challenge/access", json={}, headers={**HEADERS, "Origin": "https://example.test", "Sec-Fetch-Site": "cross-site"})
                self.assertEqual(403, response.status_code)

    def test_invalid_public_origin_is_rejected(self):
        for origin in ("http://example.test", "https://example.test/path", "https://user:pass@example.test", "https://example.test?x=1"):
            with patch.dict(os.environ, {"CHALLENGE_PUBLIC_ORIGIN": origin}), self.assertRaises(ValueError):
                ChallengeProtection(None)


class ChallengeTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"CHALLENGE_TEST_VERSION": LEGACY_VERSION, "CHALLENGE_FEEDBACK_RELEASED": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "challenge.sqlite3"
        self.store = ChallengeStore(self.path)
        self.store.set_student(EMAIL)
        self.client = TestClient(make_app(self.path))
        self.addCleanup(self.client.close)

    def access(self, email=EMAIL):
        return self.client.post("/api/challenge/access", json={"email": email}, headers=HEADERS)

    def test_anonymous_state_does_not_contact_database(self):
        with patch.object(self.store, "connection", side_effect=AssertionError("Must not connect")):
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as caught:
                self.store.state(None)
        self.assertEqual(401, caught.exception.status_code)

    def save(self, position, revision, identification="insertion", reasoning="A sorted prefix grows."):
        return self.client.put(f"/api/challenge/answers/{position}", headers=HEADERS,
                               json={"identification": identification, "reasoning": reasoning, "revision": revision})

    def submit(self, revision):
        return self.client.post("/api/challenge/submit", headers=HEADERS, json={"revision": revision})

    def test_question_order_is_shuffled_per_attempt_and_preserved_on_resume(self):
        other_email = "second@ucsd.edu"
        self.store.set_student(other_email)
        def shuffle_questions(questions):
            questions.reverse()
        with patch("challenge_store.secrets.SystemRandom") as generator:
            generator.return_value.shuffle.side_effect = shuffle_questions
            self.access()
            generator.return_value.shuffle.assert_called_once()
            with self.store.connection() as database:
                original = database.execute("SELECT questions FROM attempts WHERE student_email = ?", (EMAIL,)).fetchone()[0]
            self.assertEqual(list(reversed(make_questions(LEGACY_VERSION))), json.loads(original))
            self.access()
            self.client.get("/api/challenge/current")
            generator.return_value.shuffle.assert_called_once()
            generator.return_value.shuffle.side_effect = lambda questions: questions.append(questions.pop(0))
            self.access(other_email)
            self.assertEqual(2, generator.return_value.shuffle.call_count)
            with self.store.connection() as database:
                resumed = database.execute("SELECT questions FROM attempts WHERE student_email = ?", (EMAIL,)).fetchone()[0]
                other = database.execute("SELECT questions FROM attempts WHERE student_email = ?", (other_email,)).fetchone()[0]
            self.assertEqual(original, resumed)
            self.assertNotEqual(original, other)
            self.assertCountEqual(json.loads(original), json.loads(other))

    def test_catalog_and_every_animation(self):
        questions = make_questions()
        self.assertEqual(15, len(questions))
        self.assertEqual(set(ALGORITHMS), {question["algorithm"] for question in questions})
        self.assertNotIn("heap", ALGORITHMS)
        self.assertNotIn("bubble", ALGORITHMS)
        for question in questions:
            with self.subTest(question=question["id"]):
                frames = animation(question)
                self.assertEqual(question["values"], frames[0]["values"])
                self.assertEqual(sorted(question["values"]), frames[-1]["values"])
                self.assertGreater(len(frames), 5)
                for frame in frames:
                    self.assertEqual({"values", "active", "action"}, set(frame))
                    self.assertEqual(9, len(frame["values"]))
                    self.assertTrue(all(0 <= index < 9 for index in frame["active"]))

    def test_email_normalization_cookie_and_private_answers(self):
        response = self.access("  TESTER@UCSD.EDU  ")
        self.assertEqual(200, response.status_code)
        self.assertEqual(EMAIL, response.json()["email"])
        self.assertEqual(15, response.json()["total"])
        self.assertEqual({"number", "frames", "prompt"}, set(response.json()["question"]))
        self.assertNotIn("feedback", response.json())
        self.assertNotIn("explanation", response.text)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=strict", response.headers["set-cookie"])
        self.assertEqual("no-store", response.headers["cache-control"])
        with self.store.connection() as database:
            session = database.execute("SELECT token_hash FROM sessions").fetchone()[0]
        self.assertNotEqual(self.client.cookies.get(COOKIE), session)

    def test_denied_and_injection_emails(self):
        self.assertEqual(403, self.access("stranger@ucsd.edu").status_code)
        for email in ("' OR 1=1 --@ucsd.edu", "a@ucsd.edu.evil.com", "<script>@ucsd.edu", "a@elsewhere.edu", "a\x00@ucsd.edu"):
            self.assertEqual(422, self.access(email).status_code, email)
        with self.store.connection() as database:
            self.assertEqual(0, database.execute("SELECT count(*) FROM attempts").fetchone()[0])
            self.assertEqual(1, database.execute("SELECT count(*) FROM students").fetchone()[0])

    def test_protected_endpoints(self):
        self.assertEqual(401, self.client.get("/api/challenge/current").status_code)
        self.assertEqual(401, self.save(0, 0).status_code)
        self.assertEqual(401, self.submit(0).status_code)

    def test_csrf_and_request_size(self):
        self.assertEqual(403, self.client.post("/api/challenge/access", json={"email": EMAIL}).status_code)
        response = self.client.post("/api/challenge/access", json={"email": EMAIL},
                                    headers={**HEADERS, "Origin": "https://attacker.example"})
        self.assertEqual(403, response.status_code)
        response = self.client.post("/api/challenge/access", json={"email": EMAIL},
                                    headers={**HEADERS, "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(403, response.status_code)
        self.assertEqual(415, self.client.post("/api/challenge/access", content="email=tester", headers=HEADERS).status_code)
        response = self.client.post("/api/challenge/access", content=iter([b"a" * 12000, b"b" * 12000]),
                                    headers={**HEADERS, "Content-Type": "application/json"})
        self.assertEqual(413, response.status_code)

    def test_full_challenge_injection_text_and_idempotent_submission(self):
        state = self.access().json()
        with self.store.connection() as database:
            questions = json.loads(database.execute("SELECT questions FROM attempts").fetchone()[0])
        text = "'); DROP TABLE students; -- <img src=x onerror=alert(1)>"
        for position, question in enumerate(questions):
            algorithm = question["algorithm"] if position < 14 else next(name for name in ALGORITHMS if name != question["algorithm"])
            response = self.save(position, state["revision"], algorithm, text)
            self.assertEqual(200, response.status_code, response.text)
            state = response.json()
            self.assertNotIn("feedback", state)
        result = self.submit(state["revision"])
        self.assertEqual(200, result.status_code)
        state = result.json()
        self.assertEqual("submitted", state["status"])
        self.assertEqual(14, state["score"])
        self.assertEqual(15, state["max_score"])
        for private_field in ("feedback", "questions", "answers"):
            self.assertNotIn(private_field, state)
            self.assertNotIn(private_field, self.client.get("/api/challenge/current").json())
            self.assertNotIn(private_field, self.access().json())
        self.assertEqual(state, self.submit(0).json())
        self.assertEqual(409, self.save(0, state["revision"]).status_code)
        with self.store.connection() as database:
            self.assertEqual(1, database.execute("SELECT count(*) FROM students").fetchone()[0])
            self.assertEqual(1, database.execute("SELECT count(*) FROM attempts").fetchone()[0])
            row = database.execute("SELECT * FROM attempts").fetchone()
            self.assertEqual(EMAIL, row["student_email"])
            self.assertIsNotNone(row["submitted_at"])
            self.assertEqual(14, row["score"])
            self.assertEqual(text, json.loads(row["feedback"])["questions"][0]["reasoning"])
            self.assertEqual(15, len(json.loads(row["answers"])))
        self.assertEqual(state["attempt_id"], self.access().json()["attempt_id"])
        self.assertEqual("submitted", self.access().json()["status"])

    def test_multiple_choice_scores_release_gate_and_persistence(self):
        # A new version leaves legacy text attempts intact and snapshots choices.
        legacy = self.access().json()["attempt_id"]
        with patch.dict(os.environ, {"CHALLENGE_TEST_VERSION": VERSION}):
            store = ChallengeStore(self.path)
            with TestClient(make_app(self.path)) as client:
                state = client.post("/api/challenge/access", json={"email": EMAIL}, headers=HEADERS).json()
                self.assertNotEqual(legacy, state["attempt_id"])
                with store.connection() as database:
                    questions = json.loads(database.execute("SELECT questions FROM attempts WHERE id = ?", (state["attempt_id"],)).fetchone()[0])
                self.assertEqual(4, len(state["question"]["reasoning_choices"]))
                self.assertTrue(all(set(choice) == {"id", "text"} for choice in state["question"]["reasoning_choices"]))
                for invalid in ("'; DROP TABLE students; --", "<script>alert(1)</script>", questions[1]["reasoning_choices"][0]["id"]):
                    response = client.put("/api/challenge/answers/0", headers=HEADERS, json={"identification": "merge", "reasoning": invalid, "revision": 0})
                    self.assertEqual(422, response.status_code)
                for position, question in enumerate(questions):
                    # 14 fully correct answers; one identification-only answer.
                    selected = next(choice for choice in question["reasoning_choices"] if choice["correct"] == (position < 14))
                    response = client.put(f"/api/challenge/answers/{position}", headers=HEADERS,
                        json={"identification": question["algorithm"], "reasoning": selected["id"], "revision": state["revision"]})
                    self.assertEqual(200, response.status_code, response.text)
                    state = response.json()
                    self.assertNotIn("score", state)
                    self.assertNotIn("feedback", state)
                    if position == 0:
                        previous = client.get("/api/challenge/current?position=0").json()
                        self.assertEqual(selected["id"], previous["answer"]["reasoning"])
                        self.assertEqual(questions[0]["reasoning_choices"][0]["id"], previous["question"]["reasoning_choices"][0]["id"])
                result = client.post("/api/challenge/submit", headers=HEADERS, json={"revision": state["revision"]}).json()
                self.assertEqual((14, 15), (result["score"], result["max_score"]))
                self.assertNotIn("internal_score", json.dumps(result))
                self.assertNotIn("feedback", result)
                requested = client.get("/api/challenge/current?feedback=true").json()
                self.assertNotIn("feedback", requested)
                self.assertEqual(14, requested["score"])
                resumed = client.post("/api/challenge/access", json={"email": EMAIL}, headers=HEADERS).json()
                self.assertEqual(14, resumed["score"])
                self.assertNotIn("feedback", resumed)
                with patch.dict(os.environ, {"CHALLENGE_FEEDBACK_RELEASED": "1"}):
                    released = client.get("/api/challenge/current").json()
                    self.assertEqual(15, len(released["feedback"]["questions"]))
                    self.assertIn("correct_answer", released["feedback"]["questions"][0])
                    self.assertNotIn("internal_score", json.dumps(released))
                    self.assertNotIn("internal_points", json.dumps(released))
                    self.assertTrue(all(item["points"] in (0, 1) for item in released["feedback"]["questions"]))
                self.assertNotIn("feedback", client.get("/api/challenge/current").json())
                with store.connection() as database:
                    self.assertEqual(2, database.execute("SELECT count(*) FROM attempts").fetchone()[0])
                    stored = json.loads(database.execute("SELECT feedback FROM attempts WHERE id = ?", (resumed["attempt_id"],)).fetchone()[0])
                self.assertEqual(14.5, stored["internal_score"])
                self.assertEqual(0.5, stored["questions"][-1]["internal_points"])

    def test_save_resume_restart_and_revisions(self):
        initial = self.access().json()
        saved = self.save(0, initial["revision"]).json()
        self.assertEqual(1, saved["saved_count"])
        self.assertEqual(2, saved["question"]["number"])
        self.assertEqual(saved["revision"], self.save(0, initial["revision"]).json()["revision"])
        self.assertEqual(409, self.save(0, 0, reasoning="Different stale response").status_code)
        with TestClient(make_app(self.path)) as restarted:
            restarted.cookies.set(COOKIE, self.client.cookies.get(COOKIE))
            resumed = restarted.get("/api/challenge/current").json()
            self.assertEqual(saved["attempt_id"], resumed["attempt_id"])
            self.assertEqual(1, resumed["saved_count"])
            previous = restarted.get("/api/challenge/current?position=0").json()
            self.assertEqual("A sorted prefix grows.", previous["answer"]["reasoning"])
        self.assertEqual(initial["attempt_id"], self.access().json()["attempt_id"])

    def test_cannot_skip_or_submit_incomplete(self):
        self.access()
        self.assertEqual(409, self.save(14, 0).status_code)
        self.assertEqual(409, self.save(-1, 0).status_code)
        self.assertEqual(409, self.client.get("/api/challenge/current?position=14").status_code)
        self.assertEqual(409, self.submit(0).status_code)

    def test_validation_and_spoofed_identity(self):
        self.access()
        for reasoning in (" ", "a" * 4001, "null\x00byte"):
            self.assertEqual(422, self.save(0, 0, reasoning=reasoning).status_code)
        self.assertEqual(422, self.save(0, 0, identification="DROP TABLE attempts").status_code)
        response = self.client.put("/api/challenge/answers/0", headers=HEADERS,
                                   json={"identification": "merge", "reasoning": "Merging ranges", "revision": 0, "email": "someone@ucsd.edu"})
        self.assertEqual(422, response.status_code)

    def test_revocation_expiry_and_logout(self):
        self.access()
        self.store.set_student(EMAIL, False)
        self.assertEqual(401, self.client.get("/api/challenge/current").status_code)
        self.assertEqual(403, self.access().status_code)
        self.store.set_student(EMAIL)
        self.access()
        with self.store.connection() as database:
            database.execute("UPDATE sessions SET expires_at = 0")
        self.assertEqual(401, self.save(0, 0).status_code)
        self.access()
        self.assertEqual(200, self.client.delete("/api/challenge/session", headers=HEADERS).status_code)
        self.assertEqual(401, self.client.get("/api/challenge/current").status_code)

    def test_failure_keeps_previous_database_state(self):
        self.access()
        with patch.object(ChallengeStore, "save", side_effect=sqlite3.OperationalError("private database details")):
            response = self.save(0, 0)
        self.assertEqual(503, response.status_code)
        self.assertNotIn("private database details", response.text)
        self.assertEqual(0, self.client.get("/api/challenge/current").json()["saved_count"])

    def test_rate_limit(self):
        for request in range(20):
            self.assertEqual(403, self.access("stranger@ucsd.edu").status_code)
        self.assertEqual(429, self.access().status_code)

    def test_concurrent_access_creates_one_attempt(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            tokens = list(executor.map(self.store.access, [EMAIL] * 4))
        self.assertEqual(4, len(set(tokens)))
        with self.store.connection() as database:
            self.assertEqual(1, database.execute("SELECT count(*) FROM attempts").fetchone()[0])

    def test_production_cookie(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            with TestClient(make_app(self.path), base_url="https://testserver") as client:
                response = client.post("/api/challenge/access", headers=HEADERS, json={"email": EMAIL})
                self.assertIn("Secure", response.headers["set-cookie"])
                self.assertEqual(200, client.get("/api/challenge/current").status_code)

    def test_public_database_path_rejected(self):
        with self.assertRaises(ValueError):
            create_router(Path(__file__).resolve().parent / "static" / "private.sqlite3")

    def test_explicit_local_http_cookie_setting_is_limited_to_loopback_hosts(self):
        with patch.dict(os.environ, {"APP_ENV": "production", "CHALLENGE_LOCAL_HTTP": "1"}):
            for address, expect_secure in (("http://localhost:8000", False),
                                           ("http://127.0.0.1:8010", False),
                                           ("http://[::1]:8000", False),
                                           ("https://localhost", True),
                                           ("http://example.org", True)):
                with self.subTest(address=address):
                    client_address = "http://localhost:8000" if address == "http://[::1]:8000" else address
                    host_headers = {"Host": "[::1]:8000"} if address == "http://[::1]:8000" else {}
                    with TestClient(make_app(self.path), base_url=client_address, headers=host_headers) as client:
                        response = client.post("/api/challenge/access", headers=HEADERS, json={"email": EMAIL})
                        self.assertEqual(200, response.status_code)
                        self.assertEqual(expect_secure, "Secure" in response.headers["set-cookie"])
                        if not expect_secure:
                            self.assertEqual(200, client.get("/api/challenge/current").status_code)


class DisabledChallengeTests(unittest.TestCase):
    def test_disabled_routes_explain_unavailability_without_loading_challenge_modules(self):
        source = Path(__file__).resolve().parent / "server.py"
        specification = importlib.util.spec_from_file_location("disabled_test_server", source)
        module = importlib.util.module_from_spec(specification)
        runner = types.ModuleType("runner")
        runner.execute_java = lambda *arguments: None
        with patch.dict(os.environ, {"CHALLENGE_MODE_ENABLED": "0"}):
            with patch.dict("sys.modules", {"runner": runner, "challenge_api": None, specification.name: module}):
                specification.loader.exec_module(module)
        with TestClient(module.app) as client:
            self.assertEqual(200, client.get("/challenge").status_code)
            self.assertEqual(200, client.get("/health").status_code)
            for method, path in (("GET", "/api/challenge/current"),
                                 ("POST", "/api/challenge/access"),
                                 ("PUT", "/api/challenge/answers/0"),
                                 ("POST", "/api/challenge/submit")):
                with self.subTest(method=method, path=path):
                    response = client.request(method, path)
                    self.assertEqual(503, response.status_code)
                    self.assertEqual("challenge_unavailable", response.json()["code"])
                    self.assertEqual("no-store", response.headers["cache-control"])


if __name__ == "__main__":
    unittest.main()

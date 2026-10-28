"""Classroom regression against temporary SQLite, not an Azure capacity benchmark."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from challenge_api import ChallengeProtection, create_router
from challenge_bank import VERSION
from challenge_store import ChallengeStore


CLASSROOM = {
    "CHALLENGE_TEST_VERSION": VERSION,
    "CHALLENGE_FEEDBACK_RELEASED": "0",
    "CHALLENGE_ACCESS_REQUESTS_PER_MINUTE": "240",
    "CHALLENGE_WRITE_REQUESTS_PER_MINUTE": "2400",
    "APP_ENV": "development",
}
HEADERS = {"X-Challenge-Request": "1"}


class ClassroomTests(unittest.IsolatedAsyncioTestCase):
    async def test_70_students_share_one_proxy_and_keep_separate_saved_submissions(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CLASSROOM):
            path = Path(directory) / "classroom.sqlite3"
            store = ChallengeStore(path)
            emails = [f"classroom-test-{index:02d}@ucsd.edu" for index in range(70)]
            for email in emails:
                store.set_student(email)
            app = FastAPI()
            app.add_middleware(ChallengeProtection)
            app.include_router(create_router(path))
            transport = httpx.ASGITransport(app=app, client=("192.168.0.1", 12345))
            # Interleave 70 sessions but serialize requests for SQLite, which is
            # single-writer storage. The test below checks a 70-request middleware
            # burst; only staging can measure Azure SQL throughput.
            in_flight = asyncio.Semaphore(1)

            async def student(email):
                # Every student has a private cookie jar, despite sharing one IP.
                async with httpx.AsyncClient(transport=transport, base_url="http://classroom.test",
                                             headers=HEADERS) as client:
                    async def checked(method, route, **kwargs):
                        async with in_flight:
                            response = await client.request(method, "/api/challenge" + route, **kwargs)
                        self.assertEqual(200, response.status_code, response.text)
                        result = response.json()
                        self.assertEqual(email, result["email"])
                        return result

                    state = await checked("POST", "/access", json={"email": email})
                    attempt = state["attempt_id"]
                    for position in range(15):
                        choice = state["question"]["reasoning_choices"][0]["id"]
                        state = await checked("PUT", f"/answers/{position}", json={
                            "identification": "insertion", "reasoning": choice,
                            "revision": state["revision"],
                        })
                        self.assertNotIn("feedback", state)
                        if position == 0:
                            resumed = await checked("GET", "/current?position=0")
                            self.assertEqual(choice, resumed["answer"]["reasoning"])
                            self.assertEqual(attempt, resumed["attempt_id"])
                    submitted = await checked("POST", "/submit", json={"revision": state["revision"]})
                    resumed = await checked("GET", "/current")
                    self.assertEqual("submitted", resumed["status"])
                    self.assertEqual(submitted["score"], resumed["score"])
                    self.assertEqual(attempt, resumed["attempt_id"])
                    self.assertNotIn("feedback", resumed)
                    return attempt

            attempts = await asyncio.gather(*(student(email) for email in emails), return_exceptions=True)
            for result in attempts:
                if isinstance(result, BaseException):
                    raise result
            self.assertEqual(70, len(set(attempts)))
            with store.connection() as database:
                rows = database.execute("SELECT student_email, status, answers FROM attempts").fetchall()
            self.assertEqual(set(emails), {row["student_email"] for row in rows})
            self.assertEqual(70, len(rows))
            self.assertTrue(all(row["status"] == "submitted" and len(json.loads(row["answers"])) == 15
                                for row in rows))

    async def test_70_simultaneous_requests_pass_shared_proxy_classroom_limit(self):
        with patch.dict(os.environ, CLASSROOM):
            app = FastAPI()
            app.add_middleware(ChallengeProtection)

            @app.post("/api/challenge/access")
            def accepted():
                return {"ok": True}

            transport = httpx.ASGITransport(app=app, client=("192.168.0.1", 12345))
            async with httpx.AsyncClient(transport=transport, base_url="http://classroom.test",
                                         headers=HEADERS) as client:
                responses = await asyncio.gather(*(client.post("/api/challenge/access", json={
                    "email": f"classroom-test-{index:02d}@ucsd.edu"}) for index in range(70)))
            self.assertTrue(all(response.status_code == 200 for response in responses))

    async def test_configured_limits_still_reject_excess_requests(self):
        settings = {"CHALLENGE_ACCESS_REQUESTS_PER_MINUTE": "3",
                    "CHALLENGE_WRITE_REQUESTS_PER_MINUTE": "4"}
        with patch.dict(os.environ, settings):
            app = FastAPI()
            app.add_middleware(ChallengeProtection)

            @app.post("/api/challenge/access")
            @app.post("/api/challenge/submit")
            def accepted():
                return {"ok": True}

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://classroom.test", headers=HEADERS) as client:
                for route, limit in (("access", 3), ("submit", 4)):
                    for _ in range(limit):
                        self.assertEqual(200, (await client.post(f"/api/challenge/{route}", json={})).status_code)
                    self.assertEqual(429, (await client.post(f"/api/challenge/{route}", json={})).status_code)

    def test_invalid_rate_limit_configuration_fails_at_startup(self):
        for value in ("0", "-1", "100001", "invalid"):
            with patch.dict(os.environ, {"CHALLENGE_ACCESS_REQUESTS_PER_MINUTE": value}):
                with self.assertRaises(ValueError):
                    ChallengeProtection(None)


if __name__ == "__main__":
    unittest.main()

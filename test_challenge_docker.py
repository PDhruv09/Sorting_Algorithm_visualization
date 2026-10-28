import argparse
import json
import os
import uuid

import httpx

from challenge_store import ChallengeStore


def require(response, status):
    if response.status_code != status:
        raise AssertionError(f"Expected {status}, got {response.status_code}: {response.text}")
    return response.json()


def question_keys(store, attempt_id):
    with store.connection() as database:
        row = database.execute("SELECT questions FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    return json.loads(row["questions"])


def prepare(store, client):
    email = f"docker-check-{uuid.uuid4().hex[:12]}@ucsd.edu"
    require(client.get("/health"), 200)
    assert client.get("/challenge").status_code == 200
    require(client.get("/api/challenge/current"), 401)
    require(client.post("/api/challenge/access", json={"email": email}), 403)
    require(client.post("/api/challenge/access", json={"email": "' OR 1=1 --@ucsd.edu"}), 422)
    require(client.post("/api/challenge/access", headers={"Origin": "https://attacker.example"}, json={"email": email}), 403)
    store.set_student(email)
    response = client.post("/api/challenge/access", json={"email": email})
    state = require(response, 200)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Secure" not in cookie
    assert "feedback" not in state and set(state["question"]) == {"number", "frames", "prompt", "reasoning_choices"}
    assert require(client.get("/api/challenge/current"), 200)["attempt_id"] == state["attempt_id"]
    questions = question_keys(store, state["attempt_id"])
    saved = require(client.put("/api/challenge/answers/0", json={
        "identification": questions[0]["algorithm"],
        "reasoning": next(choice["id"] for choice in questions[0]["reasoning_choices"] if choice["correct"]),
        "revision": state["revision"],
    }), 200)
    assert saved["saved_count"] == 1
    require(client.post("/api/challenge/submit", json={"revision": saved["revision"]}), 409)
    for route in ("/secrets/challenge.sqlite3", "/var/lib/sortviz/challenge.sqlite3", "/challenge_bank.py"):
        assert client.get(route).status_code == 404
    print(json.dumps({"stage": "prepared", "email": email, "attempt_id": saved["attempt_id"], "saved_count": saved["saved_count"]}))


def finish(store, client, email, attempt_id):
    if not email.startswith("docker-check-") or not email.endswith("@ucsd.edu"):
        raise ValueError("Only generated Docker test accounts may be used")
    state = require(client.post("/api/challenge/access", json={"email": email}), 200)
    assert state["attempt_id"] == attempt_id
    assert state["saved_count"] == 1 and state["question"]["number"] == 2
    previous = require(client.get("/api/challenge/current?position=0"), 200)
    questions = question_keys(store, attempt_id)
    assert previous["answer"]["reasoning"] == next(choice["id"] for choice in questions[0]["reasoning_choices"] if choice["correct"])
    for position in range(1, 15):
        state = require(client.put(f"/api/challenge/answers/{position}", json={
            "identification": questions[position]["algorithm"],
            "reasoning": next(choice["id"] for choice in questions[position]["reasoning_choices"] if choice["correct"]),
            "revision": state["revision"],
        }), 200)
    state = require(client.post("/api/challenge/submit", json={"revision": state["revision"]}), 200)
    assert state["status"] == "submitted"
    assert "feedback" not in state and state["score"] == 30 and state["max_score"] == 30
    with store.connection() as database:
        assert database.execute("SELECT score FROM attempts WHERE id = ?", (attempt_id,)).fetchone()[0] == 30
    assert require(client.post("/api/challenge/submit", json={"revision": 0}), 200) == state
    store.set_student(email, False)
    require(client.get("/api/challenge/current"), 401)
    print(json.dumps({"stage": "passed", "persisted_attempt": attempt_id, "score": "30/30", "test_account_disabled": True}))


def main():
    parser = argparse.ArgumentParser(description="Two-stage Docker HTTP and persistence test using a generated test account.")
    parser.add_argument("stage", choices=("prepare", "finish"))
    parser.add_argument("--email")
    parser.add_argument("--attempt-id")
    arguments = parser.parse_args()
    if arguments.stage == "finish" and not (arguments.email and arguments.attempt_id):
        parser.error("finish requires --email and --attempt-id from prepare")
    store = ChallengeStore(os.environ["CHALLENGE_DB_PATH"])
    with httpx.Client(base_url="http://127.0.0.1:8000", headers={"X-Challenge-Request": "1"}, timeout=15, trust_env=False) as client:
        if arguments.stage == "prepare":
            prepare(store, client)
        else:
            finish(store, client, arguments.email, arguments.attempt_id)


if __name__ == "__main__":
    main()

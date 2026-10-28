from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from challenge_bank import VERSION, SUPPORTED_VERSIONS, algorithms_for_version, grade, make_questions, public_question


EMAIL_PATTERN = re.compile(r"[a-z0-9][a-z0-9._+-]{0,63}@ucsd\.edu", re.ASCII)
SESSION_SECONDS = 8 * 60 * 60


class DatabaseUnavailable(Exception):
    """A database failure safe to translate into a generic retry response."""


def configured_version():
    version = os.getenv("CHALLENGE_TEST_VERSION", VERSION)
    if version not in SUPPORTED_VERSIONS:
        raise ValueError("Unsupported CHALLENGE_TEST_VERSION")
    return version


def create_store(database_path=None):
    backend = os.getenv("CHALLENGE_DB_BACKEND", "sqlite").lower()
    if database_path is not None:
        backend = "sqlite"  # Explicit paths are used by isolated local tests/tools.
    if backend == "azure_sql":
        from challenge_sql import AzureChallengeStore
        return AzureChallengeStore()
    if backend != "sqlite":
        raise ValueError("CHALLENGE_DB_BACKEND must be sqlite or azure_sql")
    base = Path(__file__).resolve().parent
    path = Path(database_path or os.getenv("CHALLENGE_DB_PATH", str(base / "secrets" / "challenge.sqlite3"))).resolve()
    static = (base / "static").resolve()
    if path == static or static in path.parents:
        raise ValueError("The challenge database must be outside the static directory.")
    return ChallengeStore(path)


def normalize_email(value):
    email = value.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("Enter a valid UCSD email address.")
    return email


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class ChallengeStore:
    azure_sql = False

    def __init__(self, path):
        self.test_version = configured_version()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as database:
            schema_version = database.execute("PRAGMA user_version").fetchone()[0]
            if schema_version not in (0, 1):
                raise RuntimeError("Unsupported challenge database version")
            database.executescript("""
                CREATE TABLE IF NOT EXISTS students (
                    email TEXT PRIMARY KEY,
                    role TEXT NOT NULL DEFAULT 'student',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY,
                    student_email TEXT NOT NULL REFERENCES students(email),
                    test_version TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'in_progress',
                    current_index INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 0,
                    questions TEXT NOT NULL,
                    answers TEXT NOT NULL DEFAULT '{}',
                    feedback TEXT,
                    score INTEGER,
                    started_at TEXT NOT NULL,
                    submitted_at TEXT,
                    UNIQUE(student_email, test_version, attempt_number)
                );
                CREATE INDEX IF NOT EXISTS attempts_email ON attempts(student_email);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL REFERENCES attempts(id),
                    expires_at REAL NOT NULL
                );
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def connection(self):
        database = sqlite3.connect(self.path, timeout=10)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys = ON")
        try:
            with database:
                yield database
        finally:
            database.close()

    def set_student(self, email, enabled=True):
        email = normalize_email(email)
        with self.connection() as database:
            database.execute(
                "INSERT INTO students(email, enabled, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(email) DO UPDATE SET enabled = excluded.enabled",
                (email, int(enabled), timestamp()),
            )
        return email

    def access(self, email):
        email = normalize_email(email)
        with self.connection() as database:
            self.begin_write(database)
            student = database.execute(
                "SELECT email FROM students WHERE email = ? AND enabled = 1", (email,)
            ).fetchone()
            if student is None:
                raise HTTPException(403, "Access denied. This email is not authorized for Challenge Mode.")
            attempt = database.execute(
                ("SELECT TOP (1) *" if self.azure_sql else "SELECT *") +
                " FROM attempts" + (" WITH (UPDLOCK, HOLDLOCK)" if self.azure_sql else "") +
                " WHERE student_email = ? AND test_version = ? "
                "ORDER BY attempt_number DESC" + ("" if self.azure_sql else " LIMIT 1"), (email, self.test_version)
            ).fetchone()
            if attempt is None:
                questions = make_questions(self.test_version)
                secrets.SystemRandom().shuffle(questions)
                attempt_id = secrets.token_hex(16)
                database.execute(
                    "INSERT INTO attempts(id, student_email, test_version, questions, started_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (attempt_id, email, self.test_version, json.dumps(questions), timestamp()),
                )
            else:
                attempt_id = attempt["id"]
            token = secrets.token_urlsafe(32)
            database.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
            database.execute("DELETE FROM sessions WHERE attempt_id = ?", (attempt_id,))
            database.execute(
                "INSERT INTO sessions(token_hash, attempt_id, expires_at) VALUES (?, ?, ?)",
                (self.token_hash(token), attempt_id, time.time() + SESSION_SECONDS),
            )
        return token

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def begin_write(self, database):
        if not self.azure_sql:
            database.execute("BEGIN IMMEDIATE")

    def authenticated(self, database, token, write=False):
        if not token or len(token) > 100:
            raise HTTPException(401, "Enter your email to start or resume your challenge.")
        attempt = database.execute(
            "SELECT attempts.* FROM sessions "
            "JOIN attempts" + (" WITH (UPDLOCK, HOLDLOCK)" if write and self.azure_sql else "") +
            " ON attempts.id = sessions.attempt_id "
            "JOIN students ON students.email = attempts.student_email "
            "WHERE sessions.token_hash = ? AND sessions.expires_at > ? AND students.enabled = 1",
            (self.token_hash(token), time.time()),
        ).fetchone()
        if attempt is None:
            raise HTTPException(401, "Your session has ended. Enter your email to resume your saved challenge.")
        if attempt["test_version"] != self.test_version:
            raise HTTPException(401, "Challenge Mode has been updated. Enter your email to start the current challenge. Your earlier attempt is preserved.")
        return attempt

    def state(self, token, position=None):
        # An anonymous page load does not need to wake or contact the database.
        if not token or len(token) > 100:
            raise HTTPException(401, "Enter your email to start or resume your challenge.")
        with self.connection() as database:
            attempt = self.authenticated(database, token)
            return self.public_state(attempt, position)

    @staticmethod
    def public_state(attempt, position=None):
        questions = json.loads(attempt["questions"])
        answers = json.loads(attempt["answers"])
        result = {"attempt_id": attempt["id"], "email": attempt["student_email"],
                  "test_version": attempt["test_version"], "status": attempt["status"],
                  "total": len(questions), "saved_count": len(answers),
                  "current_index": attempt["current_index"], "revision": attempt["revision"],
                  "points_per_question": 1 if attempt["test_version"] == VERSION else
                      (2 if all("reasoning_choices" in q for q in questions) else 1),
                  "started_at": attempt["started_at"]}
        if attempt["status"] == "submitted":
            result["submitted_at"] = attempt["submitted_at"]
            result["score"] = attempt["score"]
            result["max_score"] = len(questions) * (2 if attempt["test_version"] != VERSION and
                all("reasoning_choices" in q for q in questions) else 1)
            if os.getenv("CHALLENGE_FEEDBACK_RELEASED", "0") == "1":
                feedback = json.loads(attempt["feedback"])
                # Partial-credit data remains internal, even when explanations
                # are released. A later grading decision may expose it explicitly.
                feedback.pop("internal_score", None)
                for item in feedback.get("questions", []):
                    item.pop("internal_points", None)
                result["feedback"] = feedback
        else:
            position = attempt["current_index"] if position is None else position
            if not 0 <= position <= attempt["current_index"] or position >= len(questions):
                raise HTTPException(409, "Complete the current question before continuing.")
            result["question"] = public_question(questions[position], position)
            result["answer"] = answers.get(str(position))
        return result

    def save(self, token, position, identification, reasoning, revision):
        with self.connection() as database:
            self.begin_write(database)
            attempt = self.authenticated(database, token, write=True)
            if attempt["status"] != "in_progress":
                raise HTTPException(409, "This challenge has already been submitted.")
            questions = json.loads(attempt["questions"])
            answers = json.loads(attempt["answers"])
            if identification not in algorithms_for_version(attempt["test_version"]):
                raise HTTPException(422, "Choose one of the algorithms in this challenge.")
            if not 0 <= position <= attempt["current_index"] or position >= len(questions):
                raise HTTPException(409, "Complete the current question before continuing.")
            choices = questions[position].get("reasoning_choices")
            if choices is not None and reasoning not in {choice["id"] for choice in choices}:
                raise HTTPException(422, "Choose one of the reasoning options for this question.")
            answer = {"identification": identification, "reasoning": reasoning}
            if revision != attempt["revision"]:
                previous = answers.get(str(position), {})
                if all(previous.get(key) == value for key, value in answer.items()):
                    return self.public_state(attempt)
                raise HTTPException(409, "This attempt changed in another tab. Reload to see the saved answers.")
            answer["saved_at"] = timestamp()
            answers[str(position)] = answer
            next_index = max(attempt["current_index"], min(position + 1, len(questions) - 1))
            database.execute(
                "UPDATE attempts SET answers = ?, current_index = ?, revision = revision + 1 WHERE id = ?",
                (json.dumps(answers), next_index, attempt["id"]),
            )
            updated = database.execute("SELECT * FROM attempts WHERE id = ?", (attempt["id"],)).fetchone()
            return self.public_state(updated)

    def submit(self, token, revision):
        with self.connection() as database:
            self.begin_write(database)
            attempt = self.authenticated(database, token, write=True)
            if attempt["status"] == "submitted":
                return self.public_state(attempt)
            if revision != attempt["revision"]:
                raise HTTPException(409, "This attempt changed in another tab. Reload before submitting.")
            questions = json.loads(attempt["questions"])
            answers = json.loads(attempt["answers"])
            if set(answers) != {str(position) for position in range(len(questions))}:
                raise HTTPException(409, "Answer all 15 questions before submitting the challenge.")
            feedback = grade(questions, answers, attempt["test_version"])
            database.execute(
                "UPDATE attempts SET status = 'submitted', feedback = ?, score = ?, "
                "submitted_at = ?, revision = revision + 1 WHERE id = ?",
                (json.dumps(feedback), feedback["score"], timestamp(), attempt["id"]),
            )
            updated = database.execute("SELECT * FROM attempts WHERE id = ?", (attempt["id"],)).fetchone()
            return self.public_state(updated)

    def logout(self, token):
        with self.connection() as database:
            database.execute("DELETE FROM sessions WHERE token_hash = ?", (self.token_hash(token or ""),))

from __future__ import annotations

import os
import logging
import sqlite3
import time
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.datastructures import Headers

from challenge_bank import ALGORITHMS
from challenge_store import create_store, DatabaseUnavailable, SESSION_SECONDS, normalize_email


COOKIE = "challenge_session"
BASE = Path(__file__).resolve().parent


def request_limit(name, default):
    value = int(os.getenv(name, str(default)))
    if not 1 <= value <= 100000:
        raise ValueError(f"{name} must be between 1 and 100000 requests per minute")
    return value


class AccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=1, max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        return normalize_email(value)


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identification: Literal["insertion", "selection", "merge", "quick", "counting", "bucket"]
    reasoning: str = Field(min_length=1, max_length=4000)
    revision: int = Field(ge=0, strict=True)

    @field_validator("reasoning")
    @classmethod
    def validate_reasoning(cls, value):
        value = value.strip()
        if not value or any(ord(character) < 32 and character not in "\n\r\t" for character in value):
            raise ValueError("Enter your reasoning using ordinary text.")
        return value


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0, strict=True)


class ChallengeProtection:
    def __init__(self, app):
        self.app = app
        self.public_origin = os.getenv("CHALLENGE_PUBLIC_ORIGIN", "").strip()
        if self.public_origin:
            parsed = urlsplit(self.public_origin)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                    or parsed.password or parsed.path or parsed.query or parsed.fragment
                    or any(c.isspace() for c in self.public_origin)):
                raise ValueError("CHALLENGE_PUBLIC_ORIGIN must be an HTTPS origin without a path")
        self.requests = {}
        self.lock = Lock()
        self.access_limit = request_limit("CHALLENGE_ACCESS_REQUESTS_PER_MINUTE", 20)
        self.answer_limit = request_limit("CHALLENGE_WRITE_REQUESTS_PER_MINUTE", 120)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path.startswith("/api/challenge") or path == "/challenge"):
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)

        async def protected_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message["headers"]) + [
                    (b"cache-control", b"no-store"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
                    (b"referrer-policy", b"no-referrer"),
                ]
            await send(message)

        async def reject(status, detail):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, protected_send)

        if scope["method"] in ("POST", "PUT", "DELETE"):
            if headers.get("x-challenge-request") != "1" or headers.get("sec-fetch-site") == "cross-site":
                return await reject(403, "Open Challenge Mode on this site and try again.")
            origin = headers.get("origin")
            # A configured public origin handles TLS termination without trusting
            # client-supplied forwarding headers or weakening the origin check.
            expected_origin = self.public_origin or f"{scope['scheme']}://{headers.get('host', '')}"
            if origin and origin != expected_origin:
                return await reject(403, "Requests must come from this site.")
            if scope["method"] != "DELETE" and headers.get("content-type", "").split(";")[0] != "application/json":
                return await reject(415, "Send answers as JSON.")
            now = time.monotonic()
            client = scope.get("client") or ("unknown", 0)
            key = (client[0], "access" if path.endswith("/access") else "answers")
            limit = self.access_limit if key[1] == "access" else self.answer_limit
            with self.lock:
                self.requests = {address: times for address, times in self.requests.items() if times and times[-1] > now - 60}
                if key not in self.requests and len(self.requests) >= 4096:
                    limited = True
                else:
                    recent = self.requests.setdefault(key, deque())
                    while recent and recent[0] <= now - 60:
                        recent.popleft()
                    limited = len(recent) >= limit
                    if not limited:
                        recent.append(now)
            if limited:
                return await reject(429, "Too many requests. Wait one minute and try again.")
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > 20000:
                    return await reject(413, "The answer is too large.")
                if not message.get("more_body", False):
                    break
            delivered = False

            async def replay_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            request_receive = replay_receive
        else:
            request_receive = receive
        try:
            await self.app(scope, request_receive, protected_send)
        except (sqlite3.Error, OSError, DatabaseUnavailable) as error:
            logging.getLogger(__name__).error(
                "Challenge persistence failure: error_type=%s sqlite_code=%s",
                type(error).__name__, getattr(error, "sqlite_errorcode", None))
            detail = ("Your response could not be saved. Keep this page open and try again."
                      if path.startswith("/api/challenge/answers/") or path == "/api/challenge/submit"
                      else "Challenge data is temporarily unavailable. Keep this page open and try again.")
            await reject(503, detail)


def create_router(database_path=None):
    store = create_store(database_path)
    router = APIRouter()
    secure_cookie = os.getenv("APP_ENV", "development").lower() == "production"
    local_http = os.getenv("CHALLENGE_LOCAL_HTTP", "0") == "1"

    @router.post("/api/challenge/access")
    def access(body: AccessRequest, response: Response, request: Request):
        token = store.access(body.email)
        local_request = local_http and request.url.scheme == "http" and request.url.hostname in {
            "localhost", "127.0.0.1", "::1",
        }
        response.set_cookie(COOKIE, token, httponly=True, secure=secure_cookie and not local_request,
                            samesite="strict", max_age=SESSION_SECONDS, path="/api/challenge")
        result = store.state(token)
        result["options"] = ALGORITHMS
        return result

    @router.get("/api/challenge/current")
    def current(request: Request, position: int | None = None):
        result = store.state(request.cookies.get(COOKIE), position)
        result["options"] = ALGORITHMS
        return result

    @router.put("/api/challenge/answers/{position}")
    def save(position: int, body: AnswerRequest, request: Request):
        return store.save(request.cookies.get(COOKIE), position, body.identification, body.reasoning, body.revision)

    @router.post("/api/challenge/submit")
    def submit(body: SubmitRequest, request: Request):
        return store.submit(request.cookies.get(COOKIE), body.revision)

    @router.delete("/api/challenge/session")
    def logout(request: Request, response: Response):
        store.logout(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/api/challenge")
        return {"ok": True}

    return router

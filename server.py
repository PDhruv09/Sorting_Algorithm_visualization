from __future__ import annotations

import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from runner import execute_java


# ============================================================
# Paths
# ============================================================

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"


# ============================================================
# Environment configuration
# ============================================================

APP_ENV = os.getenv(
    "APP_ENV",
    "development",
).lower()

MAX_SOURCE_CHARS = int(
    os.getenv(
        "MAX_SOURCE_CHARS",
        "50000",
    )
)

MAX_ARRAY_LENGTH = int(
    os.getenv(
        "MAX_ARRAY_LENGTH",
        "500",
    )
)

MAX_REQUEST_BYTES = int(
    os.getenv(
        "MAX_REQUEST_BYTES",
        "100000",
    )
)

RATE_LIMIT_REQUESTS = int(
    os.getenv(
        "RATE_LIMIT_REQUESTS",
        "20",
    )
)

RATE_LIMIT_WINDOW_SECONDS = int(
    os.getenv(
        "RATE_LIMIT_WINDOW_SECONDS",
        "60",
    )
)

IS_PRODUCTION = (
    APP_ENV == "production"
)


# ============================================================
# App
# ============================================================

app = FastAPI(
    title="Java Sorting Visualizer",
    version="3.0",

    docs_url=(
        None
        if IS_PRODUCTION
        else "/docs"
    ),

    redoc_url=(
        None
        if IS_PRODUCTION
        else "/redoc"
    ),

    openapi_url=(
        None
        if IS_PRODUCTION
        else "/openapi.json"
    ),
)


# ============================================================
# Request models
# ============================================================

METHOD_NAME_PATTERN = re.compile(
    r"^[A-Za-z_$][A-Za-z0-9_$]*$"
)


class ExecuteRequest(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=MAX_SOURCE_CHARS,
    )

    inputArray: list[int] = Field(
        min_length=1,
        max_length=MAX_ARRAY_LENGTH,
    )

    methodName: str | None = Field(
        default=None,
        max_length=100,
    )

    @field_validator("code")
    @classmethod
    def validate_code(
        cls,
        value: str,
    ) -> str:
        if not value.strip():
            raise ValueError(
                "Java source code cannot be empty."
            )

        return value

    @field_validator("methodName")
    @classmethod
    def validate_method_name(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if not value:
            return None

        if not METHOD_NAME_PATTERN.fullmatch(
            value
        ):
            raise ValueError(
                "Method name must be a valid Java identifier."
            )

        return value


# ============================================================
# Basic in-process rate limiter
#
# This is useful for development and a simple single-instance
# deployment.
#
# For the final public site, we should still use provider-level
# rate limiting too.
# ============================================================

_rate_limit_store: dict[
    str,
    deque[float],
] = defaultdict(deque)

_rate_limit_lock = Lock()


def _client_identifier(
    request: Request,
) -> str:
    """
    Obtain a basic identifier for rate limiting.

    Behind a hosting proxy, X-Forwarded-For may contain the
    original client address.

    For local development, request.client.host is used.
    """

    forwarded = request.headers.get(
        "x-forwarded-for"
    )

    if forwarded:
        return (
            forwarded
            .split(",")[0]
            .strip()
        )

    if request.client:
        return request.client.host

    return "unknown"


def _check_rate_limit(
    request: Request,
) -> None:
    client = _client_identifier(
        request
    )

    now = time.monotonic()

    cutoff = (
        now
        -
        RATE_LIMIT_WINDOW_SECONDS
    )

    with _rate_limit_lock:
        requests = (
            _rate_limit_store[
                client
            ]
        )

        while (
            requests
            and
            requests[0] < cutoff
        ):
            requests.popleft()

        if (
            len(requests)
            >= RATE_LIMIT_REQUESTS
        ):
            raise HTTPException(
                status_code=429,
                detail=(
                    "Too many execution requests. "
                    "Please wait a moment and try again."
                ),
            )

        requests.append(now)


# ============================================================
# Middleware
# ============================================================

@app.middleware("http")
async def security_middleware(
    request: Request,
    call_next,
):
    """
    Apply request-size and browser security protections.

    This does not replace the Java execution sandbox.
    """

    content_length = (
        request.headers.get(
            "content-length"
        )
    )

    if content_length:
        try:
            size = int(
                content_length
            )

        except ValueError:
            return JSONResponse(
                status_code=400,
                content={
                    "detail":
                        "Invalid Content-Length header."
                },
            )

        if (
            size
            >
            MAX_REQUEST_BYTES
        ):
            return JSONResponse(
                status_code=413,
                content={
                    "detail":
                        "Request is too large."
                },
            )

    response = await call_next(
        request
    )

    response.headers[
        "X-Content-Type-Options"
    ] = "nosniff"

    response.headers[
        "X-Frame-Options"
    ] = "DENY"

    response.headers[
        "Referrer-Policy"
    ] = "same-origin"

    response.headers[
        "Permissions-Policy"
    ] = (
        "camera=(), "
        "microphone=(), "
        "geolocation=()"
    )

    return response


# ============================================================
# Health endpoints
# ============================================================

@app.get("/health")
@app.get("/api/health")
def health():
    return {
        "ok": True,
        "service":
            "java-sorting-visualizer",
        "environment":
            APP_ENV,
    }


# ============================================================
# Execution endpoint
# ============================================================

@app.post("/api/execute")
def execute(
    req: ExecuteRequest,
    request: Request,
):
    _check_rate_limit(
        request
    )

    try:
        result = execute_java(
            req.code,
            req.inputArray,
            req.methodName,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        # Development mode should expose unexpected errors
        # so we can debug them locally.
        if not IS_PRODUCTION:
            raise

        # Production mode intentionally hides Python/backend
        # implementation details from public users.
        raise HTTPException(
            status_code=500,
            detail=(
                "The execution service encountered "
                "an internal error."
            ),
        ) from exc

    return _prepare_public_result(
        result
    )


# ============================================================
# Public response filtering
# ============================================================

def _prepare_public_result(
    result: dict,
) -> dict:
    """
    Remove development-only backend details when running
    publicly.

    Student Java compile/runtime errors should still be shown.
    Internal instrumentation failures should not reveal paths
    or implementation details.
    """

    if not IS_PRODUCTION:
        return result

    cleaned = dict(
        result
    )

    trace_note = cleaned.get(
        "traceNote"
    )

    if (
        trace_note
        and
        "Instrumentation compiler error:"
        in trace_note
    ):
        cleaned[
            "traceNote"
        ] = (
            "Your Java program executed successfully, "
            "but intermediate visualization was not "
            "available for this source structure."
        )

    return cleaned


# ============================================================
# Static frontend
# ============================================================

app.mount(
    "/static",
    StaticFiles(
        directory=STATIC
    ),
    name="static",
)


@app.get("/")
def root():
    return FileResponse(
        STATIC / "index.html"
    )


@app.get("/{path:path}")
def static_fallback(
    path: str,
):
    """
    Serve frontend files while preventing traversal outside
    the static directory.

    For example:
        ../../runner.py

    must never be accessible from the web.
    """

    static_root = (
        STATIC.resolve()
    )

    candidate = (
        STATIC / path
    ).resolve()

    if (
        candidate
        !=
        static_root
        and
        static_root
        not in
        candidate.parents
    ):
        raise HTTPException(
            status_code=404,
            detail="Not found.",
        )

    if (
        candidate.exists()
        and
        candidate.is_file()
    ):
        return FileResponse(
            candidate
        )

    return FileResponse(
        STATIC / "index.html"
    )

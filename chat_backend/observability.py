"""Structured request logging (gap O5).

Stdlib-only JSON lines on stdout — one JSON object per log record — plus a
request-id middleware: every HTTP request gets an `X-Request-ID` (honoured
when the client sends a sane one, generated otherwise), the id is echoed in
the response header, attached to every log line emitted while handling the
request, and returned in the 500 body so a user report can be matched to a
log line without needing an error-tracking vendor.

Sentry/OpenTelemetry is deliberately not wired in yet: there is no
deployment target to send events to (open question U7).
"""
import json
import logging
import re
import sys
import time
import uuid
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

REQUEST_ID_HEADER = "X-Request-ID"

# What we accept back from a client as its request id: short, header-safe,
# printable. Anything else is replaced by a generated one so a client cannot
# inject newlines or oversized payloads into the log stream.
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Probe endpoints are frequent and uninteresting at INFO; they still emit a
# JSON line, just at DEBUG so normal runs are not drowned in health checks.
_HEALTH_PATHS = frozenset({"/health", "/health/ready"})

# Attributes every LogRecord already carries; anything else on the record
# came in through `extra=` and belongs in the JSON payload.
_PROTOTYPE_RECORD = logging.LogRecord(
    name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
)
_STANDARD_ATTRS = frozenset(_PROTOTYPE_RECORD.__dict__) | {"message", "asctime"}

access_logger = logging.getLogger("chat_backend.access")


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single JSON object on one line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # `default=str` keeps an unserialisable extra from crashing logging.
        return json.dumps(payload, ensure_ascii=False, default=str)


class JsonHandler(logging.StreamHandler):
    """The single handler `setup_logging` owns; the subclass is its marker."""


def setup_logging(level: int = logging.INFO) -> None:
    """Attach one JSON handler to the root logger; idempotent.

    Records keep propagating to the root logger (so pytest's `caplog` and any
    host-level handler still see them); we only add our handler if it is not
    there yet, and we never remove handlers we do not own.
    """
    root = logging.getLogger()
    if not any(isinstance(handler, JsonHandler) for handler in root.handlers):
        handler = JsonHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    root.setLevel(level)


def resolve_request_id(candidate: str | None) -> str:
    """Use the client's id when it is safe, otherwise mint a fresh one."""
    if candidate and _REQUEST_ID_PATTERN.match(candidate):
        return candidate
    return uuid.uuid4().hex


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Tag every request with an id, echo it back, and log one JSON line."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Re-raised for Starlette's error middleware; the traceback itself
            # is logged by the exception handler in main.py, correlated by id.
            access_logger.error(
                "request failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
            raise
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers[REQUEST_ID_HEADER] = request_id
        level = logging.DEBUG if request.url.path in _HEALTH_PATHS else logging.INFO
        access_logger.log(
            level,
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

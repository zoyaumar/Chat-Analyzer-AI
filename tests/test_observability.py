"""Tests for the structured-logging layer (gap O5): JSON lines + X-Request-ID."""
import json
import logging
import re
import sys

from httpx import AsyncClient

from chat_backend.observability import (
    JsonFormatter,
    setup_logging,
)

_HEX_32 = re.compile(r"^[0-9a-f]{32}$")


def test_json_formatter_emits_one_json_object_with_extras():
    record = logging.LogRecord(
        name="chat_backend.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=12,
        msg="boom %s",
        args=("now",),
        exc_info=None,
    )
    record.request_id = "abc123"
    record.status = 200

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "WARNING"
    assert payload["logger"] == "chat_backend.test"
    assert payload["msg"] == "boom now"
    assert payload["request_id"] == "abc123"
    assert payload["status"] == 200
    assert payload["ts"].endswith("Z")


def test_json_formatter_includes_the_traceback():
    try:
        raise ValueError("kaboom")
    except ValueError:
        record = logging.LogRecord(
            name="chat_backend.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=30,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    payload = json.loads(JsonFormatter().format(record))

    assert "ValueError: kaboom" in payload["exception"]


def test_setup_logging_is_idempotent():
    from chat_backend.observability import JsonHandler

    def owned_handlers():
        return [h for h in logging.getLogger().handlers if isinstance(h, JsonHandler)]

    before = len(owned_handlers())
    setup_logging()
    setup_logging()
    assert len(owned_handlers()) == before
    assert before >= 1  # main.py already called it at import time


async def test_request_id_is_generated_and_echoed(client: AsyncClient):
    resp = await client.get("/health")

    request_id = resp.headers.get("X-Request-ID")
    assert request_id is not None
    assert _HEX_32.match(request_id)


async def test_a_client_supplied_request_id_is_echoed_back(client: AsyncClient):
    resp = await client.get("/health", headers={"X-Request-ID": "client-supplied-1"})

    assert resp.headers["X-Request-ID"] == "client-supplied-1"


async def test_an_unsafe_client_request_id_is_replaced(client: AsyncClient):
    # Header-safe but not id-safe (spaces): accepted by the transport,
    # rejected by resolve_request_id so it can never reach the log stream.
    resp = await client.get("/health", headers={"X-Request-ID": "bad id with spaces"})

    request_id = resp.headers["X-Request-ID"]
    assert request_id != "bad id with spaces"
    assert _HEX_32.match(request_id)


async def test_access_log_line_carries_the_request_id(client: AsyncClient, caplog):
    with caplog.at_level(logging.INFO, logger="chat_backend.access"):
        resp = await client.get("/")

    request_id = resp.headers["X-Request-ID"]
    records = [
        r
        for r in caplog.records
        if r.name == "chat_backend.access" and getattr(r, "request_id", None) == request_id
    ]
    assert records, "expected one access log record for this request id"
    record = records[-1]
    assert record.method == "GET"
    assert record.path == "/"
    assert record.status == 200
    assert isinstance(record.duration_ms, float)


async def test_health_probes_log_at_debug_not_info(client: AsyncClient, caplog):
    with caplog.at_level(logging.DEBUG, logger="chat_backend.access"):
        resp = await client.get("/health")

    request_id = resp.headers["X-Request-ID"]
    records = [
        r
        for r in caplog.records
        if r.name == "chat_backend.access" and getattr(r, "request_id", None) == request_id
    ]
    assert records
    assert records[-1].levelno == logging.DEBUG

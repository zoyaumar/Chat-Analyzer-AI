"""Graceful degradation when the AI layer is down (gap A6).

The API stays up, chat keeps working, and the two analytics endpoints that
genuinely need a model answer `503` with a readable reason instead of a `500`.
"""
from chat_backend import ai_utils
from chat_backend.ai_utils import ModelUnavailableError


def _unavailable(text: str) -> dict:
    raise ModelUnavailableError("sentiment-analysis model failed to load: no network")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_sentiment_endpoint_returns_503_when_the_model_is_unavailable(
    client, user_and_token, monkeypatch
):
    from chat_backend.routes import analytics

    _, _, token = user_and_token
    monkeypatch.setattr(analytics, "analyze_sentiment", _unavailable)

    response = await client.post(
        "/analytics/sentiment", json={"text": "hi"}, headers=_auth(token)
    )

    assert response.status_code == 503
    assert "failed to load" in response.json()["detail"]


async def test_daily_summary_returns_503_when_the_model_is_unavailable(
    client, user_and_token, monkeypatch
):
    from chat_backend.routes import analytics

    _, _, token = user_and_token
    await client.post("/messages/", json={"text": "today"}, headers=_auth(token))
    monkeypatch.setattr(analytics, "summarize_text", _unavailable)

    response = await client.get("/analytics/daily", headers=_auth(token))

    assert response.status_code == 503
    assert "failed to load" in response.json()["detail"]


async def test_chat_survives_the_ai_layer_being_down(client, user_and_token, monkeypatch):
    """Sending, listing and deleting a message never touch a model (gap A6)."""

    _, _, token = user_and_token
    monkeypatch.setattr(ai_utils, "analyze_sentiment", _unavailable)

    created = await client.post("/messages/", json={"text": "chat works"}, headers=_auth(token))
    listed = await client.get("/messages/", headers=_auth(token))
    removed = await client.delete(
        f"/messages/{created.json()['id']}", headers=_auth(token)
    )

    assert created.status_code == 200
    assert [m["text"] for m in listed.json()] == ["chat works"]
    assert removed.status_code == 200


async def test_daily_summary_does_not_block_the_event_loop(
    client, user_and_token, monkeypatch
):
    """A slow summary must not stall other requests (gap N1).

    `summarize_text` used to be called straight from an `async def` route, so
    the blocking model call ran on the event loop: while one user waited for
    their daily summary, *nothing else on the worker* could be served — not a
    message send, not the health probe. This is the regression test for the
    `await asyncio.to_thread(...)` in the route.
    """
    import asyncio
    import time

    from chat_backend.routes import analytics

    _, _, token = user_and_token
    await client.post("/messages/", json={"text": "today"}, headers=_auth(token))

    started = asyncio.Event()

    def slow_summary(text: str) -> str:
        # Signals that the summary is running, then blocks the *thread* it was
        # given. If it were on the event loop, the probe below could never run
        # and this test would time out rather than fail cleanly.
        started.set()
        time.sleep(0.75)
        return "a summary"

    monkeypatch.setattr(analytics, "summarize_text", slow_summary)

    summary_task = asyncio.create_task(
        client.get("/analytics/daily", headers=_auth(token))
    )
    # Wait for the summary to be genuinely in flight...
    for _ in range(50):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set(), "the summary never started"

    # ...and prove the loop is still free to serve an unrelated request.
    probe = await asyncio.wait_for(client.get("/health/ready"), timeout=2.0)
    assert probe.status_code == 200

    assert (await asyncio.wait_for(summary_task, timeout=5.0)).status_code == 200


async def test_daily_summary_still_503s_when_the_model_is_unavailable(
    client, user_and_token, monkeypatch
):
    """The `to_thread` hop must not swallow `ModelUnavailableError` (gap N1)."""
    from chat_backend.routes import analytics

    _, _, token = user_and_token
    await client.post("/messages/", json={"text": "today"}, headers=_auth(token))
    monkeypatch.setattr(analytics, "summarize_text", _unavailable)

    response = await client.get("/analytics/daily", headers=_auth(token))

    assert response.status_code == 503
    assert "failed to load" in response.json()["detail"]


def test_warmup_reports_each_capability_and_never_raises(monkeypatch):
    """`ai_utils.warmup` loads both pipelines and swallows per-model failures."""
    from chat_backend import ai_utils

    calls = []
    monkeypatch.setattr(ai_utils, "_sentiment_pipeline", lambda: calls.append("sentiment"))
    monkeypatch.setattr(ai_utils, "_summarizer", lambda: calls.append("summary"))

    assert ai_utils.warmup() == {"sentiment": "ready", "summary": "ready"}
    assert sorted(calls) == ["sentiment", "summary"]


def test_warmup_marks_a_failing_capability_failed_and_keeps_going(monkeypatch):
    """One broken model must not stop the other, or the caller, from finishing."""
    from chat_backend import ai_utils

    def boom():
        raise ModelUnavailableError("no network")

    monkeypatch.setattr(ai_utils, "_sentiment_pipeline", boom)
    monkeypatch.setattr(ai_utils, "_summarizer", lambda: None)

    assert ai_utils.warmup() == {"sentiment": "failed", "summary": "ready"}


def test_warmup_is_off_by_default():
    """`AI_WARMUP_ON_STARTUP` defaults off, so tests never pay a model load."""
    from chat_backend.config import Settings

    assert Settings.model_fields["ai_warmup_on_startup"].default is False

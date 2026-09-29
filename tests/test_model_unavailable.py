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
from unittest.mock import patch

from httpx import AsyncClient


async def test_analytics_sentiment(client: AsyncClient, user_and_token):
    _, _, token = user_and_token
    fake = {"label": "POSITIVE", "score": 0.99}
    with patch("chat_backend.routes.analytics.analyze_sentiment", return_value=fake):
        resp = await client.post(
            "/analytics/sentiment",
            json={"text": "I love this"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    assert resp.json() == fake


async def test_analytics_sentiment_requires_token(client: AsyncClient):
    assert (
        await client.post("/analytics/sentiment", json={"text": "hi"})
    ).status_code == 401


async def test_daily_summary_scoped_to_user(client: AsyncClient):
    await client.post("/users/register", json={"username": "a1", "password": "pw123456"})
    t1 = (await client.post("/users/login", data={"username": "a1", "password": "pw123456"})).json()["access_token"]
    await client.post("/users/register", json={"username": "a2", "password": "pw123456"})
    t2 = (await client.post("/users/login", data={"username": "a2", "password": "pw123456"})).json()["access_token"]

    await client.post("/messages/", json={"text": "secret one"}, headers={"Authorization": f"Bearer {t1}"})
    await client.post("/messages/", json={"text": "secret two"}, headers={"Authorization": f"Bearer {t2}"})

    with patch("chat_backend.routes.analytics.summarize_text", side_effect=lambda t: t):
        resp = await client.get(
            "/analytics/daily", headers={"Authorization": f"Bearer {t1}"}
        )
    assert resp.status_code == 200
    # a1's summary must contain only a1's text, never a2's.
    assert "secret one" in resp.json()["summary"]
    assert "secret two" not in resp.json()["summary"]


async def test_daily_summary_requires_token(client: AsyncClient):
    assert (await client.get("/analytics/daily")).status_code == 401
"""Sentiment is persisted with the message it belongs to.

Scoring happens in `crud.create_message`, the one write path both transports
share — these tests go through the HTTP API and through `crud`
directly, which is what the socket handler uses.
"""
from sqlalchemy import select

from chat_backend import ai_utils, crud, models


async def _send(client, token: str, text: str):
    return await client.post(
        "/messages/", json={"text": text}, headers={"Authorization": f"Bearer {token}"}
    )


async def test_a_message_is_scored_once_at_write_time(client, user_and_token, db_session):
    _, _, token = user_and_token

    response = await _send(client, token, "I really love this")

    assert response.status_code == 200
    rows = (await db_session.execute(select(models.MessageSentiment))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.message_id == response.json()["id"]
    assert (row.label, row.score) == ("POSITIVE", 0.99)
    # Provenance travels with the score, so a model upgrade stays auditable.
    assert (row.model_name, row.model_version) == ("test-model", "test-revision")
    assert row.created_at is not None


async def test_the_shared_write_path_scores_socket_messages_too(
    client, db_session, user_and_token
):
    """The socket handler calls `crud.create_message`, so it scores as well."""
    _, _, token = user_and_token
    user_id = (
        await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    ).json()["id"]

    message = await crud.create_message(db_session, user_id=user_id, text="over the wire")

    row = (
        await db_session.execute(
            select(models.MessageSentiment).where(
                models.MessageSentiment.message_id == message.id
            )
        )
    ).scalars().one()
    assert row.label == "POSITIVE"


async def test_a_scoring_failure_never_costs_the_message(
    client, user_and_token, db_session, monkeypatch
):
    """Chat must work with the AI layer down: only the score is lost."""
    _, _, token = user_and_token

    def explode(text: str) -> dict:
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(ai_utils, "analyze_sentiment", explode)

    response = await _send(client, token, "still my message")

    assert response.status_code == 200
    listed = await client.get("/messages/", headers={"Authorization": f"Bearer {token}"})
    assert [m["text"] for m in listed.json()] == ["still my message"]
    assert (await db_session.execute(select(models.MessageSentiment))).scalars().all() == []


async def test_the_timeline_reads_the_stored_score_without_running_inference(
    client, user_and_token, monkeypatch
):
    """The analytics read path is a lookup, not inference."""
    _, _, token = user_and_token
    headers = {"Authorization": f"Bearer {token}"}
    await _send(client, token, "scored once at write time")

    def explode(text: str) -> dict:
        raise AssertionError("a read path must not run inference")

    monkeypatch.setattr(ai_utils, "analyze_sentiment", explode)

    timeline = await client.get("/analytics/sentiment/timeline", headers=headers)

    assert timeline.status_code == 200
    assert timeline.json()["timeline"][0]["avg_score"] == 0.99
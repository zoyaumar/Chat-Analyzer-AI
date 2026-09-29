"""`GET /analytics/sentiment/timeline` — sentiment over time (gap A3).

A read-only aggregate over the stored scores (gap A4), grouped by UTC day (D7)
and scoped to the caller (S3).
"""
from datetime import datetime, timedelta, timezone

from chat_backend import models


async def test_timeline_requires_token(client):
    assert (await client.get("/analytics/sentiment/timeline")).status_code == 401


async def test_timeline_is_empty_for_a_user_without_messages(client, user_and_token):
    _, _, token = user_and_token

    response = await client.get(
        "/analytics/sentiment/timeline",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    # Empty, not 404: "no activity in this window" is a valid answer to a trend query.
    assert response.json() == {"days": 30, "timeline": []}


async def test_timeline_aggregates_by_utc_day_and_only_for_the_caller(
    client, user_and_token, db_session
):
    _, _, token = user_and_token
    headers = {"Authorization": f"Bearer {token}"}
    user_id = (await client.get("/users/me", headers=headers)).json()["id"]
    now = datetime.now(timezone.utc)
    older_day = now - timedelta(days=3, hours=1)

    other = models.User(username="someone-else", password_hash="x")
    db_session.add(other)
    await db_session.flush()
    db_session.add_all(
        [
            models.Message(id=1, user_id=user_id, text="positive", timestamp=now),
            models.Message(id=2, user_id=user_id, text="negative", timestamp=now),
            # Never scored (the model was down, gap A6): counted, not averaged.
            models.Message(id=3, user_id=user_id, text="unscored", timestamp=now),
            models.Message(id=4, user_id=user_id, text="older", timestamp=older_day),
            models.Message(id=5, user_id=other.id, text="not mine", timestamp=now),
        ]
    )
    db_session.add_all(
        [
            models.MessageSentiment(
                message_id=1, label="POSITIVE", score=0.9, model_name="m", model_version="v1"
            ),
            models.MessageSentiment(
                message_id=2, label="NEGATIVE", score=0.4, model_name="m", model_version="v1"
            ),
            models.MessageSentiment(
                message_id=4, label="POSITIVE", score=0.5, model_name="m", model_version="v1"
            ),
            models.MessageSentiment(
                message_id=5, label="NEGATIVE", score=0.1, model_name="m", model_version="v1"
            ),
        ]
    )
    await db_session.commit()

    response = await client.get("/analytics/sentiment/timeline?days=7", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 7
    # Oldest day first, one entry per day that has activity, nothing about the other user.
    assert body["timeline"] == [
        {
            "date": older_day.date().isoformat(),
            "messages": 1,
            "positive": 1,
            "negative": 0,
            "avg_score": 0.5,
        },
        {
            "date": now.date().isoformat(),
            "messages": 3,
            "positive": 1,
            "negative": 1,
            "avg_score": 0.65,
        },
    ]


async def test_timeline_ignores_days_outside_the_window(client, user_and_token, db_session):
    _, _, token = user_and_token
    headers = {"Authorization": f"Bearer {token}"}
    user_id = (await client.get("/users/me", headers=headers)).json()["id"]
    long_ago = datetime.now(timezone.utc) - timedelta(days=10)

    db_session.add(models.Message(id=1, user_id=user_id, text="old news", timestamp=long_ago))
    await db_session.flush()
    db_session.add(
        models.MessageSentiment(
            message_id=1, label="NEGATIVE", score=0.2, model_name="m", model_version="v1"
        )
    )
    await db_session.commit()

    response = await client.get("/analytics/sentiment/timeline?days=7", headers=headers)

    assert response.json() == {"days": 7, "timeline": []}


async def test_timeline_rejects_an_out_of_range_window(client, user_and_token):
    _, _, token = user_and_token
    headers = {"Authorization": f"Bearer {token}"}

    for days in ("0", "366"):
        response = await client.get(
            f"/analytics/sentiment/timeline?days={days}", headers=headers
        )
        assert response.status_code == 422
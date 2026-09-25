"""Account deletion: the endpoint, the cascade, and the dead token (gap D4)."""
from httpx import AsyncClient
from sqlalchemy import func, select

from chat_backend import models


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_delete_me_requires_a_valid_token(client: AsyncClient):
    assert (await client.delete("/users/me")).status_code == 401
    resp = await client.delete("/users/me", headers=_auth("not-a-token"))
    assert resp.status_code == 401


async def test_delete_me_removes_the_account_its_messages_and_the_token(
    client: AsyncClient, user_and_token, db_session
):
    _, _, token = user_and_token
    me = (await client.get("/users/me", headers=_auth(token))).json()
    created = await client.post(
        "/messages/", json={"text": "goodbye"}, headers=_auth(token)
    )
    assert created.status_code == 200

    resp = await client.delete("/users/me", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"detail": "Account deleted"}

    # The row and everything that pointed at it are gone (ON DELETE CASCADE,
    # exercised through the real schema the fixtures created from models.py).
    assert await db_session.get(models.User, me["id"]) is None
    remaining = await db_session.scalar(
        select(func.count())
        .select_from(models.Message)
        .where(models.Message.user_id == me["id"])
    )
    assert remaining == 0

    # The issued token dies with the account: get_current_user finds no user.
    assert (await client.get("/users/me", headers=_auth(token))).status_code == 401

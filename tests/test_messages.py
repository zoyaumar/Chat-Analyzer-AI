from httpx import AsyncClient


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_create_and_list_messages(client: AsyncClient, user_and_token):
    _, _, token = user_and_token

    resp = await client.post("/messages/", json={"text": "hello"}, headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["text"] == "hello"

    me = (await client.get("/users/me", headers=_auth(token))).json()
    assert resp.json()["user_id"] == me["id"]

    resp = await client.get("/messages/", headers=_auth(token))
    assert resp.status_code == 200
    assert [m["text"] for m in resp.json()] == ["hello"]


async def test_messages_require_token(client: AsyncClient, user_and_token):
    assert (await client.get("/messages/")).status_code == 401
    assert (await client.post("/messages/", json={"text": "x"})).status_code == 401


async def test_messages_reject_oversized_text(client: AsyncClient, user_and_token):
    _, _, token = user_and_token
    response = await client.post(
        "/messages/", json={"text": "x" * 4001}, headers=_auth(token)
    )
    assert response.status_code == 422


async def test_messages_scoped_to_sender(client: AsyncClient):
    # Two users; each must only ever see their own messages.
    await client.post("/users/register", json={"username": "u1", "password": "pw123456"})
    t1 = (await client.post("/users/login", data={"username": "u1", "password": "pw123456"})).json()["access_token"]
    await client.post("/users/register", json={"username": "u2", "password": "pw123456"})
    t2 = (await client.post("/users/login", data={"username": "u2", "password": "pw123456"})).json()["access_token"]

    await client.post("/messages/", json={"text": "from u1"}, headers=_auth(t1))
    await client.post("/messages/", json={"text": "from u2"}, headers=_auth(t2))

    msgs1 = (await client.get("/messages/", headers=_auth(t1))).json()
    msgs2 = (await client.get("/messages/", headers=_auth(t2))).json()
    assert [m["text"] for m in msgs1] == ["from u1"]
    assert [m["text"] for m in msgs2] == ["from u2"]


async def test_delete_message_ownership(client: AsyncClient, user_and_token):
    _, _, token = user_and_token
    mid = (
        await client.post("/messages/", json={"text": "mine"}, headers=_auth(token))
    ).json()["id"]

    # Another user cannot delete it.
    await client.post("/users/register", json={"username": "mallory", "password": "pw123456"})
    t_other = (await client.post("/users/login", data={"username": "mallory", "password": "pw123456"})).json()["access_token"]
    resp = await client.delete(f"/messages/{mid}", headers=_auth(t_other))
    assert resp.status_code == 404

    # The owner can.
    resp = await client.delete(f"/messages/{mid}", headers=_auth(token))
    assert resp.status_code == 200
    assert (await client.get("/messages/", headers=_auth(token))).json() == []


async def test_messages_validate_pagination_parameters(client: AsyncClient, user_and_token):
    _, _, token = user_and_token
    for params, expected_status in (
        ({"limit": 0}, 422),
        ({"limit": 101}, 422),
        ({"before": "2026-01-01T00:00:00Z"}, 400),
    ):
        response = await client.get(
            "/messages/", params=params, headers=_auth(token)
        )
        assert response.status_code == expected_status


async def test_messages_use_keyset_cursor_for_older_pages(client: AsyncClient, user_and_token):
    _, _, token = user_and_token
    for text in ("first", "second", "third", "fourth"):
        response = await client.post(
            "/messages/", json={"text": text}, headers=_auth(token)
        )
        assert response.status_code == 200

    newest_page = await client.get(
        "/messages/", params={"limit": 2}, headers=_auth(token)
    )
    assert newest_page.status_code == 200
    assert [message["text"] for message in newest_page.json()] == ["third", "fourth"]

    oldest = newest_page.json()[0]
    older_page = await client.get(
        "/messages/",
        params={"limit": 2, "before": oldest["timestamp"], "before_id": oldest["id"]},
        headers=_auth(token),
    )
    assert older_page.status_code == 200
    assert [message["text"] for message in older_page.json()] == ["first", "second"]

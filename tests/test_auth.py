from httpx import AsyncClient


async def test_register_and_login(client: AsyncClient):
    resp = await client.post(
        "/users/register", json={"username": "bob", "password": "pw123456"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "bob"
    assert "password" not in body and "password_hash" not in body

    resp = await client.post(
        "/users/login", data={"username": "bob", "password": "pw123456"}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_register_duplicate_username(client: AsyncClient):
    payload = {"username": "carol", "password": "pw123456"}
    assert (await client.post("/users/register", json=payload)).status_code == 200
    resp = await client.post("/users/register", json=payload)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Username already registered"


async def test_login_wrong_password(client: AsyncClient):
    await client.post("/users/register", json={"username": "dave", "password": "right"})
    resp = await client.post("/users/login", data={"username": "dave", "password": "wrong"})
    assert resp.status_code == 401


async def test_users_me_returns_profile(client: AsyncClient, user_and_token):
    username, _, token = user_and_token
    resp = await client.get(
        "/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == username
    assert isinstance(body["id"], int)


async def test_users_me_requires_token(client: AsyncClient):
    assert (await client.get("/users/me")).status_code == 401
    resp = await client.get("/users/me", headers={"Authorization": "Bearer not-a-token"})
    assert resp.status_code == 401
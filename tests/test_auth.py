from httpx import AsyncClient

from chat_backend import models
from chat_backend.auth_utils import create_access_token


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
    await client.post("/users/register", json={"username": "dave", "password": "rightpass"})
    resp = await client.post("/users/login", data={"username": "dave", "password": "wrongpass"})
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


# --- Credential policy (gap S6) -------------------------------------------
# Registration used to accept a one-character username and any password at all.
# Each of these is a `422` naming the field that failed, so a client can show a
# useful message instead of a generic failure.


async def _register_error(client: AsyncClient, payload: dict) -> dict:
    """Register `payload`; assert the `422` and return the offending field."""
    response = await client.post("/users/register", json=payload)
    assert response.status_code == 422, response.text
    details = response.json()["detail"]
    assert len(details) == 1, details
    return details[0]


async def test_a_short_password_is_rejected(client: AsyncClient):
    error = await _register_error(client, {"username": "alice", "password": "short"})

    assert error["loc"] == ["body", "password"]


async def test_a_short_username_is_rejected(client: AsyncClient):
    error = await _register_error(client, {"username": "ab", "password": "pw123456"})

    assert error["loc"] == ["body", "username"]


async def test_a_username_outside_the_pattern_is_rejected(client: AsyncClient):
    for username in ("bob smith", "bob@example.com", "bob/smith"):
        error = await _register_error(client, {"username": username, "password": "pw123456"})
        assert error["loc"] == ["body", "username"], username


async def test_a_long_username_is_rejected(client: AsyncClient):
    error = await _register_error(client, {"username": "a" * 33, "password": "pw123456"})

    assert error["loc"] == ["body", "username"]


async def test_a_password_bcrypt_would_truncate_is_rejected(client: AsyncClient):
    """bcrypt hashes at most 72 bytes and passlib drops the rest without complaining.

    Left alone, `"x" * 80` and `"x" * 72 + "yyyyyyyy"` are the same credential
    (reproduced against passlib 1.7.4 + bcrypt 4.0.1).
    """
    error = await _register_error(client, {"username": "alice", "password": "x" * 73})

    assert error["loc"] == ["body", "password"]


async def test_the_password_cap_counts_bytes_not_characters(client: AsyncClient):
    """20 four-byte emoji are 80 bytes in only 20 characters — still too long."""
    error = await _register_error(client, {"username": "alice", "password": "\U0001f600" * 20})

    assert error["loc"] == ["body", "password"]


async def test_a_password_of_exactly_the_cap_is_accepted(client: AsyncClient):
    """The boundary itself is legal — the rule rejects only what would be cut."""
    response = await client.post(
        "/users/register", json={"username": "alice", "password": "x" * 72}
    )

    assert response.status_code == 200


async def test_the_policy_does_not_apply_to_login(client: AsyncClient):
    """Login keeps its own contract: bad credentials are `401`, never `422`."""
    await client.post("/users/register", json={"username": "alice", "password": "pw123456"})

    response = await client.post("/users/login", data={"username": "alice", "password": "short"})

    assert response.status_code == 401


async def test_an_account_that_predates_the_policy_still_serialises(client, db_session):
    """The bounds sit on `UserCreate`, never on `UserOut` (gap S6).

    A one-character name is no longer registrable, but it may already exist, and
    reading it must not become a 500 because a response model tightened after
    the fact.
    """
    legacy = models.User(username="a", password_hash="not-a-real-hash")
    db_session.add(legacy)
    await db_session.commit()

    response = await client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {create_access_token({'sub': str(legacy.id)})}"},
    )

    assert response.status_code == 200
    assert response.json()["username"] == "a"

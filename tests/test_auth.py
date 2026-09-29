import bcrypt
from httpx import AsyncClient
from sqlalchemy import select

from chat_backend import auth_utils, models
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


# --- Password hashing (gap S10) ---------------------------------------------
# `passlib` (last released 2020) is replaced by `pwdlib`: argon2id writes every
# new hash and bcrypt stays in the hasher list only so accounts written before
# the migration still open. The tests below are the proof the migration
# invalidated nobody, and that every way a stored hash can be unusable answers
# with a credential failure instead of a server error.


def _bcrypt_hash(password: str) -> str:
    """A hash exactly as the pre-S10 app wrote one (passlib over bcrypt)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


async def _insert_legacy_user(
    db_session, username: str, password: str
) -> models.User:
    """Insert an account whose hash predates argon2 becoming the active hasher."""
    user = models.User(username=username, password_hash=_bcrypt_hash(password))
    db_session.add(user)
    await db_session.commit()
    return user


async def test_a_hash_written_before_the_migration_still_logs_in(
    client: AsyncClient, db_session
):
    """Keeping bcrypt as a *verifier* is the whole point of the hasher list."""
    await _insert_legacy_user(db_session, "grandma", "pw123456")

    response = await client.post(
        "/users/login", data={"username": "grandma", "password": "pw123456"}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_the_login_that_proves_an_old_hash_rewrites_it(
    client: AsyncClient, db_session
):
    """Rehash on login: the successful password entry *is* the migration step.

    No backfill script and no lockout window — the account upgrades itself, and
    because the replacement already came from argon2 the next login has nothing
    left to rewrite.
    """
    user = await _insert_legacy_user(db_session, "grandma", "pw123456")

    assert (
        await client.post(
            "/users/login", data={"username": "grandma", "password": "pw123456"}
        )
    ).status_code == 200
    await db_session.refresh(user)
    assert user.password_hash.startswith("$argon2id$")
    assert auth_utils.verify_and_rehash("pw123456", user.password_hash) == (True, None)


async def test_a_new_account_is_hashed_with_argon2(client: AsyncClient, db_session):
    """Registration never writes bcrypt again (gap S10, decided in Q6)."""
    assert (
        await client.post(
            "/users/register", json={"username": "newbie", "password": "pw123456"}
        )
    ).status_code == 200

    stored = (
        (await db_session.execute(select(models.User).where(models.User.username == "newbie")))
        .scalars()
        .one()
    )
    assert stored.password_hash.startswith("$argon2id$")
    assert auth_utils.verify_password("pw123456", stored.password_hash)


async def test_a_password_the_legacy_hasher_refuses_is_a_401_not_a_500(
    client: AsyncClient, db_session
):
    """bcrypt >= 4.1 raises `ValueError` past 72 bytes instead of truncating.

    The registration policy (S6) keeps new passwords inside that limit, so the
    only way to reach this is a hash written *before* the policy existed — and
    an unusable credential must still be a `401`, never a crash in the route.
    """
    await _insert_legacy_user(db_session, "longshot", "x" * 72)

    response = await client.post(
        "/users/login", data={"username": "longshot", "password": "x" * 80}
    )

    assert response.status_code == 401


async def test_an_unreadable_stored_hash_is_a_401_not_a_500(
    client: AsyncClient, db_session
):
    """A hash naming a hasher this install does not have is not a credential."""
    db_session.add(
        models.User(username="corrupt", password_hash="definitely-not-a-hash")
    )
    await db_session.commit()

    response = await client.post(
        "/users/login", data={"username": "corrupt", "password": "pw123456"}
    )

    assert response.status_code == 401


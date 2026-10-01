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


# --- Credential policy ----------------------------------------------------
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
    """The bounds sit on `UserCreate`, never on `UserOut`.

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


# --- Password hashing -------------------------------------------------------
# `passlib` (last released 2020) is replaced by `pwdlib`: argon2id writes every
# new hash and bcrypt stays in the hasher list only so accounts written before
# the migration still open. The tests below are the proof the migration
# invalidated nobody, and that every way a stored hash can be unusable answers
# with a credential failure instead of a server error.


def _bcrypt_hash(password: str) -> str:
    """A hash as the app wrote one before argon2 (passlib over bcrypt)."""
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
    """Registration never writes bcrypt again."""
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
    """bcrypt 5.0.0 raises `ValueError` past 72 bytes instead of truncating.

    The registration policy keeps new passwords inside that limit, so the
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


# --- Refresh tokens, logout & the origin guard -----------------------------
# The session is now two halves: a short-lived access token in the body (held
# in memory by the SPA) and a rotating refresh token in an HttpOnly cookie,
# stored hashed in `refresh_tokens` so it can be revoked server-side.


def _refresh_cookie_header(response) -> str:
    """The `Set-Cookie` line for the refresh token, or a failing assertion."""
    for header in response.headers.get_list("set-cookie"):
        if header.startswith("refresh_token="):
            return header
    raise AssertionError(
        f"no refresh_token cookie in {response.headers.get_list('set-cookie')}"
    )


async def _login(client: AsyncClient, username: str, password: str):
    return await client.post(
        "/users/login", data={"username": username, "password": password}
    )


async def test_login_sets_an_httponly_strict_refresh_cookie(
    client: AsyncClient, user_and_token
):
    """The session cookie is invisible to JS and unusable cross-site."""
    username, password, _ = user_and_token

    response = await _login(client, username, password)

    cookie = _refresh_cookie_header(response).lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/users" in cookie
    assert "max-age=" in cookie
    # Not `Secure` by default: a browser would drop it over the plain HTTP
    # every local deployment runs on (`REFRESH_COOKIE_SECURE` flips it).
    attributes = [part.strip().lower() for part in _refresh_cookie_header(response).split(";")]
    assert "secure" not in attributes


async def test_access_tokens_carry_iat_and_jti(client: AsyncClient, user_and_token):
    """`iat`/`jti` land now so revocation never needs another format change."""
    import jwt

    from chat_backend.config import settings

    _, _, token = user_and_token
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])

    assert payload["sub"].isdigit()
    assert isinstance(payload["iat"], int)
    assert isinstance(payload["jti"], str)
    assert len(payload["jti"]) == 32

    # Two logins, two ids: `jti` distinguishes sessions of the same user.
    other = await _login(client, "alice", "s3cret-pw")
    assert other.status_code == 200
    other_payload = jwt.decode(
        other.json()["access_token"], settings.secret_key, algorithms=["HS256"]
    )
    assert other_payload["jti"] != payload["jti"]


async def test_refresh_rotates_the_token_and_mints_a_usable_access_token(
    client: AsyncClient, user_and_token
):
    """One refresh, one new cookie, one new access token — and the old one dies."""
    await _login(client, "alice", "s3cret-pw")
    spent = client.cookies.get("refresh_token")
    assert spent

    response = await client.post("/users/refresh")

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    replacement = client.cookies.get("refresh_token")
    assert replacement and replacement != spent

    me = await client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {response.json()['access_token']}"},
    )
    assert me.status_code == 200

    # Replaying the spent copy is the theft scenario: no row, no session.
    client.cookies.set("refresh_token", spent, domain="test.local", path="/users")
    assert (await client.post("/users/refresh")).status_code == 401


async def test_refresh_without_a_cookie_is_401(client: AsyncClient):
    assert (await client.post("/users/refresh")).status_code == 401


async def test_logout_revokes_the_session_server_side(
    client: AsyncClient, user_and_token
):
    """Logout deletes the row — the browser copy alone was never enough."""
    await _login(client, "alice", "s3cret-pw")

    response = await client.post("/users/logout")

    assert response.status_code == 200
    assert response.json()["detail"] == "Logged out"
    assert "max-age=0" in _refresh_cookie_header(response).lower()
    # Both the jar's copy and any copy taken earlier are now worthless.
    assert (await client.post("/users/refresh")).status_code == 401
    client.cookies.set("refresh_token", "who-knows", domain="test.local", path="/users")
    assert (await client.post("/users/refresh")).status_code == 401


async def test_logout_without_a_cookie_still_succeeds(client: AsyncClient):
    """Logout is idempotent: an expired session logs out like any other."""
    response = await client.post("/users/logout")
    assert response.status_code == 200


async def test_an_expired_refresh_token_is_purged_not_accepted(
    client: AsyncClient, user_and_token, db_session
):
    """`expires_at` is enforced server-side, and the dead row does not linger."""
    from datetime import datetime, timedelta, timezone

    user = (
        await db_session.execute(select(models.User).where(models.User.username == "alice"))
    ).scalars().one()
    raw = auth_utils.generate_refresh_token()
    db_session.add(
        models.RefreshToken(
            user_id=user.id,
            token_hash=auth_utils.hash_refresh_token(raw),
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    )
    await db_session.commit()
    client.cookies.set("refresh_token", raw, domain="test.local", path="/users")

    assert (await client.post("/users/refresh")).status_code == 401

    rows = (
        await db_session.execute(
            select(models.RefreshToken).where(
                models.RefreshToken.token_hash == auth_utils.hash_refresh_token(raw)
            )
        )
    ).scalars().all()
    assert rows == []


async def test_cookie_endpoints_reject_cross_site_requests(client: AsyncClient):
    """CSRF layer two: `Sec-Fetch-Site`/`Origin` must say same-origin.

    `SameSite=Strict` already stops the browser sending the cookie cross-site;
    this guard rejects the request itself, so the answer is a `403` either way.
    """
    assert (
        await client.post("/users/refresh", headers={"Sec-Fetch-Site": "cross-site"})
    ).status_code == 403
    assert (
        await client.post("/users/logout", headers={"Origin": "https://evil.example"})
    ).status_code == 403
    assert (
        await client.post(
            "/users/login",
            data={"username": "alice", "password": "s3cret-pw"},
            headers={"Origin": "https://evil.example"},
        )
    ).status_code == 403

    # A genuine same-origin browser request passes the guard and reaches the
    # route: same authority as `Host`, so this is the 401 for the missing cookie.
    same_origin = await client.post("/users/refresh", headers={"Origin": "http://test"})
    assert same_origin.status_code == 401


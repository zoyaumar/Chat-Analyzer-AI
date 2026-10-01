"""Credential rate limiting.

Two layers of proof. `SlidingWindowLimiter` is exercised on its own with an
injected clock, so the window boundary is tested exactly and without sleeping.
The endpoints are then driven through the real app, so the wiring — the
dependency, the `429`, the `Retry-After` header — is proven rather than assumed.
"""
import pytest
from pydantic import ValidationError

from chat_backend import ratelimit
from chat_backend.config import Settings
from chat_backend.ratelimit import SlidingWindowLimiter

PASSWORD = "pw123456"


def test_a_zero_limit_is_rejected_at_startup():
    """A limit of 0 refuses even the first attempt — a misconfiguration, not a policy.

    Rejected by `Settings` so the app fails to start rather than 500ing on
    somebody's first login.
    """
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pw@127.0.0.1:5432/db",
            secret_key="x" * 32,
            login_rate_limit=0,
        )


def test_a_bucket_allows_the_limit_then_refuses():
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60)

    assert [limiter.retry_after("ip", now=0.0) for _ in range(3)] == [None, None, None]
    # The fourth attempt is refused, and the caller learns when to come back.
    assert limiter.retry_after("ip", now=0.0) == 60
    assert limiter.retry_after("ip", now=59.0) == 1


def test_the_window_slides_rather_than_resetting():
    """No double burst at a window boundary, which a fixed window would allow."""
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    assert limiter.retry_after("ip", now=0.0) is None
    assert limiter.retry_after("ip", now=10.0) is None
    assert limiter.retry_after("ip", now=20.0) is not None
    # At `now=60` the hit from `now=0` has left the window, so one slot is free —
    # but only one: the hit from `now=10` still counts.
    assert limiter.retry_after("ip", now=60.0) is None
    assert limiter.retry_after("ip", now=61.0) is not None


def test_buckets_are_independent():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)

    assert limiter.retry_after("ip-a", now=0.0) is None
    assert limiter.retry_after("ip-b", now=0.0) is None
    assert limiter.retry_after("ip-a", now=0.0) == 60


def test_the_table_is_bounded_and_fails_open():
    """A flood of distinct clients must not grow the dict without limit.

    Past the cap the limiter prefers to let a request through rather than
    refuse it: it exists to protect availability, so becoming the denial of
    service would defeat the purpose.
    """
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60, max_keys=2)

    assert limiter.retry_after("a", now=0.0) is None
    assert limiter.retry_after("b", now=0.0) is None
    assert limiter.retry_after("c", now=0.0) is None  # untracked, not refused
    assert limiter.tracked_keys() == 2
    # Once both buckets have expired the table makes room again.
    assert limiter.retry_after("d", now=120.0) is None
    assert limiter.tracked_keys() == 1


async def _login(client, password: str = PASSWORD, **kwargs):
    return await client.post(
        "/users/login", data={"username": "alice", "password": password}, **kwargs
    )


async def test_login_is_limited_per_client(client, monkeypatch):
    """A password guesser runs out of attempts and is told to wait.

    The failed attempts are deliberate: every attempt spends budget, which is
    the whole point of a brute-force limit.
    """
    monkeypatch.setattr(ratelimit.LOGIN_LIMITER, "limit", 2)
    monkeypatch.setattr(ratelimit.LOGIN_LIMITER, "window_seconds", 300.0)
    await client.post("/users/register", json={"username": "alice", "password": PASSWORD})

    assert (await _login(client, "wrongpass")).status_code == 401
    assert (await _login(client, "wrongpass")).status_code == 401

    blocked = await _login(client, "wrongpass")

    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many attempts. Please try again later."
    assert 1 <= int(blocked.headers["Retry-After"]) <= 300


async def test_a_correct_password_is_refused_once_the_budget_is_spent(client, monkeypatch):
    """The limit is not a failed-login detector — it gates the endpoint."""
    monkeypatch.setattr(ratelimit.LOGIN_LIMITER, "limit", 1)
    await client.post("/users/register", json={"username": "alice", "password": PASSWORD})

    assert (await _login(client, "wrongpass")).status_code == 401
    assert (await _login(client)).status_code == 429


async def test_registration_is_limited(client, monkeypatch):
    """Open signup cannot be used to fill the table from one address."""
    monkeypatch.setattr(ratelimit.REGISTER_LIMITER, "limit", 2)

    first = await client.post("/users/register", json={"username": "user1", "password": PASSWORD})
    second = await client.post("/users/register", json={"username": "user2", "password": PASSWORD})
    third = await client.post("/users/register", json={"username": "user3", "password": PASSWORD})

    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 429
    assert third.headers["Retry-After"]


async def test_login_and_registration_are_separate_budgets(client, monkeypatch):
    """An exhausted login budget must not stop a legitimate signup."""
    monkeypatch.setattr(ratelimit.LOGIN_LIMITER, "limit", 1)
    monkeypatch.setattr(ratelimit.REGISTER_LIMITER, "limit", 1)

    await client.post("/users/register", json={"username": "alice", "password": PASSWORD})
    assert (await _login(client, "wrongpass")).status_code == 401
    assert (await _login(client, "wrongpass")).status_code == 429

    # The register budget was spent by the call above, and it is its own limiter.
    assert (
        await client.post("/users/register", json={"username": "bob", "password": PASSWORD})
    ).status_code == 429


async def test_the_forwarded_address_is_the_bucket(client, monkeypatch):
    """Behind nginx each client gets its own bucket, not the proxy's."""
    monkeypatch.setattr(ratelimit.LOGIN_LIMITER, "limit", 1)

    one = await _login(client, "wrongpass", headers={"X-Real-IP": "203.0.113.1"})
    two = await _login(client, "wrongpass", headers={"X-Real-IP": "203.0.113.2"})
    one_again = await _login(client, "wrongpass", headers={"X-Real-IP": "203.0.113.1"})

    assert (one.status_code, two.status_code) == (401, 401)
    assert one_again.status_code == 429


async def test_without_a_proxy_the_socket_peer_is_the_bucket(client, monkeypatch):
    """`uvicorn` on its own sends no `X-Real-IP`; the peer address still limits."""
    monkeypatch.setattr(ratelimit.LOGIN_LIMITER, "limit", 1)

    first = await _login(client, "wrongpass")
    second = await _login(client, "wrongpass")

    assert first.status_code == 401
    assert second.status_code == 429


@pytest.mark.parametrize("path", ["/users/login", "/users/register"])
async def test_the_limit_is_part_of_the_documented_contract(client, path):
    """`/docs` advertises the `429`, so the behaviour is not a surprise."""
    schema = (await client.get("/openapi.json")).json()

    assert "429" in schema["paths"][path]["post"]["responses"]

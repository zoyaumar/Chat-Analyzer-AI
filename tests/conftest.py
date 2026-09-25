"""Shared fixtures: a throwaway PostgreSQL schema per test session.

The database is resolved in this order:
  1. `TEST_DATABASE_URL`, if you set one;
  2. an already-exported `DATABASE_URL` (what CI provides);
  3. a local disposable container on port 5433 (see the root README).
"""
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

_default_url = os.environ.get("DATABASE_URL") or (
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/chat_test"
)
# Must be set before chat_backend.config is imported anywhere.
os.environ.setdefault("TEST_DATABASE_URL", _default_url)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
# >= 32 bytes keeps PyJWT quiet (RFC 7518 HMAC key length).
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789-0123456789")

from chat_backend.database import Base, get_db  # noqa: E402
from chat_backend.main import app  # noqa: E402

engine = create_async_engine(os.environ["DATABASE_URL"])
TestSession = async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
async def setup_schema():
    """Create the schema from metadata once per session (test DB only)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_tables(setup_schema):
    """Isolate every test: clear all rows and restart identity sequences."""
    yield
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, messages RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db_session():
    """Provide a direct database session for tests that need precise row values."""
    async with TestSession() as session:
        yield session


@pytest.fixture
async def client():
    async def override_get_db():
        async with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    # httpx's ASGI protocol type does not match FastAPI.__call__'s overloads.
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    # Remove only our own override: another fixture may have registered its own.
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def ws_client(monkeypatch):
    """A sync `TestClient` for socket tests, wired to the test database.

    `TestClient` drives the app in its own portal event loop, which the async
    fixtures do not share, so this engine uses `NullPool`: one connection per
    operation, never a pooled connection created on a different loop. The socket
    handler's session factory is swapped for the same one, and `get_db` is
    overridden so the HTTP calls these tests make (register, log in, list,
    delete) read the same database as the socket.

    Registering through this client is also why the token and the socket agree:
    the socket re-loads the user by id from this database before accepting it.
    """
    from chat_backend.routes import websocket as websocket_module

    test_engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(websocket_module, "SessionLocal", session_factory)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def user_and_token(client: AsyncClient):
    """Register + login a user; return (username, password, token)."""
    username = "alice"
    password = "s3cret"
    resp = await client.post(
        "/users/register", json={"username": username, "password": password}
    )
    assert resp.status_code == 200
    resp = await client.post(
        "/users/login",
        data={"username": username, "password": password},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return username, password, token
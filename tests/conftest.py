"""Shared fixtures: a throwaway PostgreSQL schema per test session.

Set TEST_DATABASE_URL to point at a disposable database, e.g.:
    postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/chat_test
"""
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Must be set before chat_backend.config is imported anywhere.
os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/chat_test"
)
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
async def client():
    async def override_get_db():
        async with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


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
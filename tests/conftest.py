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

from chat_backend import ai_utils  # noqa: E402
from chat_backend.database import Base, get_db  # noqa: E402
from chat_backend.main import app  # noqa: E402

# Captured before any fixture patches them: `real_ai` below hands these back to a
# test that genuinely wants the model (only the opt-in evaluation run does).
_ORIGINAL_AI_FUNCTIONS = {
    "analyze_sentiment": ai_utils.analyze_sentiment,
    "sentiment_model_info": ai_utils.sentiment_model_info,
    "summarize_text": ai_utils.summarize_text,
}

engine = create_async_engine(os.environ["DATABASE_URL"])
TestSession = async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
async def setup_schema():
    """Rebuild the schema from metadata once per session (test DB only).

    `drop_all` first: `create_all` alone silently keeps a stale schema when
    the models change, which is exactly how a missing `ON DELETE CASCADE`
    would go unnoticed (gaps D4/D6).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
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


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Every test starts and ends with empty limiter buckets (gap S6).

    The limiters are process-wide and the suite logs in far more often than one
    window allows from one address, so without this the credential tests would
    rate-limit each other. Resetting on the way out too keeps a test that
    deliberately exhausts a budget from leaking into the next file.
    """
    from chat_backend import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch):
    """No test ever loads a model (gaps A4/A6/T5).

    `crud.create_message` scores at write time (A4), so without this every
    message test would download DistilBERT on its first send. The fakes replace
    the public names in `ai_utils` *and* in `routes.analytics` (which imports
    them by name — patching only the module would leave the route pointing at
    the real pipeline); a test that patches either name itself still wins.

    Reproducible provenance on purpose: assertions can expect exactly these
    values in `message_sentiment` (gap A7).
    """
    from chat_backend import ai_utils
    from chat_backend.routes import analytics

    def fake_sentiment(text: str) -> dict:
        return {"label": "POSITIVE", "score": 0.99}

    def fake_model_info() -> dict:
        return {"model_name": "test-model", "model_version": "test-revision"}

    def fake_summary(text: str) -> str:
        return text

    for module in (ai_utils, analytics):
        monkeypatch.setattr(module, "analyze_sentiment", fake_sentiment)
        monkeypatch.setattr(module, "summarize_text", fake_summary)
    monkeypatch.setattr(ai_utils, "sentiment_model_info", fake_model_info)
    return {"sentiment": fake_sentiment, "summary": fake_summary, "info": fake_model_info}


@pytest.fixture
def real_ai(monkeypatch):
    """Undo `fake_ai` for a test that really wants the model (gap A7).

    Only `tests/test_ai_eval.py` opts in, and only behind `RUN_AI_EVAL=1`.
    """
    for name, function in _ORIGINAL_AI_FUNCTIONS.items():
        monkeypatch.setattr(ai_utils, name, function)


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
    """Register + login a user; return (username, password, token).

    The password satisfies the credential policy (gap S6): at least 8
    characters, at most 72 bytes.
    """
    username = "alice"
    password = "s3cret-pw"
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
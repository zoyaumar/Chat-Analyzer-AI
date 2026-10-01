from httpx import AsyncClient


async def test_health_liveness(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_health_ready(client: AsyncClient):
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"
    # Models are reported, not required: chat works without them,
    # so the probe stays 200 and says what state each capability is in.
    assert set(body["model_state"]) == {"sentiment", "summary"}
    assert all(
        state in {"ready", "failed", "not_loaded"} for state in body["model_state"].values()
    )


async def test_health_ready_reports_a_failed_model_without_failing_the_probe(
    client: AsyncClient, monkeypatch
):
    from chat_backend import ai_utils

    monkeypatch.setitem(ai_utils._LOAD_FAILURES, "summarization", "RuntimeError: boom")
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["model_state"]["summary"] == "failed"


async def test_root_welcome(client: AsyncClient):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "message" in resp.json()
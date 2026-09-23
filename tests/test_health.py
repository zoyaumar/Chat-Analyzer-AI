from httpx import AsyncClient


async def test_health_liveness(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_health_ready(client: AsyncClient):
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "up"}


async def test_root_welcome(client: AsyncClient):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "message" in resp.json()
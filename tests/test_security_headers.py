"""Security headers on every API response (gap S11)."""
from httpx import AsyncClient


async def test_json_responses_carry_the_hardening_headers(client: AsyncClient):
    resp = await client.get("/health")

    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert resp.headers["Strict-Transport-Security"].startswith("max-age=31536000")

    csp = resp.headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    # JSON responses need no CDN; the Swagger allowance must not leak here.
    assert "cdn.jsdelivr.net" not in csp


async def test_error_responses_carry_the_headers_too(client: AsyncClient):
    resp = await client.get("/no-such-route")

    assert resp.status_code == 404
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Content-Security-Policy"]


async def test_docs_pages_get_the_swagger_compatible_csp(client: AsyncClient):
    for path in ("/docs", "/openapi.json"):
        resp = await client.get(path)
        assert resp.status_code == 200, path
        csp = resp.headers["Content-Security-Policy"]
        # The browser UIs load the Swagger bundle and its inline bootstrap.
        assert "https://cdn.jsdelivr.net" in csp, path
        assert "frame-ancestors 'none'" in csp, path
        assert resp.headers["X-Frame-Options"] == "DENY", path

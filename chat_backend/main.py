import logging

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from chat_backend.config import settings
from chat_backend.database import get_db
from chat_backend.observability import (
    RequestLoggingMiddleware,
    setup_logging,
)
from chat_backend.routes import analytics, messages, users, websocket

setup_logging(logging.DEBUG if settings.debug else logging.INFO)
logger = logging.getLogger("chat_backend.api")

# --- Browser hardening (gap S11) ---
# JSON responses get a locked-down CSP: nothing may load, embed or frame them.
# The Swagger/ReDoc pages are real browser UIs and need the Swagger bundle and
# its inline bootstrap, so they get the narrow policy that permits exactly that.
_DOCS_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})

_STRICT_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
_DOCS_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Response headers for browser hardening (gap S11).

    HSTS is emitted unconditionally: a browser ignores it over plain HTTP, so
    it is inert on `localhost` and takes effect the moment TLS terminates
    upstream.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            _DOCS_CSP if request.url.path in _DOCS_PATHS else _STRICT_CSP
        )
        return response

app = FastAPI(
    title="Chat Analyzer AI",
    description="Backend API for chat storage and analysis",
    version="0.1.0",
)

# No CORS middleware: the app is same-origin everywhere — Vite proxies in
# development, nginx in production (gaps S4/F15, Q34).
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(users.router)
app.include_router(messages.router)
app.include_router(analytics.router)
app.include_router(websocket.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log the full traceback server-side; never leak details to clients (gap B11).

    The request id goes into the log line *and* into the response body, so a
    user-visible failure can be matched to its traceback (gap O5).
    """
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled error on %s %s",
        request.method,
        request.url.path,
        extra={"request_id": request_id},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


@app.get("/health")
async def health() -> dict:
    """Liveness: the process is up and serving requests."""
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Readiness: the database answers `SELECT 1`."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Readiness check failed: database unreachable")
        return JSONResponse(
            status_code=503, content={"status": "unavailable", "database": "down"}
        )
    return JSONResponse(content={"status": "ok", "database": "up"})


@app.get("/")
async def read_root() -> dict:
    return {"message": "Welcome to Chat Analyzer API with AI!"}

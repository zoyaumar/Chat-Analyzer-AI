import logging

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend.config import settings
from chat_backend.database import get_db
from chat_backend.observability import (
    RequestLoggingMiddleware,
    setup_logging,
)
from chat_backend.routes import analytics, messages, users, websocket

setup_logging(logging.DEBUG if settings.debug else logging.INFO)
logger = logging.getLogger("chat_backend.api")

app = FastAPI(
    title="Chat Analyzer AI",
    description="Backend API for chat storage and analysis",
    version="0.1.0",
)

# No CORS middleware: the app is same-origin everywhere — Vite proxies in
# development, nginx in production (gaps S4/F15, Q34).
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

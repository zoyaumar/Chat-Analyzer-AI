"""Per-client rate limiting for the credential endpoints (gap S6).

`POST /users/login` could be hammered without limit and `POST /users/register`
was open to spam. Both now count attempts per client address in a sliding
window and answer `429` with a `Retry-After` header once the window is full.

**Why in-process instead of `slowapi` or an nginx rule.** The two obvious
alternatives both cost more than they buy at this size: `slowapi` adds a
dependency (and pulls in `limits`) for what one class here does, while a
reverse-proxy rule lives outside the application, cannot be exercised by the
test suite, and needs a reload to tune. The counter is the *in-process* option
of the still-open "shared state" question (U8) — no Redis, nothing to run.

**What it does not do, stated plainly.**
- PER-PROCESS BY DESIGN: state is per process, so N uvicorn workers multiply every
  limit by N. That is exact at one worker, which the startup guard enforces loudly;
  a shared store is what makes it exact beyond that (gap P17, docs/scaling.md).
- The bucket key trusts `X-Real-IP`, which is only safe because nginx overwrites
  that header (`docker/nginx.conf`) and the `api` service publishes no port
  (`docker-compose.yml`). Where the API is exposed directly, a client can forge
  it and the limit becomes advisory.
- It protects availability, so it fails open: a table full of live buckets lets
  a new client through untracked rather than refusing it (see `_make_room`).
"""
import logging
import threading
import time
from collections import deque
from math import ceil
from typing import Any

from fastapi import HTTPException, Request, status

from chat_backend.config import settings

logger = logging.getLogger("chat_backend.ratelimit")


class SlidingWindowLimiter:
    """Allow `limit` events per `window_seconds` for each key, in this process.

    A sliding window rather than a fixed one: a fixed window lets a client spend
    its whole budget at the end of one window and again at the start of the
    next, so the effective burst rate is double the configured one.
    """

    def __init__(self, limit: int, window_seconds: float, max_keys: int = 10_000) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        # Monotonic timestamps, oldest first, per key. `time.monotonic` on
        # purpose: a wall-clock adjustment must not hand out extra attempts.
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        """Forget every bucket (the test fixture, and a future admin hook)."""
        with self._lock:
            self._hits.clear()

    def tracked_keys(self) -> int:
        """How many buckets are held right now — the memory bound, observable."""
        with self._lock:
            return len(self._hits)

    def retry_after(self, key: str, now: float | None = None) -> float | None:
        """Record one event for `key` and report whether it may proceed.

        Returns `None` when the event fits in the window, otherwise the seconds
        until `key` may try again — the value of the `Retry-After` header.
        `now` is injectable so the window can be tested without sleeping.
        """
        moment = time.monotonic() if now is None else now
        cutoff = moment - self.window_seconds
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if not self._make_room(cutoff):
                    return None
                hits = self._hits[key] = deque()
            else:
                # Anything at or before the cutoff has left the window.
                while hits and hits[0] <= cutoff:
                    hits.popleft()
            if len(hits) >= self.limit:
                return hits[0] + self.window_seconds - moment
            hits.append(moment)
            return None

    def _make_room(self, cutoff: float) -> bool:
        """Drop expired buckets so a new key can be tracked; `False` if full.

        Called with the lock held, only when a key is seen for the first time —
        a table of `max_keys` *live* buckets means more distinct clients than
        the cap allows within one window, which is a flood rather than traffic.
        Letting that client through untracked keeps the limiter from becoming
        the denial of service it exists to prevent; the warning is the signal
        that the cap, or the deployment shape, needs a second look.
        """
        if len(self._hits) < self.max_keys:
            return True
        for stale in [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[stale]
        if len(self._hits) < self.max_keys:
            return True
        logger.warning(
            "rate-limit table is full (%s live keys); allowing untracked request", self.max_keys
        )
        return False


# One limiter per endpoint: login and registration are separate budgets, so an
# exhausted login budget cannot lock a legitimate signup out of the app.
LOGIN_LIMITER = SlidingWindowLimiter(
    settings.login_rate_limit, settings.login_rate_window_seconds
)
REGISTER_LIMITER = SlidingWindowLimiter(
    settings.register_rate_limit, settings.register_rate_window_seconds
)

# Declared on the routes so `/docs` documents the `429` next to the `422`: a
# rate-limited endpoint is part of the contract, not an accident.
RATE_LIMIT_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "description": "Too many attempts from this client; wait `Retry-After` seconds (gap S6)."
    }
}


def reset() -> None:
    """Clear every limiter's state."""
    for limiter in (LOGIN_LIMITER, REGISTER_LIMITER):
        limiter.clear()


def client_key(request: Request) -> str:
    """The bucket key for `request`: who the proxy says the client is.

    `X-Real-IP` first because behind the Compose stack nginx rewrites it from
    `$remote_addr`, discarding anything the client sent — without that, every
    user behind the proxy would share a single bucket. The socket peer is the
    fallback for `uvicorn` on its own (local development and the tests).
    """
    forwarded = request.headers.get("X-Real-IP")
    if forwarded:
        return forwarded.strip()
    return request.client.host if request.client else "unknown"


def _enforce(limiter: SlidingWindowLimiter, request: Request, scope: str) -> None:
    """Refuse the request when `limiter` has no budget left for its client."""
    retry_after = limiter.retry_after(f"{scope}:{client_key(request)}")
    if retry_after is None:
        return
    # A client that should wait 0.4 s is told to wait 1: `Retry-After` has
    # whole-second resolution, and rounding down would invite an instant retry.
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many attempts. Please try again later.",
        headers={"Retry-After": str(max(1, ceil(retry_after)))},
    )


async def login_rate_limit(request: Request) -> None:
    """`Depends` target for `POST /users/login` (gap S6)."""
    _enforce(LOGIN_LIMITER, request, "login")


async def register_rate_limit(request: Request) -> None:
    """`Depends` target for `POST /users/register` (gap S6)."""
    _enforce(REGISTER_LIMITER, request, "register")

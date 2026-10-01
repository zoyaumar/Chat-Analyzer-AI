import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend import models
from chat_backend.config import settings
from chat_backend.database import get_db

ALGORITHM = "HS256"

#: Cookie carrying the refresh token. `HttpOnly` keeps it out of
#: JavaScript entirely; `Path=/users` keeps it off every other endpoint — only
#: login, refresh and logout ever see it.
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/users"

# argon2id writes every password registered from now on; bcrypt is kept in the
# list purely so hashes written before the migration still open.
# `PasswordHash.hash()` always uses the *first* hasher, so registration produces
# argon2 and `verify_and_rehash` hands back an argon2 replacement for a bcrypt
# hash that just proved itself. Accounts therefore upgrade one login at a time —
# no lockout, no backfill script, and the `bcrypt<4.1` stopgap retires with
# the last bcrypt row it ever has to verify.
password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login")


def verify_and_rehash(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    """`(True, replacement)` when the password opens the hash.

    The second element is a hash worth storing when one exists and `None` when
    what is stored is already current — that is the whole rehash-on-login path.

    Two failures are deliberately *not* an exception to the caller: bcrypt
    refuses input over its 72-byte limit outright (`ValueError`; bcrypt 5.0.0
    raises instead of truncating) and a stored hash may name a hasher this
    install does not have (`UnknownHashError`). Neither is a usable credential,
    and on a login route neither may become a `500`.
    """
    try:
        valid, rehashed = password_hash.verify_and_update(
            plain_password, hashed_password
        )
    except (ValueError, UnknownHashError):
        return False, None
    return valid, rehashed


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Whether the password opens the hash, ignoring any upgrade."""
    valid, _ = verify_and_rehash(plain_password, hashed_password)
    return valid


def get_password_hash(password: str) -> str:
    """Hash with the current hasher — argon2id, never bcrypt."""
    return password_hash.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Sign an access token carrying `iat` and `jti` next to `sub`/`exp`.

    `jti` gives the token a unique id and `iat` the moment it was minted: both
    are what a future denylist or session audit needs, and they are written now
    so revocation never needs another token-format change. The claims
    are informational only — the revocable half of the session is the refresh
    token, not this one.
    """
    now = datetime.now(timezone.utc)
    to_encode = data.copy()
    expire = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire, "iat": now, "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def generate_refresh_token() -> str:
    """256 bits of `token_urlsafe` entropy — opaque, unguessable, not a JWT.

    The value never needs to be parsed, only looked up by hash, so there is no
    payload to forge and no signature to keep in sync.
    """
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex of the token — what the database stores, never the token.

    A row dump yields no live sessions: preimage resistance is the whole
    requirement, because the hash is only ever compared, never cracked.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expiry() -> datetime:
    """When a freshly minted refresh token stops working (sliding expiry)."""
    return datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)


def set_refresh_cookie(response: Response, token: str) -> None:
    """Attach the refresh token as `HttpOnly; SameSite=Strict; Path=/users`.

    `HttpOnly` is the line of defence XSS does not get to cross (the JS half of
    the session lives in memory only); `SameSite=Strict` means no cross-site
    request ever carries the cookie; `Path` narrows it to the endpoints that
    need it. `Secure` follows `REFRESH_COOKIE_SECURE` because a browser drops a
    Secure cookie over plain HTTP and local development runs plain HTTP.
    """
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response) -> None:
    """Retire the cookie — same attributes the browser matches on."""
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=settings.refresh_cookie_secure,
        samesite="strict",
    )


async def require_same_origin(request: Request) -> None:
    """Reject cross-site requests to the cookie endpoints.

    The cookie carries the session, so anything that can make the browser *send*
    it from another site is a CSRF attempt. Two signals are checked, most
    reliable first:

    1. `Sec-Fetch-Site` — sent by every browser since ~2020 on every request;
       it must say `same-origin`. It survives proxies rewriting `Host`, which
       the fallback below cannot see (the Vite dev proxy, for one).
    2. `Origin` — the fallback and what non-Chromium clients still send: its
       authority must match the `Host` header the request arrived with.

    Neither header present means a non-browser client (curl, a test) — a
    cross-site attack always comes with a browser attached, so there is nothing
    to reject. `SameSite=Strict` on the cookie already refuses the cross-site
    send; this is the second, explicit layer.
    """
    sec_fetch_site = request.headers.get("sec-fetch-site")
    if sec_fetch_site is not None:
        if sec_fetch_site != "same-origin":
            raise HTTPException(status_code=403, detail="Cross-site request rejected")
        return
    origin = request.headers.get("origin")
    if origin is None:
        return
    if urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(status_code=403, detail="Cross-site request rejected")


def user_id_from_token(token: str) -> int | None:
    """The subject of a valid token, or `None` when the token is unusable.

    Shared by the REST dependency and the WebSocket handshake so both transports
    answer the same question the same way: an unreadable, expired or malformed
    token is simply "no user", never a server error.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    subject = payload.get("sub")
    if subject is None:
        return None
    try:
        return int(subject)
    except (TypeError, ValueError):
        return None


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> models.User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user_id = user_id_from_token(token)
    if user_id is None:
        raise credentials_error
    user = await db.get(models.User, user_id)
    if user is None:
        raise credentials_error
    return user

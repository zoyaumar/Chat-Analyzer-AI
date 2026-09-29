from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
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

# argon2id writes every password registered from now on; bcrypt is kept in the
# list purely so hashes written before the migration still open (gap S10).
# `PasswordHash.hash()` always uses the *first* hasher, so registration produces
# argon2 and `verify_and_rehash` hands back an argon2 replacement for a bcrypt
# hash that just proved itself. Accounts therefore upgrade one login at a time —
# no lockout, no backfill script, and the `bcrypt<4.1` stopgap (Q7) retires with
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
    refuses input over its 72-byte limit outright (`ValueError`, bcrypt >= 4.1
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
    """Whether the password opens the hash, ignoring any upgrade (gap S10)."""
    valid, _ = verify_and_rehash(plain_password, hashed_password)
    return valid


def get_password_hash(password: str) -> str:
    """Hash with the current hasher — argon2id, never bcrypt (gap S10)."""
    return password_hash.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def user_id_from_token(token: str) -> int | None:
    """The subject of a valid token, or `None` when the token is unusable.

    Shared by the REST dependency and the WebSocket handshake so both transports
    answer the same question the same way: an unreadable, expired or malformed
    token is simply "no user", never a server error (gap S1).
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

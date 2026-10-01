from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend import auth_utils, models, ratelimit, schemas
from chat_backend.auth_utils import create_access_token, get_current_user
from chat_backend.database import get_db

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "/login",
    response_model=schemas.Token,
    # Brute-force surface: limited per client address. The origin guard
    # keeps a foreign page from minting a session cookie for its own account.
    dependencies=[
        Depends(ratelimit.login_rate_limit),
        Depends(auth_utils.require_same_origin),
    ],
    responses=ratelimit.RATE_LIMIT_RESPONSES,
)
async def login(
    # `Response` first: FastAPI injects it, and a parameter without a default
    # cannot follow `form_data = Depends()`.
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.User).where(models.User.username == form_data.username)
    )
    user = result.scalars().first()
    credentials_error = HTTPException(
        status_code=401, detail="Invalid username or password"
    )
    if user is None:
        raise credentials_error
    valid, rehashed = auth_utils.verify_and_rehash(
        form_data.password, user.password_hash
    )
    if not valid:
        raise credentials_error
    if rehashed is not None:
        # The stored hash needs rehashing (bcrypt, or stale argon2 parameters).
        # The login that just proved the password is the moment to rewrite it, so
        # accounts migrate themselves instead of waiting for a backfill script.
        user.password_hash = rehashed

    # The session has two halves: a short-lived access token in
    # the response body — held in memory by the SPA — and a rotating refresh
    # token in an HttpOnly cookie, stored hashed. Only the pair together is a
    # session, and only the cookie's row is revocable (`POST /users/logout`).
    refresh_token = auth_utils.generate_refresh_token()
    db.add(
        models.RefreshToken(
            user_id=user.id,
            token_hash=auth_utils.hash_refresh_token(refresh_token),
            expires_at=auth_utils.refresh_token_expiry(),
        )
    )
    await db.commit()

    access_token = create_access_token(data={"sub": str(user.id)})
    auth_utils.set_refresh_cookie(response, refresh_token)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post(
    "/refresh",
    response_model=schemas.Token,
    # The cookie is the credential, so the request that spends it must be
    # provably same-origin; there is no bearer header to fall back on.
    dependencies=[Depends(auth_utils.require_same_origin)],
)
async def refresh_access_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Exchange the refresh cookie for a new access token.

    Rotation on every use: the presented token's row is deleted and a
    replacement issued, so each token works exactly once. Replaying a copy the
    real client has already spent finds no row — a stolen refresh token dies the
    moment either side refreshes. Rows past `expires_at` are purged as they are
    encountered; they can never authenticate again.
    """
    raw = request.cookies.get(auth_utils.REFRESH_COOKIE_NAME)
    if not raw:
        raise HTTPException(status_code=401, detail="Not authenticated")

    now = datetime.now(timezone.utc)
    await db.execute(
        delete(models.RefreshToken).where(models.RefreshToken.expires_at <= now)
    )
    token_hash = auth_utils.hash_refresh_token(raw)
    result = await db.execute(
        select(models.RefreshToken).where(models.RefreshToken.token_hash == token_hash)
    )
    row = result.scalars().first()
    if row is None:
        # Unknown or expired: revocation by absence. Commit the purge above.
        await db.commit()
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = row.user_id
    await db.delete(row)
    replacement = auth_utils.generate_refresh_token()
    db.add(
        models.RefreshToken(
            user_id=user_id,
            token_hash=auth_utils.hash_refresh_token(replacement),
            expires_at=auth_utils.refresh_token_expiry(),
        )
    )
    await db.commit()

    auth_utils.set_refresh_cookie(response, replacement)
    return {"access_token": create_access_token(data={"sub": str(user_id)}), "token_type": "bearer"}


@router.post("/logout", dependencies=[Depends(auth_utils.require_same_origin)])
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Revoke this session's refresh token and retire the cookie.

    Logout exists server-side now: the row is deleted, so the cookie — even a
    copy taken before logout — no longer refreshes anything. The short-lived
    access token in memory simply dies with the tab; that is what its lifetime
    is for. Idempotent by design: no cookie still answers `200` and still clears
    whatever the caller had.
    """
    raw = request.cookies.get(auth_utils.REFRESH_COOKIE_NAME)
    if raw:
        await db.execute(
            delete(models.RefreshToken).where(
                models.RefreshToken.token_hash == auth_utils.hash_refresh_token(raw)
            )
        )
        await db.commit()
    auth_utils.clear_refresh_cookie(response)
    return {"detail": "Logged out"}


@router.post(
    "/register",
    response_model=schemas.UserOut,
    # Spam surface: a smaller budget over a longer window. The policy
    # itself — username shape, password length — is enforced by `UserCreate`,
    # so the two layers are independent: a body that `422`s still spends budget,
    # which is what a sprayer sends anyway (see `tests/test_rate_limit.py`).
    dependencies=[Depends(ratelimit.register_rate_limit)],
    responses=ratelimit.RATE_LIMIT_RESPONSES,
)
async def register_user(user: schemas.UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.User).where(models.User.username == user.username)
    )
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Username already registered")

    new_user = models.User(
        username=user.username,
        password_hash=auth_utils.get_password_hash(user.password),
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


@router.get("/me", response_model=schemas.UserOut)
async def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.get("/{user_id}", response_model=schemas.UserOut)
async def read_user(
    user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Public profile fields for `user_id` — attribution for a message.

    Registered after `GET /users/me`, which wins the `/users/me` path. Only the
    safe projection leaves (`UserOut`: id, username, created_at) — never the
    password hash.
    """
    user = await db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/me")
async def delete_users_me(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete the authenticated account and everything that belongs to it.

    The messages go with it through the FK's `ON DELETE CASCADE`; the
    relationship's `passive_deletes=True` means this is a single `DELETE`, not
    a load-then-delete of every message. The issued token dies with the user,
    because `get_current_user` can no longer resolve it.
    """
    await db.delete(current_user)
    await db.commit()
    return {"detail": "Account deleted"}
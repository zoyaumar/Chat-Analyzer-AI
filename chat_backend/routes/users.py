from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend import auth_utils, models, ratelimit, schemas
from chat_backend.auth_utils import create_access_token, get_current_user
from chat_backend.database import get_db

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "/login",
    response_model=schemas.Token,
    # Brute-force surface: limited per client address (gap S6).
    dependencies=[Depends(ratelimit.login_rate_limit)],
    responses=ratelimit.RATE_LIMIT_RESPONSES,
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.User).where(models.User.username == form_data.username)
    )
    user = result.scalars().first()
    if not user or not auth_utils.verify_password(
        form_data.password, user.password_hash
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post(
    "/register",
    response_model=schemas.UserOut,
    # Spam surface: a smaller budget over a longer window (gap S6). The policy
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
    """Public profile fields for `user_id` — attribution for a message (gap F10).

    Registered after `GET /users/me`, which wins the `/users/me` path. Only the
    safe projection leaves (`UserOut`: id, username, created_at) — never the
    password hash (gap S3).
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

    The messages go with it through the FK's `ON DELETE CASCADE` (gap D4); the
    relationship's `passive_deletes=True` means this is a single `DELETE`, not
    a load-then-delete of every message. The issued token dies with the user,
    because `get_current_user` can no longer resolve it.
    """
    await db.delete(current_user)
    await db.commit()
    return {"detail": "Account deleted"}
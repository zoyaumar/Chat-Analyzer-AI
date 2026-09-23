from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend import auth_utils, models, schemas
from chat_backend.auth_utils import create_access_token, get_current_user
from chat_backend.database import get_db

router = APIRouter(prefix="/users", tags=["users"])

@router.post("/login", response_model=schemas.Token)
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


@router.post("/register", response_model=schemas.UserOut)
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
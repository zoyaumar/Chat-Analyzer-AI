from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm

from .. import models, schemas, auth_utils, database
from ..database import get_db

router = APIRouter(prefix="/users", tags=["users"])

@router.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # 1. Get the user from DB
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # 2. Verify password
    if not auth_utils.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # 3. Create JWT
    access_token = auth_utils.create_access_token(data={"sub": str(user.id)})

    # 4. Return token
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/register", response_model=schemas.UserOut)
def register_user(user: schemas.UserCreate, db: Session = Depends(database.get_db)):
    # Check if username is taken
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    # Hash the password before storing
    hashed_pw = auth_utils.get_password_hash(user.password)
    new_user = models.User(username=user.username, password_hash=hashed_pw)

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user
# routes/messages.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .. import models, schemas
from ..database import get_db
from ..auth_utils import get_current_user  # if you want to protect routes

router = APIRouter(prefix="/messages", tags=["messages"])

@router.post("/")
def create_message(
    message: schemas.MessageCreate,
    db: Session = Depends(get_db),
    current_user: int = Depends(get_current_user)
):
    db_message = models.Message(
        user_id=current_user,
        text=message.text
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

@router.get("/")
def list_messages(db: Session = Depends(get_db), skip: int = 0, limit: int = 10):
    return db.query(models.Message).offset(skip).limit(limit).all()

@router.delete("/{message_id}")
def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    msg = db.query(models.Message).filter(
        models.Message.id == message_id,
        models.Message.user_id == current_user
    ).first()
    if msg:
        db.delete(msg)
        db.commit()
        return {"detail": "Message deleted"}
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found or not yours")
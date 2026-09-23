# routes/messages.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend import models, schemas
from chat_backend.auth_utils import get_current_user
from chat_backend.database import get_db

router = APIRouter(prefix="/messages", tags=["messages"])

@router.post("/")
async def create_message(
    message: schemas.MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_message = models.Message(user_id=current_user.id, text=message.text)
    db.add(db_message)
    await db.commit()
    await db.refresh(db_message)
    return db_message

@router.get("/")
async def list_messages(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: models.User = Depends(get_current_user),
):
    result = await db.execute(
        select(models.Message)
        .where(models.Message.user_id == current_user.id)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

@router.delete("/{message_id}")
async def delete_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    result = await db.execute(
        select(models.Message).where(
            models.Message.id == message_id,
            models.Message.user_id == current_user.id,
        )
    )
    msg = result.scalars().first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found or not yours")
    await db.delete(msg)
    await db.commit()
    return {"detail": "Message deleted"}
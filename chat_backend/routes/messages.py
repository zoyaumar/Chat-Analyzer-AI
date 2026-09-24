# routes/messages.py
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend import models, schemas
from chat_backend.auth_utils import get_current_user
from chat_backend.database import get_db

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("/", response_model=schemas.MessageOut)
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


@router.get("/", response_model=list[schemas.MessageOut])
async def list_messages(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=100),
    before: datetime | None = Query(default=None),
    before_id: int | None = Query(default=None, ge=1),
    current_user: models.User = Depends(get_current_user),
):
    """Return a chronological page, with an optional keyset cursor for older messages."""
    if (before is None) != (before_id is None):
        raise HTTPException(status_code=400, detail="before and before_id must be used together")
    if before is not None and before.tzinfo is None:
        raise HTTPException(status_code=400, detail="before must include a timezone")

    query = select(models.Message).where(models.Message.user_id == current_user.id)
    if before is not None:
        query = query.where(
            or_(
                models.Message.timestamp < before,
                and_(
                    models.Message.timestamp == before,
                    models.Message.id < before_id,
                ),
            )
        )

    result = await db.execute(
        query.order_by(models.Message.timestamp.desc(), models.Message.id.desc()).limit(limit)
    )
    messages = list(result.scalars().all())
    messages.reverse()
    return messages


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
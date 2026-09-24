# routes/messages.py
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend import crud, models, realtime, schemas
from chat_backend.auth_utils import get_current_user
from chat_backend.database import get_db
from chat_backend.realtime import manager

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("/", response_model=schemas.MessageOut)
async def create_message(
    message: schemas.MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Store the message, then push it to every socket the author has open (gap B1).

    The push is the same frame a socket-sent message produces, so a tab that
    sends over HTTP with a dead socket still sees the message appear everywhere
    else.
    """
    db_message = await crud.create_message(db, user_id=current_user.id, text=message.text)
    await manager.send_to_user(current_user.id, realtime.message_frame(db_message))
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

    return await crud.get_messages_for_user(
        db,
        user_id=current_user.id,
        limit=limit,
        before=before,
        before_id=before_id,
    )


@router.delete("/{message_id}")
async def delete_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    result = await crud.delete_message(db, message_id=message_id, user_id=current_user.id)
    if not result:
        # "Not found" and "not yours" are deliberately one answer (gap S2), and a
        # delete that changed nothing tells the sockets nothing.
        raise HTTPException(status_code=404, detail="Message not found or not yours")

    await manager.send_to_user(
        current_user.id, realtime.message_deleted_frame(message_id, current_user.id)
    )
    return {"detail": "Message deleted"}
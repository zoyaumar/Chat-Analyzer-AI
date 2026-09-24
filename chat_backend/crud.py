"""The shared service layer: every read and write of a message (gaps B12/Q38).

Both transports go through here — the REST routes and the WebSocket handler — so
a message created over HTTP and one created over the socket cannot drift apart,
and neither transport keeps its own copy of the rules. Nothing in this module
knows about HTTP, status codes or frames: rejecting a lone pagination cursor, or
deciding what a client receives, is the transport's job.
"""

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend import models


async def create_message(db: AsyncSession, *, user_id: int, text: str) -> models.Message:
    """Persist `text` for `user_id` and return the stored row (id + timestamp set)."""
    message = models.Message(user_id=user_id, text=text)
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def get_messages_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int = 100,
    before: datetime | None = None,
    before_id: int | None = None,
) -> list[models.Message]:
    """One chronological page of `user_id`'s messages, oldest first.

    `before`/`before_id` are the keyset cursor for older pages and belong
    together; a caller that receives only one of them must reject the request
    before getting here.
    """
    query = select(models.Message).where(models.Message.user_id == user_id)
    if before is not None and before_id is not None:
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
    # `ORDER BY … DESC LIMIT n` yields the newest n rows; the API hands back a
    # page in reading order, oldest first.
    messages = list(result.scalars().all())
    messages.reverse()
    return messages


async def delete_message(db: AsyncSession, *, message_id: int, user_id: int) -> bool:
    """Delete `message_id` when it belongs to `user_id`; report whether it did.

    No such message and someone else's message are the same answer (`False`), so
    the result cannot be used to discover which ids exist (gap S2).
    """
    result = await db.execute(
        select(models.Message).where(
            models.Message.id == message_id,
            models.Message.user_id == user_id,
        )
    )
    message = result.scalars().first()
    if message is None:
        return False
    await db.delete(message)
    await db.commit()
    return True
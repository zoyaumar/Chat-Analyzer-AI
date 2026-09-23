from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend import models, schemas
from chat_backend.ai_utils import analyze_sentiment, summarize_text
from chat_backend.auth_utils import get_current_user
from chat_backend.database import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.post("/sentiment")
def sentiment_analysis(
    payload: schemas.SentimentRequest,
    current_user: models.User = Depends(get_current_user),
):
    return analyze_sentiment(payload.text)

@router.get("/daily")
async def daily_summary(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Aware UTC boundary so a naive/aware mismatch can't shift "today" (gap B7).
    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    result = await db.execute(
        select(models.Message).where(
            models.Message.timestamp >= start_of_day,
            models.Message.user_id == current_user.id,
        )
    )
    messages = result.scalars().all()

    if not messages:
        raise HTTPException(status_code=404, detail="No messages today")

    full_text = " ".join(msg.text for msg in messages)
    summary = summarize_text(full_text)
    return {"date": str(today), "summary": summary}

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend import models
from chat_backend.ai_utils import analyze_sentiment, summarize_text
from chat_backend.auth_utils import get_current_user
from chat_backend.database import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.post("/sentiment")
def sentiment_analysis(
    text: str,
    current_user: models.User = Depends(get_current_user)
):
    return analyze_sentiment(text)

@router.get("/daily")
async def daily_summary(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    today = datetime.utcnow().date()
    result = await db.execute(
        select(models.Message).where(
            models.Message.timestamp >= today,
            models.Message.user_id == current_user.id,
        )
    )
    messages = result.scalars().all()

    if not messages:
        raise HTTPException(status_code=404, detail="No messages today")

    full_text = " ".join(msg.text for msg in messages)
    summary = summarize_text(full_text)
    return {"date": str(today), "summary": summary}

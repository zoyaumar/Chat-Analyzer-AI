from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from .. import models, schemas
from ..database import get_db
from ..auth_utils import get_current_user
from ..ai_utils import analyze_sentiment, summarize_text

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.post("/sentiment")
def sentiment_analysis(
    text: str,
    current_user: models.User = Depends(get_current_user)
):
    return analyze_sentiment(text)

@router.get("/daily")
def daily_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    today = datetime.utcnow().date()
    messages = db.query(models.Message).filter(
        models.Message.timestamp >= today
    ).all()

    if not messages:
        raise HTTPException(status_code=404, detail="No messages today")

    full_text = " ".join([msg.text for msg in messages])
    summary = summarize_text(full_text)
    return {"date": str(today), "summary": summary}

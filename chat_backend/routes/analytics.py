import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Numeric, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend import models, schemas
from chat_backend.ai_utils import ModelUnavailableError, analyze_sentiment, summarize_text
from chat_backend.auth_utils import get_current_user
from chat_backend.database import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/sentiment", response_model=schemas.SentimentResult)
def sentiment_analysis(
    payload: schemas.SentimentRequest,
    current_user: models.User = Depends(get_current_user),
):
    """Score ad-hoc text (sync: FastAPI runs it in the threadpool).

    A model that cannot load is a `503`, not a `500`: the service is
    reachable but this capability is not, which is exactly what a client needs
    to know to retry later instead of blaming the request.
    """
    try:
        return analyze_sentiment(payload.text)
    except ModelUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/daily", response_model=schemas.DailySummary)
async def daily_summary(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Summarise the caller's messages from today (UTC).

    The stored text is bounded per message but a day of it is not, so
    `summarize_text` chunks internally and never overshoots the model's
    token limit.
    """
    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)
    result = await db.execute(
        select(models.Message)
        .where(
            models.Message.timestamp >= start_of_day,
            models.Message.timestamp < end_of_day,
            models.Message.user_id == current_user.id,
        )
        .order_by(models.Message.timestamp)
    )
    messages = result.scalars().all()

    if not messages:
        raise HTTPException(status_code=404, detail="No messages today")

    full_text = " ".join(msg.text for msg in messages)
    try:
        # Off the event loop: the pipeline call is blocking CPU work, and a busy
        # day is several sequential model calls. Called straight, it
        # froze every other request on this worker — chat, the WebSocket and the
        # health probes included. The write path already does this.
        summary = await asyncio.to_thread(summarize_text, full_text)
    except ModelUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"date": str(today), "summary": summary}


@router.get("/sentiment/timeline", response_model=schemas.SentimentTimeline)
async def sentiment_timeline(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """The caller's sentiment over the last `days` UTC days.

    Every stored score is read back — no inference runs on a read path
    — so this is a plain aggregate over `message_sentiment`, and each row carries
    the model that produced it. Days with no activity are omitted rather
    than returned as zeros, so the client can draw a line without inventing
    points. Messages whose scoring failed count in `messages` but not in
    `positive`/`negative` or `avg_score`.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    # `timestamptz` + explicit UTC: the grouping does not depend on the server's
    # `TimeZone` setting.
    day = func.date(func.timezone("UTC", models.Message.timestamp)).label("day")
    result = await db.execute(
        select(
            day,
            func.count(models.Message.id).label("messages"),
            func.coalesce(
                func.sum(case((models.MessageSentiment.label == "POSITIVE", 1), else_=0)),
                0,
            ).label("positive"),
            func.coalesce(
                func.sum(case((models.MessageSentiment.label == "NEGATIVE", 1), else_=0)),
                0,
            ).label("negative"),
            # `avg()` over float8 returns double precision, and PostgreSQL has no
            # `round(double precision, int)`; casting to numeric first keeps both
            # databases' behaviour identical.
            func.coalesce(
                func.round(
                    func.cast(func.avg(models.MessageSentiment.score), Numeric), 4
                ),
                0,
            ).label("avg_score"),
        )
        .join(
            models.MessageSentiment,
            models.MessageSentiment.message_id == models.Message.id,
            isouter=True,
        )
        .where(
            models.Message.user_id == current_user.id,
            models.Message.timestamp >= since,
        )
        .group_by(day)
        .order_by(day)
    )
    return {
        "days": days,
        "timeline": [
            {
                "date": str(row.day),
                "messages": row.messages,
                "positive": row.positive,
                "negative": row.negative,
                "avg_score": float(row.avg_score),
            }
            for row in result.all()
        ],
    }

import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from chat_backend.database import get_db
from chat_backend.routes import analytics, messages, users, websocket

app = FastAPI(
    title="Chat Analyzer AI",
    description="Backend API for chat storage and analysis",
    version="0.1.0",
)

# Single origin in development (Vite proxies to FastAPI); the CORS middleware is
# removed entirely once the single-origin build lands (gap S4/F15).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(messages.router)
app.include_router(analytics.router)
app.include_router(websocket.router)

logger = logging.getLogger("uvicorn.error")


@app.get("/test-db")
async def test_db(db: AsyncSession = Depends(get_db)):
    result = (await db.execute(text("SELECT 1"))).scalar()
    return {"db_result": result}


@app.get("/")
async def read_root():
    return {"message": "Welcome to Chat Analyzer API with AI!"}

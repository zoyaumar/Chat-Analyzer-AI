import traceback
from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from typing import List
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from chat_backend.auth_utils import ALGORITHM, SECRET_KEY, get_current_user
from chat_backend.routes import analytics, websocket
from . import models, schemas, database
from .database import get_db, engine
from .routes import users, messages
from fastapi.middleware.cors import CORSMiddleware

import logging

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(
    title="Chat Analyzer AI",
    description="Backend API for chat storage and analysis",
    version="0.1.0"
)

origins = [
    "http://localhost:5173",  # Vite default
    "http://localhost:3000",  # React CRA default
    "http://127.0.0.1:8000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change "*" to specific origins in production
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"],  
)

app.include_router(users.router)
app.include_router(messages.router)
app.include_router(analytics.router)
app.include_router(websocket.router)

logger = logging.getLogger("uvicorn.error")  
logger.info("App is starting!")



# # Dependency
# def get_db():
#     db = database.SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()


# # --- Global Exception Handler ---
# @app.exception_handler(Exception)
# async def global_exception_handler(request: Request, exc: Exception):
#     tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
#     logger.error(f"Unhandled error: {exc}\n{tb_str}")  # logs to terminal
#     return JSONResponse(
#         status_code=500,
#         content={"detail": str(exc)},  # sends error back to browser
#     )


@app.get("/test-db")
def test_db(db: Session = Depends(get_db)):
    result = db.execute(text("SELECT 1")).scalar()
    print("DB test result:", result)  
    return {"db_result": result}

@app.get("/")
def read_root():
    logger.info("working")
    print("working", flush=True)
    return {"message": "Welcome to Chat Analyzer API with AI!"}

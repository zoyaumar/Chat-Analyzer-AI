import traceback
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from . import models, schemas, database
from .database import get_db, engine
from .routes import users, messages
import logging

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(
    title="Chat Analyzer AI",
    description="Backend API for chat storage and analysis",
    version="0.1.0"
    )

app.include_router(users.router)
app.include_router(messages.router)

logger = logging.getLogger("uvicorn.error")  # this is Uvicorn’s error logger
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

# @app.post("/register")
# def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
#     db_user = models.User(username=user.username, password_hash=user.password_hash)
#     db.add(db_user)
#     db.commit()
#     db.refresh(db_user)
#     return {"id": db_user.id, "username": db_user.username}

# @app.post("/send_message")
# def send_message(msg: schemas.MessageCreate, db: Session = Depends(get_db)):
#     db_msg = models.Message(user_id=msg.user_id, text=msg.text)
#     db.add(db_msg)
#     db.commit()
#     db.refresh(db_msg)
#     return db_msg

# @app.get("/messages", response_model=list[schemas.MessageOut])
# def get_messages(db: Session = Depends(get_db)):
#     messages = db.query(models.Message).all()
#     return messages

@app.get("/test-db")
def test_db(db: Session = Depends(get_db)):
    result = db.execute(text("SELECT 1")).scalar()
    print("DB test result:", result)  
    return {"db_result": result}

@app.get("/")
def read_root():
    logger.info("working")
    print("working", flush=True)
    return {"message": "Hello, FastAPI is working!"}

logger.info("working1")
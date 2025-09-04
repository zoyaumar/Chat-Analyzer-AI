import traceback
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from chat_backend.routes import analytics
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
app.include_router(analytics.router)

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

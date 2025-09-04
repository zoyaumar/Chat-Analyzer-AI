from pydantic import BaseModel
from datetime import datetime

class UserCreate(BaseModel):
    username: str
    password_hash: str

class MessageCreate(BaseModel):
    user_id: int
    text: str

class MessageOut(BaseModel):
    id: int
    user_id: int
    text: str
    timestamp: datetime

    class Config:
        orm_mode = True

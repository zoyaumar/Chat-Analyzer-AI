from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ======================
# Users
# ======================
class UserBase(BaseModel):
    username: str

# For registration (client sends plain password)
class UserCreate(UserBase):
    password: str

# For returning safe user data
class UserOut(UserBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ======================
# Authentication
# ======================
class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    sub: str | None = None


# ======================
# Messages
# ======================
class MessageBase(BaseModel):
    text: str

class MessageCreate(MessageBase):
    text: str = Field(max_length=4000)

class MessageOut(MessageBase):
    id: int
    user_id: int
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)

class MessageWithUser(MessageOut):
    user: UserOut


# ======================
# Analytics
# ======================
class SentimentResult(BaseModel):
    label: str
    score: float


class DailySummary(BaseModel):
    date: str
    summary: str


class SentimentRequest(BaseModel):
    text: str = Field(max_length=4000)

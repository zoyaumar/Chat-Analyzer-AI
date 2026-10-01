from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --- Credential policy (gap S6) -------------------------------------------
# Registration used to accept a single character as a username and any Unicode
# string as a password. These bounds are the policy; the response to a
# violation is always `422` with the offending field named.
USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 32
# Letters, digits, and the three separators that turn up in real handles —
# nothing that needs escaping in a URL, a log line or a mention.
USERNAME_PATTERN = r"^[A-Za-z0-9._-]+$"
PASSWORD_MIN_LENGTH = 8
# bcrypt is no longer the hasher that *writes* passwords — argon2id is (gap S10)
# — but it still has to *verify* every password registered before the migration,
# and bcrypt 5.0.0 raises `ValueError` on input over 72 bytes instead of truncating
# it. Keeping registration inside that limit means both hashers accept exactly the
# same credentials: a long password would be unverifiable rather than merely
# collision-prone (the old `passlib` stack truncated silently, so `"x" * 80` and
# `"x" * 72 + "yyyy"` were the same credential). It also bounds the cost of hashing
# attacker-sized input. A byte cap, not a character cap — 20 emoji are already
# 80 bytes (gap S6).
PASSWORD_MAX_BYTES = 72


# ======================
# Users
# ======================
class UserBase(BaseModel):
    username: str

# For registration (client sends plain password)
class UserCreate(UserBase):
    """The registration payload — the only place the policy applies (gap S6).

    The constraints live here rather than on `UserBase` on purpose: `UserOut`
    inherits from it and must keep serialising accounts that predate the policy.
    An over-strict *response* model would turn a legacy row into a 500, whereas
    an over-strict request model is exactly the point.
    """

    username: str = Field(
        min_length=USERNAME_MIN_LENGTH,
        max_length=USERNAME_MAX_LENGTH,
        pattern=USERNAME_PATTERN,
    )
    password: str = Field(min_length=PASSWORD_MIN_LENGTH)

    @field_validator("password")
    @classmethod
    def _password_fits_bcrypt(cls, value: str) -> str:
        """Refuse a password the legacy hasher could not accept (gap S6)."""
        if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
            raise ValueError(
                f"Password must be at most {PASSWORD_MAX_BYTES} bytes"
            )
        return value

# For returning safe user data
class UserOut(UserBase):
    id: int
    # Account age, so a client can say when an account was created (gap D5).
    created_at: datetime

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


class SentimentDay(BaseModel):
    """One UTC day of activity: counts plus the mean score of the scored messages."""

    date: str
    messages: int
    positive: int
    negative: int
    avg_score: float


class SentimentTimeline(BaseModel):
    """Sentiment over time for one user, oldest day first (gap A3)."""

    days: int
    timeline: list[SentimentDay]

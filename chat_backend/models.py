from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, relationship
from sqlalchemy.sql import func

from .database import Base


class User(Base):
    __tablename__ = "users"

    # `Mapped[]` annotations keep mypy honest about instance-level types
    # (`user.id` is an `int`, not a `Column`); the values stay classic
    # `Column(...)` so the schema and the migration do not change (gap T3).
    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    username: Mapped[str] = Column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = Column(String, nullable=False)

    # One-to-many relationship with messages
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="user")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    text: Mapped[str] = Column(String, nullable=False)
    timestamp: Mapped[datetime] = Column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # Link back to User
    user: Mapped["User"] = relationship("User", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_user_id_timestamp_desc", user_id, timestamp.desc()),
    )


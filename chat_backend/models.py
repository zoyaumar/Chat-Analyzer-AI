from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .database import Base


class User(Base):
    __tablename__ = "users"

    # `Mapped[]` annotations keep mypy honest about instance-level types
    # (`user.id` is an `int`, not a `Column`); the values stay classic
    # `Column(...)` so the schema and the migration do not change.
    # The nullable additions use `mapped_column`: there the annotation *is* the
    # nullability, so `Mapped[datetime | None]` stays honest instead of being
    # flattened to `datetime` by the plugin's `Column` inference.
    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    username: Mapped[str] = Column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = Column(String, nullable=False)
    # Account-age bookkeeping: set by the database on insert, by
    # SQLAlchemy on the next ORM update.
    created_at: Mapped[datetime] = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # One-to-many relationship with messages. `passive_deletes=True` + the
    # FK's ON DELETE CASCADE: deleting a user never loads the messages,
    # the database removes them in the same statement.
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="user", passive_deletes=True
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 4000 matches `MessageCreate.text`'s Pydantic limit.
    text: Mapped[str] = Column(String(4000), nullable=False)
    timestamp: Mapped[datetime] = Column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Link back to User
    user: Mapped["User"] = relationship("User", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_user_id_timestamp_desc", user_id, timestamp.desc()),
    )


class MessageSentiment(Base):
    """One persisted score per message.

    Written once, at message creation, in the same transaction as the message —
    the API reads it back instead of re-running inference, and `model_name` /
    `model_version` say exactly which model produced the number.
    """

    __tablename__ = "message_sentiment"

    message_id: Mapped[int] = Column(
        Integer, ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    label: Mapped[str] = Column(String(32), nullable=False)
    # The plugin cannot match `Float` (generic `Column[_N]`) to `Mapped[float]`;
    # a targeted ignore keeps the ORM `__init__` signature available, which a
    # `mapped_column` here would drop.
    score: Mapped[float] = Column(Float, nullable=False)  # type: ignore[misc]
    model_name: Mapped[str] = Column(String(255), nullable=False)
    model_version: Mapped[str] = Column(String(64), nullable=False)
    created_at: Mapped[datetime] = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RefreshToken(Base):
    """A revocable session — the stored half of the refresh flow.

    Only the SHA-256 hash of the token is stored: a leaked database row is not
    a usable credential, and rotation deletes the row on every use, so replaying
    a copy that the real client has already refreshed finds nothing.

    `user_id` cascades with the account: deleting a user takes their sessions
    with it, in the same `DELETE` as the messages.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    token_hash: Mapped[str] = Column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False)


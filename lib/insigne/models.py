from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    confirmation_tokens: Mapped[list["ConfirmationToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    progress_entries: Mapped[list["ProgressEntry"]] = relationship(
        foreign_keys="ProgressEntry.user_id", back_populates="user"
    )
    signoffs_given: Mapped[list["ProgressEntry"]] = relationship(
        foreign_keys="ProgressEntry.signed_off_by_id", back_populates="signed_off_by"
    )
    signoff_requests: Mapped[list["SignoffRequest"]] = relationship(back_populates="mentor")


class ConfirmationToken(Base):
    __tablename__ = "confirmation_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    user: Mapped["User"] = relationship(back_populates="confirmation_tokens")


class ProgressEntry(Base):
    __tablename__ = "progress_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    badge_slug: Mapped[str] = mapped_column(String, nullable=False)
    level_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="in_progress")
    signed_off_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    user: Mapped["User"] = relationship(
        foreign_keys=[user_id], back_populates="progress_entries"
    )
    signed_off_by: Mapped["User | None"] = relationship(
        foreign_keys=[signed_off_by_id], back_populates="signoffs_given"
    )
    signoff_requests: Mapped[list["SignoffRequest"]] = relationship(
        back_populates="progress_entry", cascade="all, delete-orphan"
    )


class SignoffRequest(Base):
    __tablename__ = "signoff_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    progress_entry_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("progress_entries.id"), nullable=False, index=True
    )
    mentor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    progress_entry: Mapped["ProgressEntry"] = relationship(back_populates="signoff_requests")
    mentor: Mapped["User"] = relationship(back_populates="signoff_requests")

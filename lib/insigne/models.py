from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
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
    email: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    @property
    def is_admin(self) -> bool:
        from insigne.config import config
        return bool(self.email and self.email.lower() in config.admins)

    @property
    def is_leader(self) -> bool:
        return (
            any(m.role == "groepsleider" and m.approved and not m.withdrawn
                for m in self.group_memberships)
            or any(m.role == "speltakleider" and m.approved and not m.withdrawn
                   for m in self.speltak_memberships)
        )

    created_by: Mapped["User | None"] = relationship(
        foreign_keys=[created_by_id], remote_side="User.id", back_populates="managed_scouts"
    )
    managed_scouts: Mapped[list["User"]] = relationship(
        foreign_keys=[created_by_id], back_populates="created_by"
    )
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
    group_memberships: Mapped[list["GroupMembership"]] = relationship(
        foreign_keys="GroupMembership.user_id", back_populates="user", cascade="all, delete-orphan"
    )
    speltak_memberships: Mapped[list["SpeltakMembership"]] = relationship(
        foreign_keys="SpeltakMembership.user_id", back_populates="user", cascade="all, delete-orphan"
    )
    membership_requests: Mapped[list["MembershipRequest"]] = relationship(
        foreign_keys="MembershipRequest.user_id", back_populates="user", cascade="all, delete-orphan"
    )


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
    mentor_comment: Mapped[str | None] = mapped_column(String, nullable=True)
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
    signoff_rejections: Mapped[list["SignoffRejection"]] = relationship(
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


class SignoffRejection(Base):
    __tablename__ = "signoff_rejections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    progress_entry_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("progress_entries.id"), nullable=False, index=True
    )
    mentor_name: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    progress_entry: Mapped["ProgressEntry"] = relationship(back_populates="signoff_rejections")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    created_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    speltakken: Mapped[list["Speltak"]] = relationship(
        back_populates="group", cascade="all, delete-orphan",
        order_by="Speltak.name"
    )
    memberships: Mapped[list["GroupMembership"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    membership_requests: Mapped[list["MembershipRequest"]] = relationship(
        foreign_keys="MembershipRequest.group_id",
        back_populates="group",
        cascade="all, delete-orphan",
    )


class Speltak(Base):
    __tablename__ = "speltakken"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    peer_signoff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    group: Mapped["Group"] = relationship(back_populates="speltakken")
    memberships: Mapped[list["SpeltakMembership"]] = relationship(
        back_populates="speltak", cascade="all, delete-orphan"
    )
    membership_requests: Mapped[list["MembershipRequest"]] = relationship(
        foreign_keys="MembershipRequest.speltak_id",
        back_populates="speltak",
        cascade="all, delete-orphan",
    )


class GroupMembership(Base):
    __tablename__ = "group_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)  # groepsleider | member
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    withdrawn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    invited_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    user: Mapped["User"] = relationship(foreign_keys=[user_id], back_populates="group_memberships")
    group: Mapped["Group"] = relationship(back_populates="memberships")
    invited_by: Mapped["User | None"] = relationship(foreign_keys=[invited_by_id])


class SpeltakMembership(Base):
    __tablename__ = "speltak_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    speltak_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("speltakken.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)  # speltakleider | scout
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    withdrawn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    invited_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    user: Mapped["User"] = relationship(foreign_keys=[user_id], back_populates="speltak_memberships")
    speltak: Mapped["Speltak"] = relationship(back_populates="memberships")
    invited_by: Mapped["User | None"] = relationship(foreign_keys=[invited_by_id])


class MembershipRequest(Base):
    __tablename__ = "membership_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    group_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("groups.id"), nullable=True, index=True
    )
    speltak_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("speltakken.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending | approved | rejected
    reviewed_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    user: Mapped["User"] = relationship(foreign_keys=[user_id], back_populates="membership_requests")
    group: Mapped["Group | None"] = relationship(
        foreign_keys=[group_id], back_populates="membership_requests"
    )
    speltak: Mapped["Speltak | None"] = relationship(
        foreign_keys=[speltak_id], back_populates="membership_requests"
    )

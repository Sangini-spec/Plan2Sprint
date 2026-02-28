from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization
    from .notification import NotificationPreference
    from .audit_log import AuditLogEntry


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(
        String, name="full_name", nullable=False
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(
        String, name="avatar_url", nullable=True
    )
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="DEVELOPER"
    )
    supabase_user_id: Mapped[str] = mapped_column(
        String, name="supabase_user_id", unique=True, nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("organizations.id"),
        name="organization_id",
        nullable=False,
    )
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, name="onboarding_completed", nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_at", server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        name="updated_at",
        server_default=func.now(),
        onupdate=func.now(),
    )

    # -- relationships --
    organization: Mapped["Organization"] = relationship(
        back_populates="users"
    )
    notification_prefs: Mapped[List["NotificationPreference"]] = relationship(
        back_populates="user"
    )
    audit_log_entries: Mapped[List["AuditLogEntry"]] = relationship(
        back_populates="actor"
    )

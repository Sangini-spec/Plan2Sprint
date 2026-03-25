from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _default_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=7)


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    organization_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("organizations.id"),
        name="organization_id",
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="developer"
    )
    token: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, default=_generate_token
    )
    invited_by: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_default_expiry
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="accepted_at", nullable=True
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
        back_populates="invitations"
    )

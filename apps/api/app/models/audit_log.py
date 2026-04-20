from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization
    from .user import User


class AuditLogEntry(Base):
    __tablename__ = "audit_log_entries"
    __table_args__ = (
        Index(
            "ix_audit_log_entries_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_audit_log_entries_org_event_type",
            "organization_id",
            "event_type",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    organization_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("organizations.id"),
        name="organization_id",
        nullable=False,
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(25),
        ForeignKey("users.id"),
        name="actor_id",
        nullable=True,  # Nullable for system-initiated events (daily digests, nudges)
    )
    actor_role: Mapped[str] = mapped_column(
        String(50), name="actor_role", nullable=False
    )
    event_type: Mapped[str] = mapped_column(
        String, name="event_type", nullable=False
    )
    resource_type: Mapped[str] = mapped_column(
        String, name="resource_type", nullable=False
    )
    resource_id: Mapped[str] = mapped_column(
        String, name="resource_id", nullable=False
    )
    before_state: Mapped[Optional[Any]] = mapped_column(
        JSON, name="before_state", nullable=True
    )
    after_state: Mapped[Optional[Any]] = mapped_column(
        JSON, name="after_state", nullable=True
    )
    source_channel: Mapped[Optional[str]] = mapped_column(
        String, name="source_channel", nullable=True
    )
    success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    metadata_: Mapped[Optional[Any]] = mapped_column(
        "metadata", JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_at", server_default=func.now()
    )

    # -- relationships --
    organization: Mapped["Organization"] = relationship(
        back_populates="audit_log_entries"
    )
    actor: Mapped["User"] = relationship(
        back_populates="audit_log_entries"
    )

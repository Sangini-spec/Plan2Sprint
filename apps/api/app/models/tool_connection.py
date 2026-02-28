from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    JSON,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization


class ToolConnection(Base):
    __tablename__ = "tool_connections"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "source_tool", name="uq_tool_connections_org_source"
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
    source_tool: Mapped[str] = mapped_column(
        String(50), name="source_tool", nullable=False
    )
    access_token: Mapped[str] = mapped_column(
        String, name="access_token", nullable=False
    )
    refresh_token: Mapped[Optional[str]] = mapped_column(
        String, name="refresh_token", nullable=True
    )
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="token_expires_at", nullable=True
    )
    webhook_secret: Mapped[Optional[str]] = mapped_column(
        String, name="webhook_secret", nullable=True
    )
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="last_sync_at", nullable=True
    )
    sync_status: Mapped[str] = mapped_column(
        String, name="sync_status", nullable=False, default="idle"
    )
    config: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
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
        back_populates="connections"
    )

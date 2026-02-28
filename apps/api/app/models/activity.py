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
    from .team_member import TeamMember


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    __table_args__ = (
        Index(
            "ix_activity_events_org_member_occurred",
            "organization_id",
            "team_member_id",
            "occurred_at",
        ),
        Index(
            "ix_activity_events_org_occurred",
            "organization_id",
            "occurred_at",
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
    team_member_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("team_members.id"),
        name="team_member_id",
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(50), name="event_type", nullable=False
    )
    source_tool: Mapped[str] = mapped_column(
        String(50), name="source_tool", nullable=False
    )
    external_id: Mapped[Optional[str]] = mapped_column(
        String, name="external_id", nullable=True
    )
    linked_ticket_id: Mapped[Optional[str]] = mapped_column(
        String, name="linked_ticket_id", nullable=True
    )
    metadata_: Mapped[Optional[Any]] = mapped_column(
        "metadata", JSON, nullable=True
    )
    is_after_hours: Mapped[bool] = mapped_column(
        Boolean, name="is_after_hours", nullable=False, default=False
    )
    is_weekend: Mapped[bool] = mapped_column(
        Boolean, name="is_weekend", nullable=False, default=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="occurred_at", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_at", server_default=func.now()
    )

    # -- relationships --
    organization: Mapped["Organization"] = relationship(
        back_populates="activity_events"
    )
    team_member: Mapped["TeamMember"] = relationship(
        back_populates="activity_events"
    )

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .user import User
    from .team_member import TeamMember
    from .work_item import WorkItem
    from .iteration import Iteration
    from .repository import Repository
    from .sprint_plan import SprintPlan
    from .standup import StandupReport, TeamStandupDigest
    from .analytics import HealthSignal, BurnoutAlert
    from .retrospective import Retrospective
    from .audit_log import AuditLogEntry
    from .activity import ActivityEvent
    from .tool_connection import ToolConnection
    from .invitation import Invitation


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(
        String, nullable=False, default="America/New_York"
    )
    working_hours_start: Mapped[str] = mapped_column(
        String, name="working_hours_start", nullable=False, default="09:00"
    )
    working_hours_end: Mapped[str] = mapped_column(
        String, name="working_hours_end", nullable=False, default="17:00"
    )
    standup_time: Mapped[str] = mapped_column(
        String, name="standup_time", nullable=False, default="09:30"
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
    users: Mapped[List["User"]] = relationship(back_populates="organization")
    team_members: Mapped[List["TeamMember"]] = relationship(
        back_populates="organization"
    )
    work_items: Mapped[List["WorkItem"]] = relationship(
        back_populates="organization"
    )
    iterations: Mapped[List["Iteration"]] = relationship(
        back_populates="organization"
    )
    repositories: Mapped[List["Repository"]] = relationship(
        back_populates="organization"
    )
    sprint_plans: Mapped[List["SprintPlan"]] = relationship(
        back_populates="organization"
    )
    standup_reports: Mapped[List["StandupReport"]] = relationship(
        back_populates="organization"
    )
    team_digests: Mapped[List["TeamStandupDigest"]] = relationship(
        back_populates="organization"
    )
    health_signals: Mapped[List["HealthSignal"]] = relationship(
        back_populates="organization"
    )
    burnout_alerts: Mapped[List["BurnoutAlert"]] = relationship(
        back_populates="organization"
    )
    retrospectives: Mapped[List["Retrospective"]] = relationship(
        back_populates="organization"
    )
    audit_log_entries: Mapped[List["AuditLogEntry"]] = relationship(
        back_populates="organization"
    )
    activity_events: Mapped[List["ActivityEvent"]] = relationship(
        back_populates="organization"
    )
    connections: Mapped[List["ToolConnection"]] = relationship(
        back_populates="organization"
    )
    invitations: Mapped[List["Invitation"]] = relationship(
        back_populates="organization"
    )

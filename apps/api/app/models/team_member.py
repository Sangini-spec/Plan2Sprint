from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    String,
    Float,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization
    from .work_item import WorkItem
    from .sprint_plan import PlanAssignment
    from .standup import StandupReport
    from .analytics import VelocityProfile, HealthSignal, BurnoutAlert
    from .activity import ActivityEvent
    from .repository import Commit, PullRequest


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "external_id", name="uq_team_members_org_ext"
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
    imported_project_id: Mapped[Optional[str]] = mapped_column(
        String(25),
        ForeignKey("imported_projects.id"),
        name="imported_project_id",
        nullable=True,
    )
    external_id: Mapped[str] = mapped_column(
        String, name="external_id", nullable=False
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(
        String, name="display_name", nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(30), name="role", nullable=False, default="developer",
        server_default="developer",
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(
        String, name="avatar_url", nullable=True
    )
    skill_tags: Mapped[List[str]] = mapped_column(
        ARRAY(String), name="skill_tags", default=list
    )
    default_capacity: Mapped[float] = mapped_column(
        Float, name="default_capacity", nullable=False, default=40
    )
    slack_user_id: Mapped[Optional[str]] = mapped_column(
        String, name="slack_user_id", nullable=True
    )
    teams_user_id: Mapped[Optional[str]] = mapped_column(
        String, name="teams_user_id", nullable=True
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
        back_populates="team_members"
    )
    work_items: Mapped[List["WorkItem"]] = relationship(
        back_populates="assignee"
    )
    plan_assignments: Mapped[List["PlanAssignment"]] = relationship(
        back_populates="team_member"
    )
    standup_reports: Mapped[List["StandupReport"]] = relationship(
        back_populates="team_member"
    )
    velocity_profiles: Mapped[List["VelocityProfile"]] = relationship(
        back_populates="team_member"
    )
    health_signals: Mapped[List["HealthSignal"]] = relationship(
        back_populates="team_member"
    )
    burnout_alerts: Mapped[List["BurnoutAlert"]] = relationship(
        back_populates="team_member"
    )
    activity_events: Mapped[List["ActivityEvent"]] = relationship(
        back_populates="team_member"
    )
    commits: Mapped[List["Commit"]] = relationship(
        back_populates="author"
    )
    pull_requests: Mapped[List["PullRequest"]] = relationship(
        back_populates="author"
    )

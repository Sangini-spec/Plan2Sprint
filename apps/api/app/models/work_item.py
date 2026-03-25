from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    String,
    Integer,
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
    from .iteration import Iteration
    from .team_member import TeamMember
    from .imported_project import ImportedProject
    from .project_phase import ProjectPhase
    from .sprint_plan import PlanAssignment
    from .repository import PullRequest


class WorkItem(Base):
    __tablename__ = "work_items"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "external_id",
            "source_tool",
            name="uq_work_items_org_ext_source",
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
    external_id: Mapped[str] = mapped_column(
        String, name="external_id", nullable=False
    )
    source_tool: Mapped[str] = mapped_column(
        String(50), name="source_tool", nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="BACKLOG"
    )
    story_points: Mapped[Optional[float]] = mapped_column(
        Float, name="story_points", nullable=True
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    type: Mapped[str] = mapped_column(
        String, nullable=False, default="story"
    )
    labels: Mapped[List[str]] = mapped_column(
        ARRAY(String), default=list
    )
    acceptance_criteria: Mapped[Optional[str]] = mapped_column(
        String, name="acceptance_criteria", nullable=True
    )
    epic_id: Mapped[Optional[str]] = mapped_column(
        String, name="epic_id", nullable=True
    )
    planned_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="planned_start", nullable=True
    )
    planned_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="planned_end", nullable=True
    )
    iteration_id: Mapped[Optional[str]] = mapped_column(
        String(25),
        ForeignKey("iterations.id"),
        name="iteration_id",
        nullable=True,
    )
    assignee_id: Mapped[Optional[str]] = mapped_column(
        String(25),
        ForeignKey("team_members.id"),
        name="assignee_id",
        nullable=True,
    )
    imported_project_id: Mapped[Optional[str]] = mapped_column(
        String(25),
        ForeignKey("imported_projects.id"),
        name="imported_project_id",
        nullable=True,
    )
    source_status: Mapped[Optional[str]] = mapped_column(
        String(100), name="source_status", nullable=True
    )
    phase_id: Mapped[Optional[str]] = mapped_column(
        String(25),
        ForeignKey("project_phases.id", ondelete="SET NULL"),
        name="phase_id",
        nullable=True,
    )
    spillover_risk: Mapped[Optional[str]] = mapped_column(
        String(20), name="spillover_risk", nullable=True
    )
    spillover_reason: Mapped[Optional[str]] = mapped_column(
        String, name="spillover_reason", nullable=True
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
        back_populates="work_items"
    )
    iteration: Mapped[Optional["Iteration"]] = relationship(
        back_populates="work_items"
    )
    assignee: Mapped[Optional["TeamMember"]] = relationship(
        back_populates="work_items"
    )
    imported_project: Mapped[Optional["ImportedProject"]] = relationship()
    phase: Mapped[Optional["ProjectPhase"]] = relationship()
    plan_assignments: Mapped[List["PlanAssignment"]] = relationship(
        back_populates="work_item"
    )
    pull_requests: Mapped[List["PullRequest"]] = relationship(
        back_populates="linked_work_item"
    )

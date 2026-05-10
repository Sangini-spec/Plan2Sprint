from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    String,
    Integer,
    Float,
    Boolean,
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
    # Sprint E — PO-controlled visibility on the Project Plan Gantt. When
    # a long project accumulates dozens of completed/legacy features the
    # Gantt becomes unreadable; the PO clicks the trash icon on a row to
    # hide it. The work item itself stays in the DB (for analytics, sprint
    # history, etc.) — this flag only filters it out of the Gantt query.
    # The "Show N hidden" toggle in the header brings them back.
    hidden_from_gantt: Mapped[bool] = mapped_column(
        Boolean,
        name="hidden_from_gantt",
        nullable=False,
        default=False,
        server_default="false",
    )
    # Hotfix 19 — AI-classified phase fallback. Populated by
    # ``services.ai_phase_classifier`` when keyword/board_column rules
    # fail to match a feature. Cached per-feature so we only pay an LLM
    # round-trip the FIRST time a feature can't be matched, and only
    # again when the title or description changes (input hash mismatch).
    # The actual phase resolution chain is:
    #   1. Manual phase_id (PO drag)
    #   2. Rules engine (keyword + board_column)
    #   3. ai_classified_phase_id (this) — semantic understanding
    #   4. Status fallback (terminal -> last work phase, else first)
    ai_classified_phase_id: Mapped[Optional[str]] = mapped_column(
        String(25),
        ForeignKey("project_phases.id", ondelete="SET NULL"),
        name="ai_classified_phase_id",
        nullable=True,
    )
    ai_classified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="ai_classified_at", nullable=True
    )
    ai_classified_input_hash: Mapped[Optional[str]] = mapped_column(
        String(64), name="ai_classified_input_hash", nullable=True
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
    # Hotfix 21 — disambiguate which FK this relationship uses. The
    # ``ai_classified_phase_id`` column added in Hotfix 19 introduced a
    # second FK from work_items → project_phases, which made
    # ``relationship(ProjectPhase)`` ambiguous. Without ``foreign_keys``,
    # SQLAlchemy fails mapper initialisation with "multiple foreign key
    # paths" and EVERY endpoint that touches work_items returns 500.
    # Pinning ``foreign_keys=[phase_id]`` keeps the original meaning of
    # ``feature.phase`` (the manual/rule-resolved phase, not the AI-
    # classified one). The AI-classified phase doesn't need its own
    # ORM relationship — we read the column directly.
    phase: Mapped[Optional["ProjectPhase"]] = relationship(
        foreign_keys=[phase_id]
    )
    plan_assignments: Mapped[List["PlanAssignment"]] = relationship(
        back_populates="work_item"
    )
    pull_requests: Mapped[List["PullRequest"]] = relationship(
        back_populates="linked_work_item"
    )

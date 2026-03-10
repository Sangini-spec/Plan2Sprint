from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import (
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization
    from .iteration import Iteration
    from .imported_project import ImportedProject
    from .work_item import WorkItem
    from .team_member import TeamMember


class SprintPlan(Base):
    __tablename__ = "sprint_plans"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    organization_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("organizations.id"),
        name="organization_id",
        nullable=False,
    )
    project_id: Mapped[Optional[str]] = mapped_column(
        String(25),
        ForeignKey("imported_projects.id"),
        name="project_id",
        nullable=True,
    )
    iteration_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("iterations.id"),
        name="iteration_id",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="GENERATING"
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(
        Float, name="confidence_score", nullable=True
    )
    risk_summary: Mapped[Optional[str]] = mapped_column(
        String, name="risk_summary", nullable=True
    )
    overall_rationale: Mapped[Optional[str]] = mapped_column(
        String, name="overall_rationale", nullable=True
    )
    goal_attainment_confidence: Mapped[Optional[float]] = mapped_column(
        Float, name="goal_attainment_confidence", nullable=True
    )
    total_story_points: Mapped[Optional[float]] = mapped_column(
        Float, name="total_story_points", nullable=True
    )
    unplanned_items: Mapped[Optional[Any]] = mapped_column(
        JSON, name="unplanned_items", nullable=True
    )
    estimated_sprints: Mapped[Optional[int]] = mapped_column(
        Integer, name="estimated_sprints", nullable=True
    )
    estimated_end_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="estimated_end_date", nullable=True
    )
    success_probability: Mapped[Optional[int]] = mapped_column(
        Integer, name="success_probability", nullable=True
    )
    spillover_risk_sp: Mapped[Optional[int]] = mapped_column(
        Integer, name="spillover_risk_sp", nullable=True
    )
    forecast_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="forecast_updated_at", nullable=True
    )
    ai_model_used: Mapped[Optional[str]] = mapped_column(
        String, name="ai_model_used", nullable=True
    )
    tool: Mapped[Optional[str]] = mapped_column(
        String(10), name="tool", nullable=True
    )
    human_edits: Mapped[Optional[Any]] = mapped_column(
        JSON, name="human_edits", nullable=True
    )
    estimated_weeks_total: Mapped[Optional[int]] = mapped_column(
        Integer, name="estimated_weeks_total", nullable=True
    )
    project_completion_summary: Mapped[Optional[str]] = mapped_column(
        String, name="project_completion_summary", nullable=True
    )
    capacity_recommendations: Mapped[Optional[Any]] = mapped_column(
        JSON, name="capacity_recommendations", nullable=True
    )
    rejection_feedback: Mapped[Optional[str]] = mapped_column(
        String, name="rejection_feedback", nullable=True
    )
    approved_by_id: Mapped[Optional[str]] = mapped_column(
        String, name="approved_by_id", nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="approved_at", nullable=True
    )
    synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="synced_at", nullable=True
    )
    undo_available_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="undo_available_until", nullable=True
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
        back_populates="sprint_plans"
    )
    project: Mapped[Optional["ImportedProject"]] = relationship()
    iteration: Mapped["Iteration"] = relationship(
        back_populates="sprint_plans"
    )
    assignments: Mapped[List["PlanAssignment"]] = relationship(
        back_populates="sprint_plan"
    )


class PlanAssignment(Base):
    __tablename__ = "plan_assignments"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    sprint_plan_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("sprint_plans.id"),
        name="sprint_plan_id",
        nullable=False,
    )
    work_item_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("work_items.id"),
        name="work_item_id",
        nullable=False,
    )
    team_member_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("team_members.id"),
        name="team_member_id",
        nullable=False,
    )
    story_points: Mapped[float] = mapped_column(
        Float, name="story_points", nullable=False
    )
    confidence_score: Mapped[float] = mapped_column(
        Float, name="confidence_score", nullable=False
    )
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    risk_flags: Mapped[List[str]] = mapped_column(
        ARRAY(String), name="risk_flags", default=list
    )
    skill_match: Mapped[Optional[Any]] = mapped_column(
        JSON, name="skill_match", nullable=True
    )
    sprint_number: Mapped[Optional[int]] = mapped_column(
        Integer, name="sprint_number", nullable=True, default=1,
    )
    is_human_edited: Mapped[bool] = mapped_column(
        Boolean, name="is_human_edited", nullable=False, default=False
    )
    suggested_priority: Mapped[Optional[int]] = mapped_column(
        Integer, name="suggested_priority", nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_at", server_default=func.now()
    )

    # -- relationships --
    sprint_plan: Mapped["SprintPlan"] = relationship(
        back_populates="assignments"
    )
    work_item: Mapped["WorkItem"] = relationship(
        back_populates="plan_assignments"
    )
    team_member: Mapped["TeamMember"] = relationship(
        back_populates="plan_assignments"
    )

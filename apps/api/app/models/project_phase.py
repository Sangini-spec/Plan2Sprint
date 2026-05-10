from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization
    from .imported_project import ImportedProject


class ProjectPhase(Base):
    __tablename__ = "project_phases"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_project_phases_proj_slug"),
    )

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    organization_id: Mapped[str] = mapped_column(
        String(25), ForeignKey("organizations.id"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(25), ForeignKey("imported_projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(
        String(7), nullable=False, server_default="#6366f1"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # Timeline revamp (Sprint 1): persist computed phase boundaries so the
    # dashboard doesn't have to re-derive them on every page load. Values are
    # written by services.timeline_engine in one of three modes (Raw, AI-Opt,
    # Rebalanced). Nullable because phases for brand-new projects may not have
    # dates yet — the UI renders "TBD" in that case.
    planned_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    planned_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship()
    imported_project: Mapped["ImportedProject"] = relationship()
    rules: Mapped[List["PhaseAssignmentRule"]] = relationship(
        back_populates="phase", cascade="all, delete-orphan"
    )


class PhaseAssignmentRule(Base):
    __tablename__ = "phase_assignment_rules"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    phase_id: Mapped[str] = mapped_column(
        String(25), ForeignKey("project_phases.id", ondelete="CASCADE"), nullable=False
    )
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    phase: Mapped["ProjectPhase"] = relationship(back_populates="rules")

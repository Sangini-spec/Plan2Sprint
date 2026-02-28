from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization
    from .imported_project import ImportedProject
    from .work_item import WorkItem
    from .sprint_plan import SprintPlan


class Iteration(Base):
    __tablename__ = "iterations"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "external_id",
            "source_tool",
            name="uq_iterations_org_ext_source",
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
    name: Mapped[str] = mapped_column(String, nullable=False)
    goal: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="start_date", nullable=False
    )
    end_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="end_date", nullable=False
    )
    state: Mapped[str] = mapped_column(
        String, nullable=False, default="active"
    )
    imported_project_id: Mapped[Optional[str]] = mapped_column(
        String(25),
        ForeignKey("imported_projects.id"),
        name="imported_project_id",
        nullable=True,
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
        back_populates="iterations"
    )
    imported_project: Mapped[Optional["ImportedProject"]] = relationship()
    work_items: Mapped[List["WorkItem"]] = relationship(
        back_populates="iteration"
    )
    sprint_plans: Mapped[List["SprintPlan"]] = relationship(
        back_populates="iteration"
    )

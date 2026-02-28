from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    ForeignKey,
    JSON,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization


class SprintConstraint(Base):
    __tablename__ = "sprint_constraints"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    organization_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("organizations.id"),
        name="organization_id",
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("imported_projects.id"),
        name="project_id",
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(50), name="source", nullable=False
    )
    constraint_data: Mapped[Any] = mapped_column(
        "constraint", JSON, nullable=False
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="applied_at", server_default=func.now()
    )
    expires_after_sprints: Mapped[Optional[int]] = mapped_column(
        Integer, name="expires_after_sprints", nullable=True, default=3
    )
    sprints_applied: Mapped[int] = mapped_column(
        Integer, name="sprints_applied", nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_at", server_default=func.now()
    )

    # -- relationships --
    organization: Mapped["Organization"] = relationship()

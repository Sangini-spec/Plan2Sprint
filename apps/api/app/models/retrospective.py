from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import (
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization


class Retrospective(Base):
    __tablename__ = "retrospectives"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    organization_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("organizations.id"),
        name="organization_id",
        nullable=False,
    )
    iteration_id: Mapped[Optional[str]] = mapped_column(
        String, name="iteration_id", nullable=True
    )
    what_went_well: Mapped[Any] = mapped_column(
        JSON, name="what_went_well", nullable=False
    )
    what_didnt_go_well: Mapped[Any] = mapped_column(
        JSON, name="what_didnt_go_well", nullable=False
    )
    root_cause_analysis: Mapped[Optional[Any]] = mapped_column(
        JSON, name="root_cause_analysis", nullable=True
    )
    failure_classification: Mapped[Optional[str]] = mapped_column(
        String(30), name="failure_classification", nullable=True
    )
    failure_evidence: Mapped[Optional[Any]] = mapped_column(
        JSON, name="failure_evidence", nullable=True
    )
    pattern_detected: Mapped[Optional[bool]] = mapped_column(
        Boolean, name="pattern_detected", nullable=True, default=False
    )
    consecutive_failure_count: Mapped[Optional[int]] = mapped_column(
        Integer, name="consecutive_failure_count", nullable=True, default=0
    )
    feed_forward_signals: Mapped[Optional[Any]] = mapped_column(
        JSON, name="feed_forward_signals", nullable=True
    )
    is_draft: Mapped[bool] = mapped_column(
        Boolean, name="is_draft", nullable=False, default=True
    )
    finalized_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="finalized_at", nullable=True
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
        back_populates="retrospectives"
    )
    action_items: Mapped[List["RetroActionItem"]] = relationship(
        back_populates="retrospective"
    )


class RetroActionItem(Base):
    __tablename__ = "retro_action_items"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    retrospective_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("retrospectives.id"),
        name="retrospective_id",
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    assignee_id: Mapped[Optional[str]] = mapped_column(
        String, name="assignee_id", nullable=True
    )
    due_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="due_date", nullable=True
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="open"
    )
    is_carry_forward: Mapped[bool] = mapped_column(
        Boolean, name="is_carry_forward", nullable=False, default=False
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
    retrospective: Mapped["Retrospective"] = relationship(
        back_populates="action_items"
    )

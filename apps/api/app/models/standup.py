from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import (
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization
    from .team_member import TeamMember


class StandupReport(Base):
    __tablename__ = "standup_reports"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "team_member_id",
            "report_date",
            name="uq_standup_reports_org_member_date",
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
    iteration_id: Mapped[Optional[str]] = mapped_column(
        String, name="iteration_id", nullable=True
    )
    report_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="report_date", nullable=False
    )
    completed_items: Mapped[Any] = mapped_column(
        JSON, name="completed_items", nullable=False
    )
    in_progress_items: Mapped[Any] = mapped_column(
        JSON, name="in_progress_items", nullable=False
    )
    blockers: Mapped[Any] = mapped_column(JSON, nullable=False)
    narrative_text: Mapped[str] = mapped_column(
        String, name="narrative_text", nullable=False
    )
    acknowledged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="acknowledged_at", nullable=True
    )
    developer_note: Mapped[Optional[str]] = mapped_column(
        String, name="developer_note", nullable=True
    )
    is_inactive: Mapped[bool] = mapped_column(
        Boolean, name="is_inactive", nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_at", server_default=func.now()
    )

    # -- relationships --
    organization: Mapped["Organization"] = relationship(
        back_populates="standup_reports"
    )
    team_member: Mapped["TeamMember"] = relationship(
        back_populates="standup_reports"
    )
    blocker_flags: Mapped[List["BlockerFlag"]] = relationship(
        back_populates="standup_report"
    )


class TeamStandupDigest(Base):
    __tablename__ = "team_standup_digests"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "digest_date",
            name="uq_team_standup_digests_org_date",
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
    iteration_id: Mapped[Optional[str]] = mapped_column(
        String, name="iteration_id", nullable=True
    )
    digest_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="digest_date", nullable=False
    )
    sprint_pacing: Mapped[float] = mapped_column(
        Float, name="sprint_pacing", nullable=False
    )
    acknowledged_pct: Mapped[float] = mapped_column(
        Float, name="acknowledged_pct", nullable=False
    )
    sprint_health: Mapped[str] = mapped_column(
        String(50), name="sprint_health", nullable=False
    )
    at_risk_items: Mapped[Any] = mapped_column(
        JSON, name="at_risk_items", nullable=False
    )
    blocker_count: Mapped[int] = mapped_column(
        Integer, name="blocker_count", nullable=False
    )
    summary_text: Mapped[str] = mapped_column(
        String, name="summary_text", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_at", server_default=func.now()
    )

    # -- relationships --
    organization: Mapped["Organization"] = relationship(
        back_populates="team_digests"
    )


class BlockerFlag(Base):
    __tablename__ = "blocker_flags"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    standup_report_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("standup_reports.id"),
        name="standup_report_id",
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    ticket_reference: Mapped[Optional[str]] = mapped_column(
        String, name="ticket_reference", nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="OPEN"
    )
    flagged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="flagged_at", server_default=func.now()
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="resolved_at", nullable=True
    )

    # -- relationships --
    standup_report: Mapped["StandupReport"] = relationship(
        back_populates="blocker_flags"
    )

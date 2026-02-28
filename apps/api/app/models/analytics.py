from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization
    from .team_member import TeamMember


class VelocityProfile(Base):
    __tablename__ = "velocity_profiles"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
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
    planned_sp: Mapped[float] = mapped_column(
        Float, name="planned_sp", nullable=False
    )
    completed_sp: Mapped[float] = mapped_column(
        Float, name="completed_sp", nullable=False
    )
    rolling_average: Mapped[Optional[float]] = mapped_column(
        Float, name="rolling_average", nullable=True
    )
    by_ticket_type: Mapped[Optional[Any]] = mapped_column(
        JSON, name="by_ticket_type", nullable=True
    )
    is_cold_start: Mapped[bool] = mapped_column(
        Boolean, name="is_cold_start", nullable=False, default=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="recorded_at", server_default=func.now()
    )

    # -- relationships --
    team_member: Mapped["TeamMember"] = relationship(
        back_populates="velocity_profiles"
    )


class HealthSignal(Base):
    __tablename__ = "health_signals"
    __table_args__ = (
        Index(
            "ix_health_signals_org_created",
            "organization_id",
            "created_at",
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
    signal_type: Mapped[str] = mapped_column(
        String(50), name="signal_type", nullable=False
    )
    severity: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    message: Mapped[str] = mapped_column(String, nullable=False)
    metadata_: Mapped[Optional[Any]] = mapped_column(
        "metadata", JSON, nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="resolved_at", nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_at", server_default=func.now()
    )

    # -- relationships --
    organization: Mapped["Organization"] = relationship(
        back_populates="health_signals"
    )
    team_member: Mapped["TeamMember"] = relationship(
        back_populates="health_signals"
    )


class BurnoutAlert(Base):
    __tablename__ = "burnout_alerts"

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
    severity: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    capacity_utilization: Mapped[float] = mapped_column(
        Float, name="capacity_utilization", nullable=False
    )
    consecutive_sprints: Mapped[int] = mapped_column(
        Integer, name="consecutive_sprints", nullable=False
    )
    after_hours_frequency: Mapped[float] = mapped_column(
        Float, name="after_hours_frequency", nullable=False
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), name="acknowledged_at", nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), name="created_at", server_default=func.now()
    )

    # -- relationships --
    organization: Mapped["Organization"] = relationship(
        back_populates="burnout_alerts"
    )
    team_member: Mapped["TeamMember"] = relationship(
        back_populates="burnout_alerts"
    )

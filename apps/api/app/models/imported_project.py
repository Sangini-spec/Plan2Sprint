"""Imported project — persists project references after tool disconnect.

Also includes UserProjectPreference for persisting the user's last-selected
project across sessions (Task 1 — Project Selection).
"""

from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, JSON, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid


class ImportedProject(Base):
    __tablename__ = "imported_projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_id", "source_tool", name="uq_imported_project"),
    )

    id: Mapped[str] = mapped_column(String(25), primary_key=True, default=generate_cuid)
    organization_id: Mapped[str] = mapped_column(String(25), ForeignKey("organizations.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    source_tool: Mapped[str] = mapped_column(String(50), nullable=False)  # "ado" | "jira"
    name: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str | None] = mapped_column(String, nullable=True)  # Jira project key
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    board_id: Mapped[str | None] = mapped_column(String, nullable=True)  # Jira board ID or ADO team project
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cached_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # work items, team members, iterations
    slack_channel_id: Mapped[str | None] = mapped_column(String, nullable=True)  # Slack channel ID for project
    slack_channel_name: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "proj-medicare"
    teams_channel_id: Mapped[str | None] = mapped_column(String, nullable=True)  # MS Teams channel ID
    teams_channel_name: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "proj-medicare"
    # Timeline revamp (Sprint 1): the enforceable "ship by" date the dashboard
    # timeline is measured against. Set automatically when the first AI plan is
    # approved (copied from SprintPlan.estimated_end_date) and overwritten on
    # rebalance acceptance. Source=MANUAL when the PO overrode it from the UI —
    # in that case we keep it across plan regenerations until they reset.
    target_launch_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_launch_source: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "AUTO" | "MANUAL"
    # Hotfix 83 — idempotency key for the "project past target launch" email.
    # Holds the ``target_launch_date`` value that was active when we last
    # fired the alert. The next overdue check sends a new email only when
    # ``target_launch_date != last_overdue_alert_target_date``, so the
    # PO never gets two emails for the same missed launch — but if they
    # rebalance to a new target and that new target ALSO slips, a fresh
    # email is sent (different key).
    last_overdue_alert_target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    organization = relationship("Organization", backref="imported_projects")


class UserProjectPreference(Base):
    """Stores the user's last-selected project — persists across sessions and page refreshes."""
    __tablename__ = "user_project_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_project_pref"),
    )

    id: Mapped[str] = mapped_column(String(25), primary_key=True, default=generate_cuid)
    user_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # supabase user id or demo-user-1
    organization_id: Mapped[str] = mapped_column(String(25), nullable=False)
    selected_project_id: Mapped[str | None] = mapped_column(String(25), ForeignKey("imported_projects.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    selected_project = relationship("ImportedProject")


class StakeholderProjectAssignment(Base):
    """Maps a stakeholder user to projects they can view — assigned by PO/admin."""
    __tablename__ = "stakeholder_project_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "imported_project_id", name="uq_stakeholder_project"),
    )

    id: Mapped[str] = mapped_column(String(25), primary_key=True, default=generate_cuid)
    user_id: Mapped[str] = mapped_column(String(25), nullable=False)  # can be users.id or team_members.id
    imported_project_id: Mapped[str] = mapped_column(String(25), ForeignKey("imported_projects.id"), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(25), ForeignKey("organizations.id"), nullable=False)
    assigned_by: Mapped[str | None] = mapped_column(String(25), nullable=True)  # user_id of assigner
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project = relationship("ImportedProject")

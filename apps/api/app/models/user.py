from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, generate_cuid

if TYPE_CHECKING:
    from .organization import Organization
    from .notification import NotificationPreference
    from .audit_log import AuditLogEntry


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(
        String, name="full_name", nullable=False
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(
        String, name="avatar_url", nullable=True
    )
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="DEVELOPER"
    )
    supabase_user_id: Mapped[str] = mapped_column(
        String, name="supabase_user_id", unique=True, nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        String(25),
        ForeignKey("organizations.id"),
        name="organization_id",
        nullable=False,
    )
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, name="onboarding_completed", nullable=False, default=False
    )
    # Onboarding feature (Plan2Sprint product tour).
    #
    # JSON shape (see apps/web/src/lib/onboarding/types.ts for the
    # mirror TypeScript interface):
    #   {
    #     "role": "product_owner",
    #     "current_step": "sprint-planning-rebalance",
    #     "completed_steps": ["welcome", "connect-tool", ...],
    #     "skipped_steps": [],
    #     "page_hints_seen": ["/po/retro", "/po/health"],
    #     "status": "in_progress" | "completed" | "dismissed" | "not_started",
    #     "started_at": "2026-05-11T14:32:00Z",
    #     "completed_at": null,
    #     "banner_dismissed": false,
    #     "replay_count": 0
    #   }
    #
    # NULL = user has never been touched by the onboarding system
    # (existing users at ship time, new users until the welcome modal
    # fires). The frontend treats NULL the same as ``status=not_started``.
    onboarding_progress: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, name="onboarding_progress", nullable=True
    )
    # Hotfix 73 — per-user Slack identity link (after the dev/
    # stakeholder OAuths their personal Slack account from the
    # Channels page).
    slack_user_id: Mapped[Optional[str]] = mapped_column(
        String, name="slack_user_id", nullable=True
    )
    slack_team_id: Mapped[Optional[str]] = mapped_column(
        String, name="slack_team_id", nullable=True
    )
    slack_team_name: Mapped[Optional[str]] = mapped_column(
        String, name="slack_team_name", nullable=True
    )
    slack_handle: Mapped[Optional[str]] = mapped_column(
        String, name="slack_handle", nullable=True
    )
    # Hotfix 74 — per-user Teams identity link.
    teams_user_id: Mapped[Optional[str]] = mapped_column(
        String, name="teams_user_id", nullable=True
    )
    teams_user_principal_name: Mapped[Optional[str]] = mapped_column(
        String, name="teams_user_principal_name", nullable=True
    )
    teams_display_name: Mapped[Optional[str]] = mapped_column(
        String, name="teams_display_name", nullable=True
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
        back_populates="users"
    )
    notification_prefs: Mapped[List["NotificationPreference"]] = relationship(
        back_populates="user"
    )
    audit_log_entries: Mapped[List["AuditLogEntry"]] = relationship(
        back_populates="actor"
    )

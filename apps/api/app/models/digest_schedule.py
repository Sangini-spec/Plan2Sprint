"""
Per-user digest schedule preference.

Controls whether a specific user receives the morning and evening
notification digests on a given day. One row per (user_id) — scoped
to the user's organization through the User <-> Organization link.

This is layered ON TOP of the existing ``notification_scheduler.py``
background loop. The loop fires the same time windows it always did
(9 AM IST morning, 5 PM IST evening); the scheduler asks this table
"should I send to user X right now?" before queuing each delivery.
If a user has no row, ``_default_should_send`` returns True for the
old behavior — backward-compatible for orgs that haven't opted in
yet.

Schedule semantics:

  schedule_mode = 'every_weekday'
      Send Mon-Fri (current behaviour). selected_days is ignored.

  schedule_mode = 'alternate_days'
      Send Mon, Wed, Fri. selected_days is ignored.

  schedule_mode = 'weekly'
      Send only on the SINGLE day in selected_days (default Monday).
      We persist a list for storage uniformity even though only one
      element is used here.

  schedule_mode = 'custom'
      Send on every day in selected_days. Days are stored as
      Python's weekday() ints: 0=Mon, 1=Tue, ..., 6=Sun.

Independent of schedule_mode, ``send_morning`` and ``send_evening``
gate the two time slots. If BOTH are False, no digests go to this
user at all (clear opt-out — matches the UX design decision the PO
asked for: turning both off disables the digest entirely).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, INTEGER as PG_INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, generate_cuid


# Schedule modes — declared as plain string constants rather than a
# SQLAlchemy/PG Enum to keep migrations cheap (no DDL drift when we
# add a mode later). Validation happens in the API layer.
SCHEDULE_MODE_EVERY_WEEKDAY = "every_weekday"
SCHEDULE_MODE_ALTERNATE_DAYS = "alternate_days"
SCHEDULE_MODE_WEEKLY = "weekly"
SCHEDULE_MODE_CUSTOM = "custom"

VALID_SCHEDULE_MODES = (
    SCHEDULE_MODE_EVERY_WEEKDAY,
    SCHEDULE_MODE_ALTERNATE_DAYS,
    SCHEDULE_MODE_WEEKLY,
    SCHEDULE_MODE_CUSTOM,
)


class DigestSchedule(Base):
    """User-scoped preference for when to receive morning / evening digests.

    Read paths (notification_scheduler):
        ``should_send_for_user(db, user_id, slot, dt)``
        in ``services/digest_schedule_helper.py`` — that helper is
        the single place that interprets these rows. Don't replicate
        the logic in callers.

    Default behaviour for users with NO row:
        every_weekday + both times on. Preserves backward compatibility
        for orgs that haven't opened the preferences UI yet.
    """

    __tablename__ = "digest_schedules"
    __table_args__ = (
        # One schedule per user. We don't scope by org because a user's
        # PO role is always tied to one organization in the current data
        # model (TeamMember.organization_id is single-valued and a user
        # is one TeamMember per org). If multi-org-per-user is added
        # later, this becomes (user_id, organization_id).
        UniqueConstraint("user_id", name="uq_digest_schedule_user"),
        # Lookup by org in the scheduler loop benefits from a covering
        # index on org → user so we can join cheaply.
        Index("ix_digest_schedule_org", "organization_id"),
    )

    id: Mapped[str] = mapped_column(
        String(25), primary_key=True, default=generate_cuid
    )

    # FKs
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Mode controls WHICH days; ``selected_days`` carries the param
    # for 'weekly' and 'custom' modes only (ignored otherwise).
    schedule_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SCHEDULE_MODE_EVERY_WEEKDAY,
    )
    selected_days: Mapped[Optional[list[int]]] = mapped_column(
        ARRAY(PG_INTEGER),
        nullable=True,
        default=None,
    )

    # Time-slot toggles. Both default True (current behaviour).
    send_morning: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    send_evening: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # Audit fields
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

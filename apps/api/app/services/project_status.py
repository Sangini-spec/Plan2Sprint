"""Project lifecycle status helpers.

Right now exposes one thing: ``compute_overdue_status`` — the single
source of truth for "has this project's target launch date passed?",
used by:

  * The dashboard timeline block (drives red Target Launch tile, plan-
    badge swap, EST. WEEKS replacement).
  * The retrospective summary endpoint.
  * The cron-fired overdue email sender.

We keep the rule in ONE place so the email, the UI, and the retro card
can never disagree about whether a project is overdue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional


# Status of a project relative to its target launch.
#
#   on_track       - target not set OR project archived OR target still
#                    in the future (within grace).
#   overdue        - target was at least GRACE in the past AND completion
#                    hasn't reached 100%.
#   delivered_late - completion is 100% but target date passed before
#                    that happened. Different visual treatment in the
#                    UI (amber, not red) and triggers a different email
#                    template (or no email — see is_overdue below).
ProjectLifecycleStatus = Literal["on_track", "overdue", "delivered_late"]


# 24-hour grace from target_launch_date midnight (UTC) before flagging.
# This gives the team the entire target day to ship before alarms fire.
OVERDUE_GRACE = timedelta(days=1)


@dataclass(frozen=True)
class OverdueStatus:
    status: ProjectLifecycleStatus
    days_past: int  # 0 when status == on_track; positive otherwise

    @property
    def is_overdue(self) -> bool:
        """True only for the *uncompleted* past-target case. The email
        sender uses this to decide whether to fire — we deliberately
        DON'T email projects that delivered late since the team already
        knows they shipped."""
        return self.status == "overdue"


def compute_overdue_status(
    target_launch_date: Optional[datetime],
    completion_pct: float,
    is_active: bool,
    *,
    now: Optional[datetime] = None,
) -> OverdueStatus:
    """Decide whether a project is overdue right now.

    Args:
        target_launch_date: ``ImportedProject.target_launch_date`` —
            the committed launch date (UTC). May be None for projects
            that haven't approved a plan yet.
        completion_pct: 0-100. The dashboard's
            ``progressData.overallCompletePct``. We treat anything ≥ 100
            as "delivered" — sub-100 with a passed date is "overdue".
        is_active: ``ImportedProject.is_active``. Archived projects
            never go overdue.
        now: optional injected clock for deterministic testing.

    Returns: an ``OverdueStatus`` value with ``.status`` and
    ``.days_past``. ``days_past`` is calendar days (rounded down) past
    the target — useful for the "Overdue 8 days" subtitle.
    """
    now = now or datetime.now(timezone.utc)

    if not is_active or target_launch_date is None:
        return OverdueStatus(status="on_track", days_past=0)

    # Target dates are stored at noon UTC (per the Sprint 8 hover-edit
    # convention) so day-boundary comparisons work the same in every
    # viewer's timezone.
    target = target_launch_date
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)

    if now <= target + OVERDUE_GRACE:
        return OverdueStatus(status="on_track", days_past=0)

    # Past the grace window — figure out whether work actually finished.
    days_past = max(0, (now.date() - target.date()).days)

    if completion_pct >= 100:
        return OverdueStatus(status="delivered_late", days_past=days_past)

    return OverdueStatus(status="overdue", days_past=days_past)

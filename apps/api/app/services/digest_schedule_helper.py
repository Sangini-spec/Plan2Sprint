"""
Single source of truth for interpreting ``digest_schedules`` rows.

The notification_scheduler asks this helper "should I send a digest
to user X in slot Y right now?". Helper handles:

  * Default behaviour when no row exists (backward-compat).
  * Schedule mode interpretation (every_weekday / alternate_days /
    weekly / custom).
  * The send_morning / send_evening time-slot toggles.
  * Both-toggles-off as a clear opt-out (never send to this user).

DO NOT replicate this logic in callers — that's how this kind of
preference system silently goes wrong (one place gets updated, the
others quietly send extra mail).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.digest_schedule import (
    DigestSchedule,
    SCHEDULE_MODE_EVERY_WEEKDAY,
    SCHEDULE_MODE_ALTERNATE_DAYS,
    SCHEDULE_MODE_WEEKLY,
    SCHEDULE_MODE_CUSTOM,
)


# Python's datetime.weekday(): Monday=0 ... Sunday=6
MON, TUE, WED, THU, FRI, SAT, SUN = 0, 1, 2, 3, 4, 5, 6
WEEKDAYS = {MON, TUE, WED, THU, FRI}
ALTERNATE_DAYS = {MON, WED, FRI}


def _day_allowed(
    schedule_mode: str,
    selected_days: list[int] | None,
    weekday: int,
) -> bool:
    """Return True iff the schedule says ``today`` (weekday) is a send day."""
    if schedule_mode == SCHEDULE_MODE_EVERY_WEEKDAY:
        return weekday in WEEKDAYS
    if schedule_mode == SCHEDULE_MODE_ALTERNATE_DAYS:
        return weekday in ALTERNATE_DAYS
    if schedule_mode == SCHEDULE_MODE_WEEKLY:
        # Default to Monday if selected_days is empty/invalid. Storing
        # a single-element list keeps the column type consistent with
        # 'custom' mode and avoids two shapes to read.
        days = selected_days or [MON]
        return weekday in set(days)
    if schedule_mode == SCHEDULE_MODE_CUSTOM:
        return weekday in set(selected_days or [])
    # Unknown mode — fail-OPEN to today's weekday so a stale row from
    # a feature-flag flip can't silently mute notifications. Worst
    # case: user gets a notification they didn't expect; they re-pick
    # a mode and we're back on the rails.
    return weekday in WEEKDAYS


async def should_send_for_user(
    db: AsyncSession,
    user_id: str,
    slot: str,
    dt: datetime,
) -> bool:
    """The single check used by ``notification_scheduler``.

    Args:
        db: live AsyncSession.
        user_id: target ``users.id``.
        slot: ``"morning"`` or ``"evening"`` — anything else returns False.
        dt: the datetime the scheduler is firing for (UTC). Only its
            ``weekday()`` matters for the day decision.

    Returns:
        True if the digest should be queued for this user in this slot.
        False to skip — backed by either an explicit opt-out (both
        toggles False, schedule says "not today", or slot disabled) or
        an unknown slot.
    """
    if slot not in ("morning", "evening"):
        return False

    row = (await db.execute(
        select(DigestSchedule).where(DigestSchedule.user_id == user_id)
    )).scalar_one_or_none()

    # No row → default behaviour: every weekday, both slots on.
    if row is None:
        return dt.weekday() in WEEKDAYS

    # Both-off ⇒ user opted out entirely.
    if not row.send_morning and not row.send_evening:
        return False

    # Slot toggle.
    if slot == "morning" and not row.send_morning:
        return False
    if slot == "evening" and not row.send_evening:
        return False

    # Day-of-week gate based on schedule mode.
    return _day_allowed(row.schedule_mode, row.selected_days, dt.weekday())

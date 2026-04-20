"""
Activity Engine — evaluates activity events and generates health signals.

Signal Types:
  - after_hours_work    — dev commits/activity outside 9am-6pm
  - weekend_work        — dev commits/activity on Saturday/Sunday
  - blocker_stale       — blocker open > 24 hours
  - low_velocity        — dev velocity < 60% of rolling average
  - high_wip            — dev has > 3 items in IN_PROGRESS
  - unlinked_commits    — commits without ticket references
  - pr_review_overdue   — PR awaiting review > 48 hours
  - burnout_risk        — combination of after_hours + weekend + high utilization

Severities: info, warning, critical
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Sequence

from sqlalchemy import select, func as sa_func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.base import generate_cuid
from ..models.activity import ActivityEvent
from ..models.analytics import HealthSignal, BurnoutAlert, VelocityProfile
from ..models.work_item import WorkItem
from ..models.team_member import TeamMember
from ..models.organization import Organization
from .ws_manager import ws_manager
from ..models.repository import PullRequest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORKING_HOURS_START = 9   # 9 AM
WORKING_HOURS_END = 18    # 6 PM
WEEKEND_DAYS = {5, 6}     # Saturday = 5, Sunday = 6

MAX_WIP = 3               # > 3 items in progress triggers signal
VELOCITY_THRESHOLD = 0.6  # < 60% of rolling avg triggers signal
PR_REVIEW_OVERDUE_HOURS = 48
BLOCKER_STALE_HOURS = 24

BURNOUT_AFTER_HOURS_THRESHOLD = 0.3    # > 30% of events are after hours
BURNOUT_CONSECUTIVE_SPRINTS = 2         # overloaded for 2+ sprints


async def _get_org_hours(db: AsyncSession, org_id: str) -> tuple[int, int]:
    """Return (start_hour, end_hour) from org settings, falling back to 9-18.
    Uses integer hours for SQL comparisons. Half-hours round: start down, end up."""
    result = await db.execute(
        select(Organization.working_hours_start, Organization.working_hours_end)
        .where(Organization.id == org_id)
    )
    row = result.one_or_none()
    if row and row[0] is not None and row[1] is not None:
        try:
            s_parts = str(row[0]).split(":")
            e_parts = str(row[1]).split(":")
            start = int(s_parts[0])
            end_h = int(e_parts[0])
            end_m = int(e_parts[1]) if len(e_parts) > 1 else 0
            end = end_h + (1 if end_m > 0 else 0)  # round up
            if 0 <= start <= 23 and start < end <= 24:
                return start, end
        except (ValueError, IndexError):
            pass
    return WORKING_HOURS_START, WORKING_HOURS_END


# ---------------------------------------------------------------------------
# Activity Event Creation
# ---------------------------------------------------------------------------

async def record_activity(
    db: AsyncSession,
    org_id: str,
    team_member_id: str,
    event_type: str,
    source_tool: str,
    occurred_at: datetime,
    *,
    external_id: str | None = None,
    linked_ticket_id: str | None = None,
    metadata: dict | None = None,
    working_hours_start: int = WORKING_HOURS_START,
    working_hours_end: int = WORKING_HOURS_END,
) -> ActivityEvent:
    """
    Record a single activity event. Automatically flags after-hours and weekend.
    """
    is_after_hours = (
        occurred_at.hour < working_hours_start
        or occurred_at.hour >= working_hours_end
    )
    is_weekend = occurred_at.weekday() in WEEKEND_DAYS

    event = ActivityEvent(
        id=generate_cuid(),
        organization_id=org_id,
        team_member_id=team_member_id,
        event_type=event_type,
        source_tool=source_tool,
        external_id=external_id,
        linked_ticket_id=linked_ticket_id,
        metadata_=metadata,
        is_after_hours=is_after_hours,
        is_weekend=is_weekend,
        occurred_at=occurred_at,
    )
    db.add(event)
    await db.flush()
    return event


# ---------------------------------------------------------------------------
# Signal Evaluators
# ---------------------------------------------------------------------------

async def evaluate_high_wip(
    db: AsyncSession,
    org_id: str,
    team_member_id: str,
) -> HealthSignal | None:
    """Check if a team member has too many items in progress."""
    result = await db.execute(
        select(sa_func.count()).where(
            WorkItem.organization_id == org_id,
            WorkItem.assignee_id == team_member_id,
            WorkItem.status == "IN_PROGRESS",
        )
    )
    wip_count = result.scalar() or 0

    if wip_count > MAX_WIP:
        return await _create_signal(
            db, org_id, team_member_id,
            signal_type="high_wip",
            severity="warning",
            message=f"Has {wip_count} items in progress (limit: {MAX_WIP})",
            metadata={"wip_count": wip_count, "threshold": MAX_WIP},
        )
    return None


async def evaluate_after_hours(
    db: AsyncSession,
    org_id: str,
    team_member_id: str,
    lookback_days: int = 14,
) -> HealthSignal | None:
    """Check if a team member is frequently working after hours."""
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    total_result = await db.execute(
        select(sa_func.count()).where(
            ActivityEvent.organization_id == org_id,
            ActivityEvent.team_member_id == team_member_id,
            ActivityEvent.occurred_at >= since,
        )
    )
    total = total_result.scalar() or 0

    if total == 0:
        return None

    after_hours_result = await db.execute(
        select(sa_func.count()).where(
            ActivityEvent.organization_id == org_id,
            ActivityEvent.team_member_id == team_member_id,
            ActivityEvent.occurred_at >= since,
            ActivityEvent.is_after_hours == True,
        )
    )
    after_hours = after_hours_result.scalar() or 0

    ratio = after_hours / total
    if ratio > BURNOUT_AFTER_HOURS_THRESHOLD:
        return await _create_signal(
            db, org_id, team_member_id,
            signal_type="after_hours_work",
            severity="warning" if ratio < 0.5 else "critical",
            message=f"{int(ratio * 100)}% of activity is after hours ({after_hours}/{total} events)",
            metadata={"ratio": round(ratio, 2), "after_hours": after_hours, "total": total},
        )
    return None


async def evaluate_weekend_work(
    db: AsyncSession,
    org_id: str,
    team_member_id: str,
    lookback_days: int = 14,
) -> HealthSignal | None:
    """Check if a team member is working on weekends."""
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    weekend_result = await db.execute(
        select(sa_func.count()).where(
            ActivityEvent.organization_id == org_id,
            ActivityEvent.team_member_id == team_member_id,
            ActivityEvent.occurred_at >= since,
            ActivityEvent.is_weekend == True,
        )
    )
    weekend_count = weekend_result.scalar() or 0

    if weekend_count >= 3:  # 3+ weekend events in 2 weeks is concerning
        return await _create_signal(
            db, org_id, team_member_id,
            signal_type="weekend_work",
            severity="warning",
            message=f"{weekend_count} activity events on weekends in the last {lookback_days} days",
            metadata={"weekend_count": weekend_count, "lookback_days": lookback_days},
        )
    return None


async def evaluate_unlinked_commits(
    db: AsyncSession,
    org_id: str,
    team_member_id: str,
    lookback_days: int = 7,
) -> HealthSignal | None:
    """Check if a team member has commits without ticket references."""
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    result = await db.execute(
        select(sa_func.count()).where(
            ActivityEvent.organization_id == org_id,
            ActivityEvent.team_member_id == team_member_id,
            ActivityEvent.occurred_at >= since,
            ActivityEvent.event_type == "commit",
            ActivityEvent.linked_ticket_id == None,
        )
    )
    unlinked = result.scalar() or 0

    if unlinked >= 5:
        return await _create_signal(
            db, org_id, team_member_id,
            signal_type="unlinked_commits",
            severity="info",
            message=f"{unlinked} commits without ticket references in the last {lookback_days} days",
            metadata={"unlinked_count": unlinked},
        )
    return None


async def evaluate_pr_review_overdue(
    db: AsyncSession,
    org_id: str,
) -> list[HealthSignal]:
    """Check for PRs awaiting review longer than threshold."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=PR_REVIEW_OVERDUE_HOURS)

    result = await db.execute(
        select(PullRequest).where(
            PullRequest.status == "OPEN",
            PullRequest.created_external_at <= cutoff,
        )
    )
    overdue_prs = result.scalars().all()
    signals: list[HealthSignal] = []

    for pr in overdue_prs:
        if pr.author_id:
            hours_old = (datetime.now(timezone.utc) - pr.created_external_at).total_seconds() / 3600
            signal = await _create_signal(
                db, org_id, pr.author_id,
                signal_type="pr_review_overdue",
                severity="warning",
                message=f"PR #{pr.number} '{pr.title}' awaiting review for {int(hours_old)}h",
                metadata={"pr_id": pr.id, "pr_number": pr.number, "hours_old": int(hours_old)},
            )
            if signal:
                signals.append(signal)

    return signals


# ---------------------------------------------------------------------------
# Full Evaluation (run periodically or on webhook)
# ---------------------------------------------------------------------------

async def evaluate_all_signals(
    db: AsyncSession,
    org_id: str,
) -> list[HealthSignal]:
    """
    Run all signal evaluators for all team members in the org.
    Typically called periodically (e.g. every hour) or after a sync.
    """
    # Load org-specific working hours for after-hours detection
    org_start, org_end = await _get_org_hours(db, org_id)

    # Get all team members
    result = await db.execute(
        select(TeamMember).where(TeamMember.organization_id == org_id)
    )
    members = result.scalars().all()

    all_signals: list[HealthSignal] = []

    for member in members:
        # Run per-member evaluators
        signal = await evaluate_high_wip(db, org_id, member.id)
        if signal:
            all_signals.append(signal)

        signal = await evaluate_after_hours(db, org_id, member.id)
        if signal:
            all_signals.append(signal)

        signal = await evaluate_weekend_work(db, org_id, member.id)
        if signal:
            all_signals.append(signal)

        signal = await evaluate_unlinked_commits(db, org_id, member.id)
        if signal:
            all_signals.append(signal)

    # Run org-wide evaluators
    pr_signals = await evaluate_pr_review_overdue(db, org_id)
    all_signals.extend(pr_signals)

    await db.commit()

    logger.info(f"Evaluated signals for org {org_id}: {len(all_signals)} new signals")

    # Broadcast health signal events if any new signals were created
    if all_signals:
        await ws_manager.broadcast(org_id, {
            "type": "health_signals",
            "data": {
                "count": len(all_signals),
                "signals": [
                    {
                        "type": s.signal_type,
                        "severity": s.severity,
                        "message": s.message,
                    }
                    for s in all_signals[:10]  # Limit to avoid oversized messages
                ],
            },
        })

    return all_signals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_signal(
    db: AsyncSession,
    org_id: str,
    team_member_id: str,
    *,
    signal_type: str,
    severity: str,
    message: str,
    metadata: dict | None = None,
) -> HealthSignal | None:
    """Create a health signal if one doesn't already exist (dedup within 24h)."""
    # Dedup: check if the same signal type exists for this member in the last 24h
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    result = await db.execute(
        select(HealthSignal).where(
            HealthSignal.organization_id == org_id,
            HealthSignal.team_member_id == team_member_id,
            HealthSignal.signal_type == signal_type,
            HealthSignal.created_at >= since,
            HealthSignal.resolved_at == None,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return None  # Already have a recent signal

    signal = HealthSignal(
        id=generate_cuid(),
        organization_id=org_id,
        team_member_id=team_member_id,
        signal_type=signal_type,
        severity=severity,
        message=message,
        metadata_=metadata,
    )
    db.add(signal)
    await db.flush()
    return signal

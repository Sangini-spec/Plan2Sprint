"""
Daily Digest Service — generates per-project status cards for PO Slack/Teams DMs.

Three message types:
  1. Morning Digest (9 AM)  — "What to watch today"
  2. Evening Summary (5 PM) — "What happened today"
  3. Nudge Message           — "You haven't checked P2S in X days"
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.imported_project import ImportedProject
from ..models.sprint_plan import SprintPlan
from ..models.work_item import WorkItem
from ..models.iteration import Iteration
from ..models.standup import StandupReport, BlockerFlag
from ..models.repository import PullRequest
from ..models.analytics import HealthSignal
from ..models.team_member import TeamMember
from ..models.in_app_notification import InAppNotification
from ..models.user import User
from ..models.tool_connection import ToolConnection

logger = logging.getLogger(__name__)

FRONTEND_URL = "https://plan2sprint-web.purplebeach-150945ee.westus3.azurecontainerapps.io"


# ---------------------------------------------------------------------------
# Data Gathering Helpers
# ---------------------------------------------------------------------------

async def _get_sprint_status(db: AsyncSession, org_id: str, project_id: str) -> dict:
    """Get current sprint progress for a project."""
    # Find active iteration
    iter_result = await db.execute(
        select(Iteration).where(
            Iteration.organization_id == org_id,
            Iteration.state == "active",
        ).order_by(Iteration.start_date.desc()).limit(1)
    )
    iteration = iter_result.scalar_one_or_none()

    if not iteration:
        return {"hasIteration": False}

    now = datetime.now(timezone.utc)
    total_days = max((iteration.end_date - iteration.start_date).days, 1) if iteration.end_date and iteration.start_date else 14
    elapsed_days = max((now - iteration.start_date).days, 0) if iteration.start_date else 0
    elapsed_pct = min(round((elapsed_days / total_days) * 100), 100)

    # Work item counts
    wi_result = await db.execute(
        select(WorkItem.status, func.count()).where(
            WorkItem.organization_id == org_id,
            WorkItem.imported_project_id == project_id,
        ).group_by(WorkItem.status)
    )
    status_counts = dict(wi_result.all())
    total = sum(status_counts.values())
    done = status_counts.get("DONE", 0) + status_counts.get("CLOSED", 0)
    completion_pct = round((done / total) * 100) if total > 0 else 0

    # Get latest plan
    plan_result = await db.execute(
        select(SprintPlan).where(
            SprintPlan.organization_id == org_id,
            SprintPlan.project_id == project_id,
            SprintPlan.status.in_(["APPROVED", "SYNCED", "SYNCED_PARTIAL"]),
        ).order_by(SprintPlan.created_at.desc()).limit(1)
    )
    plan = plan_result.scalar_one_or_none()

    return {
        "hasIteration": True,
        "sprintName": iteration.name or "Current Sprint",
        "completionPct": completion_pct,
        "elapsedPct": elapsed_pct,
        "totalItems": total,
        "doneItems": done,
        "estimatedSprints": plan.estimated_sprints if plan else None,
        "successProbability": plan.success_probability if plan else None,
        "isRebalanced": getattr(plan, 'is_rebalanced', False) if plan else False,
    }


async def _get_blocker_status(db: AsyncSession, org_id: str) -> dict:
    """Get active blocker counts."""
    result = await db.execute(
        select(BlockerFlag.status, func.count()).where(
            BlockerFlag.standup_report_id.in_(
                select(StandupReport.id).where(StandupReport.organization_id == org_id)
            ),
            BlockerFlag.status.in_(["OPEN", "ACKNOWLEDGED", "ESCALATED"]),
        ).group_by(BlockerFlag.status)
    )
    counts = dict(result.all())
    total = sum(counts.values())
    unacked = counts.get("OPEN", 0)
    return {"total": total, "unacknowledged": unacked, "escalated": counts.get("ESCALATED", 0)}


async def _get_standup_status(db: AsyncSession, org_id: str) -> dict:
    """Get today's standup submission count."""
    today = datetime.now(timezone.utc).date()
    submitted = await db.execute(
        select(func.count()).select_from(StandupReport).where(
            StandupReport.organization_id == org_id,
            func.date(StandupReport.created_at) == today,
        )
    )
    total_devs = await db.execute(
        select(func.count()).select_from(TeamMember).where(
            TeamMember.organization_id == org_id,
            TeamMember.role.in_(["DEVELOPER", "developer"]),
        )
    )
    return {
        "submitted": submitted.scalar() or 0,
        "totalDevs": total_devs.scalar() or 0,
    }


async def _get_pr_activity(db: AsyncSession, org_id: str) -> dict:
    """Get today's PR activity."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    # PRs opened/merged today
    from ..models.repository import Repository
    repo_ids_q = select(Repository.id).where(Repository.organization_id == org_id)

    opened = await db.execute(
        select(func.count()).select_from(PullRequest).where(
            PullRequest.repository_id.in_(repo_ids_q),
            PullRequest.created_external_at >= today_start,
        )
    )
    merged = await db.execute(
        select(func.count()).select_from(PullRequest).where(
            PullRequest.repository_id.in_(repo_ids_q),
            PullRequest.status == "MERGED",
            PullRequest.merged_at >= today_start,
        )
    )
    stalled = await db.execute(
        select(func.count()).select_from(PullRequest).where(
            PullRequest.repository_id.in_(repo_ids_q),
            PullRequest.status == "OPEN",
            PullRequest.created_external_at <= datetime.now(timezone.utc) - timedelta(hours=48),
        )
    )
    return {
        "openedToday": opened.scalar() or 0,
        "mergedToday": merged.scalar() or 0,
        "stalled": stalled.scalar() or 0,
    }


async def _get_health_score(db: AsyncSession, org_id: str) -> dict:
    """Get team health overall score (lightweight — no full dashboard computation)."""
    # Check for recent health signals
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    signals = await db.execute(
        select(HealthSignal.severity, func.count()).where(
            HealthSignal.organization_id == org_id,
            HealthSignal.created_at >= week_ago,
            HealthSignal.resolved_at.is_(None),
        ).group_by(HealthSignal.severity)
    )
    severity_counts = dict(signals.all())
    red_count = severity_counts.get("critical", 0) + severity_counts.get("warning", 0)

    # Simple score estimate based on unresolved signals
    total_signals = sum(severity_counts.values())
    score = max(0, 100 - (total_signals * 10))

    return {"score": score, "activeSignals": total_signals, "criticalCount": red_count}


# ---------------------------------------------------------------------------
# Morning Digest
# ---------------------------------------------------------------------------

async def generate_morning_digest(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    project_name: str,
) -> dict[str, Any]:
    """Generate morning digest data for one project."""
    sprint = await _get_sprint_status(db, org_id, project_id)
    blockers = await _get_blocker_status(db, org_id)
    health = await _get_health_score(db, org_id)

    # Build "needs attention" items
    attention = []
    if blockers["unacknowledged"] > 0:
        attention.append(f"{blockers['unacknowledged']} unacknowledged blocker(s)")
    if sprint.get("successProbability") is not None and sprint["successProbability"] < 65:
        attention.append(f"Sprint success at {sprint['successProbability']}% — rebalancing recommended")
    if health["criticalCount"] > 0:
        attention.append(f"{health['criticalCount']} team health alert(s)")

    success_prob = sprint.get("successProbability")
    if success_prob is not None:
        if success_prob >= 75:
            risk_label = "ON TRACK"
        elif success_prob >= 50:
            risk_label = "AT RISK"
        else:
            risk_label = "CRITICAL"
    else:
        risk_label = "NO DATA"

    return {
        "type": "morning",
        "projectName": project_name,
        "projectId": project_id,
        "sprintName": sprint.get("sprintName", "N/A"),
        "completionPct": sprint.get("completionPct", 0),
        "successProbability": success_prob,
        "riskLabel": risk_label,
        "blockerCount": blockers["total"],
        "unackedBlockers": blockers["unacknowledged"],
        "healthScore": health["score"],
        "attentionItems": attention,
        "isRebalanced": sprint.get("isRebalanced", False),
        "link": f"{FRONTEND_URL}/po",
    }


# ---------------------------------------------------------------------------
# Evening Summary
# ---------------------------------------------------------------------------

async def generate_evening_summary(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    project_name: str,
) -> dict[str, Any]:
    """Generate evening summary data for one project."""
    sprint = await _get_sprint_status(db, org_id, project_id)
    blockers = await _get_blocker_status(db, org_id)
    standups = await _get_standup_status(db, org_id)
    prs = await _get_pr_activity(db, org_id)

    # Count stories completed today
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    completed_today = await db.execute(
        select(func.count()).select_from(WorkItem).where(
            WorkItem.organization_id == org_id,
            WorkItem.imported_project_id == project_id,
            WorkItem.status.in_(["DONE", "CLOSED"]),
            WorkItem.updated_at >= today_start,
        )
    )

    return {
        "type": "evening",
        "projectName": project_name,
        "projectId": project_id,
        "completedToday": completed_today.scalar() or 0,
        "prsOpened": prs["openedToday"],
        "prsMerged": prs["mergedToday"],
        "stalledPrs": prs["stalled"],
        "completionPct": sprint.get("completionPct", 0),
        "unresolvedBlockers": blockers["total"],
        "standupsSubmitted": standups["submitted"],
        "totalDevs": standups["totalDevs"],
        "link": f"{FRONTEND_URL}/po",
    }


# ---------------------------------------------------------------------------
# Nudge Message
# ---------------------------------------------------------------------------

async def generate_nudge_data(
    db: AsyncSession,
    org_id: str,
    user_email: str,
    days_inactive: int,
    nudge_level: int,
) -> dict[str, Any]:
    """Generate nudge message data based on inactivity level."""
    blockers = await _get_blocker_status(db, org_id)
    health = await _get_health_score(db, org_id)

    # Count projects with issues
    projects_at_risk = 0
    proj_result = await db.execute(
        select(ImportedProject).where(ImportedProject.organization_id == org_id)
    )
    for proj in proj_result.scalars().all():
        status = await _get_sprint_status(db, org_id, proj.id)
        if status.get("successProbability") is not None and status["successProbability"] < 65:
            projects_at_risk += 1

    # Nudge tone based on level
    if nudge_level == 1:
        greeting = f"You haven't checked Plan2Sprint in {days_inactive} days."
        tone = "friendly"
    elif nudge_level == 2:
        greeting = f"Your team needs attention — {days_inactive} days since your last visit."
        tone = "direct"
    else:
        greeting = f"Critical items unresolved for over a week. {days_inactive} days inactive."
        tone = "urgent"

    highlights = []
    if blockers["total"] > 0:
        highlights.append(f"{blockers['total']} active blocker(s)")
    if projects_at_risk > 0:
        highlights.append(f"{projects_at_risk} project(s) at risk")
    if health["criticalCount"] > 0:
        highlights.append(f"{health['criticalCount']} team health alert(s)")
    if not highlights:
        highlights.append("Check your project dashboards for updates")

    return {
        "type": "nudge",
        "greeting": greeting,
        "tone": tone,
        "nudgeLevel": nudge_level,
        "daysInactive": days_inactive,
        "highlights": highlights,
        "link": f"{FRONTEND_URL}/po",
    }


# ---------------------------------------------------------------------------
# Orchestrator — Send Digests for All Projects in an Org
# ---------------------------------------------------------------------------

async def get_po_email(db: AsyncSession, org_id: str) -> str | None:
    """Get the PO's email for an org. Prefers POs that have Slack mapping."""
    # First: prefer team members with slack_user_id set (they can actually receive)
    result = await db.execute(
        select(TeamMember.email).where(
            TeamMember.organization_id == org_id,
            TeamMember.slack_user_id.isnot(None),
            TeamMember.role.in_(["PRODUCT_OWNER", "product_owner", "ADMIN", "admin", "OWNER", "owner"]),
        ).limit(1)
    )
    row = result.scalar_one_or_none()
    if row:
        return row

    # Second: any team member with slack_user_id (even if not PO role)
    result = await db.execute(
        select(TeamMember.email).where(
            TeamMember.organization_id == org_id,
            TeamMember.slack_user_id.isnot(None),
        ).limit(1)
    )
    row = result.scalar_one_or_none()
    if row:
        return row

    # Third: any PO-role team member
    result = await db.execute(
        select(TeamMember.email).where(
            TeamMember.organization_id == org_id,
            TeamMember.role.in_(["PRODUCT_OWNER", "product_owner", "ADMIN", "admin", "OWNER", "owner"]),
        ).limit(1)
    )
    row = result.scalar_one_or_none()
    if row:
        return row

    # Fallback: any user with email
    user_result = await db.execute(
        select(User.email).where(User.organization_id == org_id).limit(1)
    )
    return user_result.scalar_one_or_none()


async def get_org_projects(db: AsyncSession, org_id: str) -> list[dict]:
    """Get all projects for an org."""
    result = await db.execute(
        select(ImportedProject).where(ImportedProject.organization_id == org_id)
    )
    return [{"id": p.id, "name": p.name} for p in result.scalars().all()]


async def get_connected_orgs(db: AsyncSession) -> list[str]:
    """Get all org IDs that have Slack or Teams connected."""
    result = await db.execute(
        select(ToolConnection.organization_id).where(
            ToolConnection.source_tool.in_(["SLACK", "TEAMS"]),
            ToolConnection.access_token.isnot(None),
        ).distinct()
    )
    return [row[0] for row in result.all()]


async def check_nudge_needed(db: AsyncSession, org_id: str, po_email: str) -> tuple[int, int] | None:
    """Check if a nudge is needed. Returns (days_inactive, nudge_level) or None."""
    # Get PO's last login from user table
    user_result = await db.execute(
        select(User.last_sign_in_at).where(
            User.organization_id == org_id,
            User.email == po_email,
        )
    )
    last_login = user_result.scalar_one_or_none()

    if not last_login:
        return None  # Can't determine inactivity

    days_inactive = (datetime.now(timezone.utc) - last_login).days
    if days_inactive < 3:
        return None  # Active enough

    # Count nudges sent in current streak
    nudges_sent = await db.execute(
        select(func.count()).select_from(InAppNotification).where(
            InAppNotification.organization_id == org_id,
            InAppNotification.recipient_email == po_email,
            InAppNotification.type == "inactivity_nudge",
            InAppNotification.created_at >= last_login,  # Only count since last login
        )
    )
    nudge_count = nudges_sent.scalar() or 0

    if nudge_count >= 3:
        return None  # Max nudges reached

    if days_inactive >= 8 and nudge_count == 2:
        return (days_inactive, 3)
    elif days_inactive >= 5 and nudge_count == 1:
        return (days_inactive, 2)
    elif days_inactive >= 3 and nudge_count == 0:
        return (days_inactive, 1)

    return None

"""
Agent Tools — wraps existing Plan2Sprint services as callable tools for AI agents.

Each tool function:
  1. Accepts keyword arguments matching the JSON Schema parameters
  2. Receives `_context` dict with `db` (AsyncSession) and `org_id`
  3. Returns a JSON-serializable dict

Tools are registered in `build_standup_tools()` etc., returning AgentTool lists
that plug into the orchestrator.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .agent_orchestrator import AgentTool
from ..models.work_item import WorkItem
from ..models.team_member import TeamMember
from ..models.repository import PullRequest, Commit
from ..models.standup import StandupReport, BlockerFlag
from ..models.activity import ActivityEvent
from ..models.analytics import HealthSignal, VelocityProfile
from ..models.iteration import Iteration
from ..models.sprint_plan import SprintPlan, PlanAssignment
from ..models.retrospective import Retrospective, RetroActionItem
from ..models.sprint_constraint import SprintConstraint

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: extract DB session and org from context
# ---------------------------------------------------------------------------

def _ctx(context: dict[str, Any] | None) -> tuple[AsyncSession, str]:
    """Extract db session and org_id from _context passed by orchestrator."""
    if not context:
        raise ValueError("No context provided — agent tools require db + org_id")
    return context["db"], context["org_id"]


# ---------------------------------------------------------------------------
# Tool: get_github_activity
# ---------------------------------------------------------------------------

async def get_github_activity(
    team_member_id: str | None = None,
    since_hours: int = 24,
    **kwargs: Any,
) -> dict:
    """Get recent GitHub activity (commits, PRs) for a team member or the whole team."""
    db, org_id = _ctx(kwargs.get("_context"))
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    # Commits
    commit_q = (
        select(Commit)
        .where(Commit.committed_at >= since)
        .order_by(Commit.committed_at.desc())
        .limit(50)
    )
    if team_member_id:
        commit_q = commit_q.where(Commit.author_id == team_member_id)

    commit_result = await db.execute(commit_q)
    commits = commit_result.scalars().all()

    # PRs
    pr_q = (
        select(PullRequest)
        .where(PullRequest.created_external_at >= since)
        .order_by(PullRequest.created_external_at.desc())
        .limit(30)
    )
    if team_member_id:
        pr_q = pr_q.where(PullRequest.author_id == team_member_id)

    pr_result = await db.execute(pr_q)
    prs = pr_result.scalars().all()

    return {
        "commits": [
            {
                "sha": c.sha[:8],
                "message": (c.message or "")[:100],
                "author_id": c.author_id,
                "committed_at": str(c.committed_at),
                "linked_ticket_ids": c.linked_ticket_ids if c.linked_ticket_ids else [],
            }
            for c in commits
        ],
        "pull_requests": [
            {
                "number": pr.number,
                "title": pr.title,
                "status": pr.status,
                "author_id": pr.author_id,
                "created_at": str(pr.created_external_at),
                "merged_at": str(pr.merged_at) if pr.merged_at else None,
                "url": pr.url,
            }
            for pr in prs
        ],
    }


# ---------------------------------------------------------------------------
# Tool: get_work_items
# ---------------------------------------------------------------------------

async def get_work_items(
    team_member_id: str | None = None,
    status: str | None = None,
    since_hours: int | None = None,
    **kwargs: Any,
) -> dict:
    """Get work items, optionally filtered by assignee, status, or recency."""
    db, org_id = _ctx(kwargs.get("_context"))

    q = (
        select(WorkItem)
        .where(WorkItem.organization_id == org_id)
        .order_by(WorkItem.updated_at.desc())
        .limit(50)
    )
    if team_member_id:
        q = q.where(WorkItem.assignee_id == team_member_id)
    if status:
        q = q.where(WorkItem.status == status.upper())
    if since_hours:
        since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        q = q.where(WorkItem.updated_at >= since)

    result = await db.execute(q)
    items = result.scalars().all()

    return {
        "items": [
            {
                "id": wi.id,
                "external_id": wi.external_id,
                "title": wi.title,
                "type": wi.type,
                "status": wi.status,
                "priority": wi.priority,
                "story_points": wi.story_points,
                "assignee_id": wi.assignee_id,
                "updated_at": str(wi.updated_at),
            }
            for wi in items
        ],
        "total": len(items),
    }


# ---------------------------------------------------------------------------
# Tool: get_health_signals
# ---------------------------------------------------------------------------

async def get_health_signals(
    team_member_id: str | None = None,
    severity: str | None = None,
    **kwargs: Any,
) -> dict:
    """Get active health signals for the team or a specific member."""
    db, org_id = _ctx(kwargs.get("_context"))

    q = (
        select(HealthSignal)
        .where(HealthSignal.organization_id == org_id)
        .order_by(HealthSignal.created_at.desc())
        .limit(30)
    )
    if team_member_id:
        q = q.where(HealthSignal.team_member_id == team_member_id)
    if severity:
        q = q.where(HealthSignal.severity == severity.lower())

    result = await db.execute(q)
    signals = result.scalars().all()

    return {
        "signals": [
            {
                "id": s.id,
                "team_member_id": s.team_member_id,
                "signal_type": s.signal_type,
                "severity": s.severity,
                "message": s.message,
                "detected_at": str(s.created_at),
            }
            for s in signals
        ],
    }


# ---------------------------------------------------------------------------
# Tool: get_team_members
# ---------------------------------------------------------------------------

async def get_team_members(**kwargs: Any) -> dict:
    """Get all team members in the organization."""
    db, org_id = _ctx(kwargs.get("_context"))

    result = await db.execute(
        select(TeamMember)
        .where(TeamMember.organization_id == org_id)
        .order_by(TeamMember.display_name)
    )
    members = result.scalars().all()

    return {
        "members": [
            {
                "id": m.id,
                "display_name": m.display_name,
                "email": m.email,
                "role": m.role,
                "skill_tags": m.skill_tags if hasattr(m, "skill_tags") else [],
                "default_capacity": m.default_capacity if hasattr(m, "default_capacity") else None,
            }
            for m in members
        ],
    }


# ---------------------------------------------------------------------------
# Tool: get_standup_history
# ---------------------------------------------------------------------------

async def get_standup_history(
    team_member_id: str | None = None,
    days: int = 7,
    **kwargs: Any,
) -> dict:
    """Get recent standup reports."""
    db, org_id = _ctx(kwargs.get("_context"))
    since = datetime.now(timezone.utc) - timedelta(days=days)

    q = (
        select(StandupReport)
        .where(
            StandupReport.organization_id == org_id,
            StandupReport.report_date >= since,
        )
        .order_by(StandupReport.report_date.desc())
        .limit(50)
    )
    if team_member_id:
        q = q.where(StandupReport.team_member_id == team_member_id)

    result = await db.execute(q)
    reports = result.scalars().all()

    return {
        "reports": [
            {
                "id": r.id,
                "team_member_id": r.team_member_id,
                "report_date": str(r.report_date),
                "completed_items": r.completed_items,
                "in_progress_items": r.in_progress_items,
                "blockers": r.blockers,
                "narrative_text": r.narrative_text,
                "is_inactive": r.is_inactive,
                "acknowledged": r.acknowledged,
            }
            for r in reports
        ],
    }


# ---------------------------------------------------------------------------
# Tool: get_open_blockers
# ---------------------------------------------------------------------------

async def get_open_blockers(**kwargs: Any) -> dict:
    """Get all open blocker flags across the organization."""
    db, org_id = _ctx(kwargs.get("_context"))

    q = (
        select(BlockerFlag)
        .join(StandupReport, BlockerFlag.standup_report_id == StandupReport.id)
        .where(
            StandupReport.organization_id == org_id,
            BlockerFlag.status.in_(["OPEN", "ACKNOWLEDGED", "ESCALATED"]),
        )
        .order_by(BlockerFlag.flagged_at.desc())
        .limit(20)
    )
    result = await db.execute(q)
    blockers = result.scalars().all()

    return {
        "blockers": [
            {
                "id": b.id,
                "description": b.description,
                "ticket_reference": b.ticket_reference,
                "status": b.status,
                "flagged_at": str(b.flagged_at),
            }
            for b in blockers
        ],
    }


# ---------------------------------------------------------------------------
# Tool: get_recent_activity_events
# ---------------------------------------------------------------------------

async def get_recent_activity_events(
    team_member_id: str | None = None,
    since_hours: int = 24,
    **kwargs: Any,
) -> dict:
    """Get recent activity events (commits, PR reviews, status changes)."""
    db, org_id = _ctx(kwargs.get("_context"))
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    q = (
        select(ActivityEvent)
        .where(
            ActivityEvent.organization_id == org_id,
            ActivityEvent.occurred_at >= since,
        )
        .order_by(ActivityEvent.occurred_at.desc())
        .limit(100)
    )
    if team_member_id:
        q = q.where(ActivityEvent.team_member_id == team_member_id)

    result = await db.execute(q)
    events = result.scalars().all()

    return {
        "events": [
            {
                "id": e.id,
                "team_member_id": e.team_member_id,
                "event_type": e.event_type,
                "source_tool": e.source_tool,
                "occurred_at": str(e.occurred_at),
                "is_after_hours": e.is_after_hours,
                "is_weekend": e.is_weekend,
                "linked_ticket_id": e.linked_ticket_id if hasattr(e, "linked_ticket_id") else None,
            }
            for e in events
        ],
    }


# ---------------------------------------------------------------------------
# Tool Builders — assemble tool sets per agent type
# ---------------------------------------------------------------------------

def build_standup_tools() -> list[AgentTool]:
    """Tools available to the Auto Standup Generator agent."""
    return [
        AgentTool(
            name="get_team_members",
            description="Get all team members in the organization with their IDs, names, roles, and skills.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=get_team_members,
        ),
        AgentTool(
            name="get_github_activity",
            description="Get recent GitHub activity (commits and pull requests) for a specific team member or the whole team. Returns commit messages, PR titles/status, and timestamps.",
            parameters={
                "type": "object",
                "properties": {
                    "team_member_id": {
                        "type": "string",
                        "description": "Filter by team member ID. Omit for all members.",
                    },
                    "since_hours": {
                        "type": "integer",
                        "description": "Look back this many hours. Default 24.",
                        "default": 24,
                    },
                },
                "required": [],
            },
            handler=get_github_activity,
        ),
        AgentTool(
            name="get_work_items",
            description="Get work items (tickets) from Jira/ADO. Can filter by assignee, status (TODO, IN_PROGRESS, IN_REVIEW, DONE), or recency.",
            parameters={
                "type": "object",
                "properties": {
                    "team_member_id": {
                        "type": "string",
                        "description": "Filter by assignee. Omit for all.",
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by status: TODO, IN_PROGRESS, IN_REVIEW, DONE.",
                    },
                    "since_hours": {
                        "type": "integer",
                        "description": "Only items updated in the last N hours.",
                    },
                },
                "required": [],
            },
            handler=get_work_items,
        ),
        AgentTool(
            name="get_health_signals",
            description="Get health signals for team members (burnout risk, high WIP, after-hours work, PR review overdue, etc.).",
            parameters={
                "type": "object",
                "properties": {
                    "team_member_id": {
                        "type": "string",
                        "description": "Filter by team member. Omit for all.",
                    },
                    "severity": {
                        "type": "string",
                        "description": "Filter by severity: info, warning, critical.",
                    },
                },
                "required": [],
            },
            handler=get_health_signals,
        ),
        AgentTool(
            name="get_open_blockers",
            description="Get all open blocker flags across the team — includes description, ticket reference, and when it was flagged.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=get_open_blockers,
        ),
        AgentTool(
            name="get_recent_activity_events",
            description="Get raw activity events (commits, PR reviews, status changes) with after-hours and weekend flags.",
            parameters={
                "type": "object",
                "properties": {
                    "team_member_id": {
                        "type": "string",
                        "description": "Filter by team member.",
                    },
                    "since_hours": {
                        "type": "integer",
                        "description": "Look back period in hours. Default 24.",
                        "default": 24,
                    },
                },
                "required": [],
            },
            handler=get_recent_activity_events,
        ),
        AgentTool(
            name="get_standup_history",
            description="Get previous standup reports (completed items, in-progress, blockers, narrative) for context on what was reported before.",
            parameters={
                "type": "object",
                "properties": {
                    "team_member_id": {
                        "type": "string",
                        "description": "Filter by team member.",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Look back period in days. Default 7.",
                        "default": 7,
                    },
                },
                "required": [],
            },
            handler=get_standup_history,
        ),
    ]


# ===========================================================================
# Phase 2-4: Additional tools for Blocker / Health Coach / Retro agents
# ===========================================================================


# ---------------------------------------------------------------------------
# Tool: get_velocity_data
# ---------------------------------------------------------------------------

async def get_velocity_data(
    team_member_id: str | None = None,
    **kwargs: Any,
) -> dict:
    """Get velocity profiles (rolling average SP, by-type breakdown) for team members."""
    db, org_id = _ctx(kwargs.get("_context"))

    q = select(VelocityProfile).order_by(VelocityProfile.recorded_at.desc())
    if team_member_id:
        q = q.where(VelocityProfile.team_member_id == team_member_id)
    else:
        # Get latest profile per member
        q = q.limit(50)

    result = await db.execute(q)
    profiles = result.scalars().all()

    return {
        "profiles": [
            {
                "team_member_id": p.team_member_id,
                "iteration_id": p.iteration_id,
                "planned_sp": p.planned_sp,
                "completed_sp": p.completed_sp,
                "rolling_average": p.rolling_average,
                "by_ticket_type": p.by_ticket_type,
                "is_cold_start": p.is_cold_start,
                "recorded_at": str(p.recorded_at),
            }
            for p in profiles
        ],
    }


# ---------------------------------------------------------------------------
# Tool: get_sprint_forecast
# ---------------------------------------------------------------------------

async def get_sprint_forecast(**kwargs: Any) -> dict:
    """Get active sprint info: iteration dates, pacing, completion stats."""
    db, org_id = _ctx(kwargs.get("_context"))

    # Find active iteration
    iter_result = await db.execute(
        select(Iteration)
        .where(
            Iteration.organization_id == org_id,
            Iteration.state == "active",
        )
        .order_by(Iteration.start_date.desc())
        .limit(1)
    )
    iteration = iter_result.scalar_one_or_none()

    if not iteration:
        return {"active_sprint": None, "message": "No active sprint found"}

    now = datetime.now(timezone.utc)

    # Work item stats for this iteration
    total_q = await db.execute(
        select(func.count()).select_from(WorkItem)
        .where(WorkItem.iteration_id == iteration.id)
    )
    total_items = total_q.scalar() or 0

    done_q = await db.execute(
        select(func.count()).select_from(WorkItem)
        .where(WorkItem.iteration_id == iteration.id, WorkItem.status == "DONE")
    )
    done_items = done_q.scalar() or 0

    sp_total_q = await db.execute(
        select(func.coalesce(func.sum(WorkItem.story_points), 0))
        .where(WorkItem.iteration_id == iteration.id)
    )
    sp_total = sp_total_q.scalar() or 0

    sp_done_q = await db.execute(
        select(func.coalesce(func.sum(WorkItem.story_points), 0))
        .where(WorkItem.iteration_id == iteration.id, WorkItem.status == "DONE")
    )
    sp_done = sp_done_q.scalar() or 0

    # Pacing
    total_days = (iteration.end_date - iteration.start_date).days if iteration.start_date and iteration.end_date else 14
    elapsed_days = (now - iteration.start_date).days if iteration.start_date else 0
    time_pct = min(elapsed_days / max(total_days, 1), 1.0)
    work_pct = done_items / max(total_items, 1)

    return {
        "active_sprint": {
            "id": iteration.id,
            "name": iteration.name,
            "goal": iteration.goal,
            "start_date": str(iteration.start_date) if iteration.start_date else None,
            "end_date": str(iteration.end_date) if iteration.end_date else None,
            "total_days": total_days,
            "elapsed_days": elapsed_days,
            "days_remaining": max(total_days - elapsed_days, 0),
            "time_pct": round(time_pct * 100, 1),
            "total_items": total_items,
            "done_items": done_items,
            "completion_pct": round(work_pct * 100, 1),
            "total_sp": sp_total,
            "completed_sp": sp_done,
        },
    }


# ---------------------------------------------------------------------------
# Tool: get_retro_history
# ---------------------------------------------------------------------------

async def get_retro_history(
    limit: int = 3,
    **kwargs: Any,
) -> dict:
    """Get past retrospectives with action items for pattern detection."""
    db, org_id = _ctx(kwargs.get("_context"))

    q = (
        select(Retrospective)
        .where(Retrospective.organization_id == org_id)
        .order_by(Retrospective.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(q)
    retros = result.scalars().all()

    retro_list = []
    for r in retros:
        # Load action items
        ai_q = await db.execute(
            select(RetroActionItem)
            .where(RetroActionItem.retrospective_id == r.id)
            .order_by(RetroActionItem.created_at)
        )
        actions = ai_q.scalars().all()

        retro_list.append({
            "id": r.id,
            "iteration_id": r.iteration_id,
            "what_went_well": r.what_went_well,
            "what_didnt_go_well": r.what_didnt_go_well,
            "root_cause_analysis": r.root_cause_analysis,
            "failure_classification": r.failure_classification,
            "pattern_detected": r.pattern_detected,
            "consecutive_failure_count": r.consecutive_failure_count,
            "feed_forward_signals": r.feed_forward_signals,
            "created_at": str(r.created_at),
            "action_items": [
                {
                    "title": a.title,
                    "assignee_id": a.assignee_id,
                    "status": a.status,
                    "is_carry_forward": a.is_carry_forward,
                    "due_date": str(a.due_date) if a.due_date else None,
                }
                for a in actions
            ],
        })

    return {"retrospectives": retro_list}


# ---------------------------------------------------------------------------
# Tool: get_sprint_plan_data
# ---------------------------------------------------------------------------

async def get_sprint_plan_data(
    iteration_id: str | None = None,
    **kwargs: Any,
) -> dict:
    """Get sprint plan details: assignments, confidence scores, risk flags."""
    db, org_id = _ctx(kwargs.get("_context"))

    q = (
        select(SprintPlan)
        .where(SprintPlan.organization_id == org_id)
        .order_by(SprintPlan.created_at.desc())
        .limit(3)
    )
    if iteration_id:
        q = q.where(SprintPlan.iteration_id == iteration_id)

    result = await db.execute(q)
    plans = result.scalars().all()

    plan_list = []
    for p in plans:
        # Load assignments
        assign_q = await db.execute(
            select(PlanAssignment).where(PlanAssignment.sprint_plan_id == p.id)
        )
        assignments = assign_q.scalars().all()

        plan_list.append({
            "id": p.id,
            "iteration_id": p.iteration_id,
            "status": p.status,
            "confidence_score": p.confidence_score,
            "total_story_points": p.total_story_points,
            "overall_rationale": p.overall_rationale,
            "risk_summary": p.risk_summary,
            "goal_attainment_confidence": p.goal_attainment_confidence,
            "estimated_sprints": p.estimated_sprints,
            "created_at": str(p.created_at),
            "assignments": [
                {
                    "work_item_id": a.work_item_id,
                    "team_member_id": a.team_member_id,
                    "story_points": a.story_points,
                    "confidence_score": a.confidence_score,
                    "risk_flags": a.risk_flags,
                    "sprint_number": a.sprint_number,
                }
                for a in assignments
            ],
        })

    return {"plans": plan_list}


# ---------------------------------------------------------------------------
# Tool: send_notification (wraps message_router)
# ---------------------------------------------------------------------------

async def send_notification(
    recipient_email: str,
    notification_type: str,
    title: str,
    body: str,
    **kwargs: Any,
) -> dict:
    """Send an in-app notification to a team member. Used by agents to alert about blockers, health concerns, etc."""
    db, org_id = _ctx(kwargs.get("_context"))

    try:
        from .message_router import deliver_notification
        await deliver_notification(
            db=db,
            org_id=org_id,
            recipient_email=recipient_email,
            notification_type=notification_type,
            slack_payload=None,
            teams_payload=None,
            in_app_payload={
                "title": title,
                "body": body,
            },
        )
        return {"sent": True, "channel": "in_app", "recipient": recipient_email}
    except Exception as e:
        return {"sent": False, "error": str(e)[:200]}


# ===========================================================================
# Tool Builders for Phase 2-4 Agents
# ===========================================================================

# Shared tool schema definitions (reused across builders)
_TEAM_MEMBER_TOOL = AgentTool(
    name="get_team_members",
    description="Get all team members in the organization with their IDs, names, roles, and skills.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=get_team_members,
)

_WORK_ITEMS_TOOL = AgentTool(
    name="get_work_items",
    description="Get work items (tickets) from Jira/ADO. Can filter by assignee, status (TODO, IN_PROGRESS, IN_REVIEW, DONE), or recency.",
    parameters={
        "type": "object",
        "properties": {
            "team_member_id": {"type": "string", "description": "Filter by assignee. Omit for all."},
            "status": {"type": "string", "description": "Filter by status: TODO, IN_PROGRESS, IN_REVIEW, DONE."},
            "since_hours": {"type": "integer", "description": "Only items updated in the last N hours."},
        },
        "required": [],
    },
    handler=get_work_items,
)

_GITHUB_TOOL = AgentTool(
    name="get_github_activity",
    description="Get recent GitHub activity (commits and pull requests) for a specific team member or the whole team.",
    parameters={
        "type": "object",
        "properties": {
            "team_member_id": {"type": "string", "description": "Filter by team member ID. Omit for all members."},
            "since_hours": {"type": "integer", "description": "Look back this many hours. Default 24.", "default": 24},
        },
        "required": [],
    },
    handler=get_github_activity,
)

_HEALTH_SIGNALS_TOOL = AgentTool(
    name="get_health_signals",
    description="Get health signals for team members (burnout risk, high WIP, after-hours work, PR review overdue, etc.).",
    parameters={
        "type": "object",
        "properties": {
            "team_member_id": {"type": "string", "description": "Filter by team member. Omit for all."},
            "severity": {"type": "string", "description": "Filter by severity: info, warning, critical."},
        },
        "required": [],
    },
    handler=get_health_signals,
)

_OPEN_BLOCKERS_TOOL = AgentTool(
    name="get_open_blockers",
    description="Get all open blocker flags across the team — includes description, ticket reference, and when it was flagged.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=get_open_blockers,
)

_VELOCITY_TOOL = AgentTool(
    name="get_velocity_data",
    description="Get velocity profiles for team members: rolling average SP, planned vs completed, by-type breakdown.",
    parameters={
        "type": "object",
        "properties": {
            "team_member_id": {"type": "string", "description": "Filter by team member. Omit for all."},
        },
        "required": [],
    },
    handler=get_velocity_data,
)

_SPRINT_FORECAST_TOOL = AgentTool(
    name="get_sprint_forecast",
    description="Get active sprint info: dates, pacing, completion percentage, SP totals, days remaining.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=get_sprint_forecast,
)

_NOTIFICATION_TOOL = AgentTool(
    name="send_notification",
    description="Send an in-app notification to a team member by email. Types: blocker_alert, health_alert, retro_action.",
    parameters={
        "type": "object",
        "properties": {
            "recipient_email": {"type": "string", "description": "Email of the recipient."},
            "notification_type": {"type": "string", "description": "Type: blocker_alert, health_alert, retro_action."},
            "title": {"type": "string", "description": "Notification title."},
            "body": {"type": "string", "description": "Notification body text."},
        },
        "required": ["recipient_email", "notification_type", "title", "body"],
    },
    handler=send_notification,
)


def build_blocker_detection_tools() -> list[AgentTool]:
    """Tools available to the Smart Blocker Detection agent."""
    return [
        _TEAM_MEMBER_TOOL,
        _WORK_ITEMS_TOOL,
        _GITHUB_TOOL,
        _HEALTH_SIGNALS_TOOL,
        _OPEN_BLOCKERS_TOOL,
        AgentTool(
            name="get_recent_activity_events",
            description="Get raw activity events (commits, PR reviews, status changes) with after-hours and weekend flags.",
            parameters={
                "type": "object",
                "properties": {
                    "team_member_id": {"type": "string", "description": "Filter by team member."},
                    "since_hours": {"type": "integer", "description": "Look back period in hours. Default 24.", "default": 24},
                },
                "required": [],
            },
            handler=get_recent_activity_events,
        ),
        _NOTIFICATION_TOOL,
    ]


def build_health_coach_tools() -> list[AgentTool]:
    """Tools available to the Sprint Health Coach agent."""
    return [
        _TEAM_MEMBER_TOOL,
        _WORK_ITEMS_TOOL,
        _HEALTH_SIGNALS_TOOL,
        _OPEN_BLOCKERS_TOOL,
        _VELOCITY_TOOL,
        _SPRINT_FORECAST_TOOL,
        AgentTool(
            name="get_standup_history",
            description="Get previous standup reports for patterns on repeated blockers or stalling.",
            parameters={
                "type": "object",
                "properties": {
                    "team_member_id": {"type": "string", "description": "Filter by team member."},
                    "days": {"type": "integer", "description": "Look back period in days. Default 7.", "default": 7},
                },
                "required": [],
            },
            handler=get_standup_history,
        ),
        _NOTIFICATION_TOOL,
    ]


def build_retro_tools() -> list[AgentTool]:
    """Tools available to the AI Retrospective Synthesizer agent."""
    return [
        _TEAM_MEMBER_TOOL,
        _WORK_ITEMS_TOOL,
        _HEALTH_SIGNALS_TOOL,
        _OPEN_BLOCKERS_TOOL,
        _VELOCITY_TOOL,
        _SPRINT_FORECAST_TOOL,
        AgentTool(
            name="get_standup_history",
            description="Get standup reports from the sprint for theme extraction.",
            parameters={
                "type": "object",
                "properties": {
                    "team_member_id": {"type": "string", "description": "Filter by team member."},
                    "days": {"type": "integer", "description": "Look back period in days. Default 14.", "default": 14},
                },
                "required": [],
            },
            handler=get_standup_history,
        ),
        AgentTool(
            name="get_retro_history",
            description="Get past retrospectives (last 3) with action items, root causes, and failure classifications for pattern detection.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of past retros to fetch. Default 3.", "default": 3},
                },
                "required": [],
            },
            handler=get_retro_history,
        ),
        AgentTool(
            name="get_sprint_plan_data",
            description="Get sprint plan details: assignments, confidence scores, risk flags for the current or recent sprints.",
            parameters={
                "type": "object",
                "properties": {
                    "iteration_id": {"type": "string", "description": "Filter by specific sprint. Omit for most recent."},
                },
                "required": [],
            },
            handler=get_sprint_plan_data,
        ),
    ]

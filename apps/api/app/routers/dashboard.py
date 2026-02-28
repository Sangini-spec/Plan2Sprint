"""
Dashboard data API — serves real data from synced DB for dashboard panels.

All queries are scoped to the user's org and optionally to a selected project.

GET /api/dashboard/summary       — Sprint summary stats (work items, velocity, health)
GET /api/dashboard/work-items    — Work items list with filters
GET /api/dashboard/team          — Team member stats + assigned work
GET /api/dashboard/sprints       — Active and recent iterations
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query as Q
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, case
from sqlalchemy.orm import selectinload

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models.work_item import WorkItem
from ..models.iteration import Iteration
from ..models.team_member import TeamMember
from ..models.analytics import HealthSignal, VelocityProfile
from ..models.repository import PullRequest, Commit
from ..models.imported_project import ImportedProject

router = APIRouter()


def _wi_filters(org_id: str, project_id: str | None):
    """Base WHERE conditions for work items — scoped to project when provided."""
    conds = [WorkItem.organization_id == org_id]
    if project_id:
        conds.append(WorkItem.imported_project_id == project_id)
    return conds


def _iter_filters(org_id: str, project_id: str | None):
    """Base WHERE conditions for iterations — scoped to project when provided."""
    conds = [Iteration.organization_id == org_id]
    if project_id:
        conds.append(Iteration.imported_project_id == project_id)
    return conds


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    projectId: str | None = Q(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sprint summary stats for the PO dashboard top cards."""
    org_id = current_user.get("organization_id", "demo-org")
    wi_conds = _wi_filters(org_id, projectId)

    # Total work items
    total = await db.execute(
        select(func.count()).select_from(WorkItem).where(*wi_conds)
    )
    total_count = total.scalar() or 0

    # Status breakdown
    status_query = (
        select(WorkItem.status, func.count().label("cnt"))
        .where(*wi_conds)
        .group_by(WorkItem.status)
    )
    status_result = await db.execute(status_query)
    status_counts: dict[str, int] = {}
    for row in status_result.all():
        status_counts[row[0]] = row[1]

    in_progress = status_counts.get("IN_PROGRESS", 0)
    done = status_counts.get("DONE", 0)
    todo = status_counts.get("TODO", 0) + status_counts.get("BACKLOG", 0)
    in_review = status_counts.get("IN_REVIEW", 0)
    blocked = status_counts.get("CANCELLED", 0)

    # Story points
    sp_result = await db.execute(
        select(func.coalesce(func.sum(WorkItem.story_points), 0))
        .where(*wi_conds)
    )
    total_sp = float(sp_result.scalar() or 0)

    sp_done_result = await db.execute(
        select(func.coalesce(func.sum(WorkItem.story_points), 0))
        .where(*wi_conds, WorkItem.status == "DONE")
    )
    done_sp = float(sp_done_result.scalar() or 0)

    # Team members
    member_count = await db.execute(
        select(func.count()).select_from(TeamMember)
        .where(TeamMember.organization_id == org_id)
    )
    team_size = member_count.scalar() or 0

    # Active sprints (scoped to project)
    iter_conds = _iter_filters(org_id, projectId)
    active_sprints = await db.execute(
        select(func.count()).select_from(Iteration)
        .where(*iter_conds, Iteration.state == "active")
    )
    active_sprint_count = active_sprints.scalar() or 0

    # Health signals (unresolved)
    signal_count = await db.execute(
        select(func.count()).select_from(HealthSignal)
        .where(HealthSignal.organization_id == org_id)
        .where(HealthSignal.resolved_at.is_(None))
    )
    active_signals = signal_count.scalar() or 0

    # Open PRs
    pr_count = await db.execute(
        select(func.count()).select_from(PullRequest)
        .where(PullRequest.status.in_(["OPEN", "AWAITING_REVIEW", "CHANGES_REQUESTED"]))
    )
    open_prs = pr_count.scalar() or 0

    # Sprint progress
    completion_pct = int((done / total_count) * 100) if total_count > 0 else 0

    return {
        "totalItems": total_count,
        "statusBreakdown": {
            "todo": todo,
            "inProgress": in_progress,
            "inReview": in_review,
            "done": done,
            "blocked": blocked,
        },
        "storyPoints": {
            "total": total_sp,
            "completed": done_sp,
            "remaining": total_sp - done_sp,
        },
        "teamSize": team_size,
        "activeSprints": active_sprint_count,
        "openPrs": open_prs,
        "healthSignals": active_signals,
        "completionPct": completion_pct,
    }


@router.get("/dashboard/work-items")
async def get_dashboard_work_items(
    projectId: str | None = Q(None),
    status: str | None = Q(None),
    type: str | None = Q(None),
    assignee: str | None = Q(None),
    limit: int = Q(50),
    offset: int = Q(0),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Work items list with optional filters."""
    org_id = current_user.get("organization_id", "demo-org")
    wi_conds = _wi_filters(org_id, projectId)

    query = (
        select(WorkItem)
        .where(*wi_conds)
        .options(selectinload(WorkItem.assignee))
        .order_by(WorkItem.priority.asc(), WorkItem.updated_at.desc())
    )

    if status:
        query = query.where(WorkItem.status == status.upper())
    if type:
        query = query.where(WorkItem.type == type.lower())
    if assignee:
        query = query.where(WorkItem.assignee_id == assignee)

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "workItems": [
            {
                "id": wi.id,
                "externalId": wi.external_id,
                "title": wi.title,
                "status": wi.status,
                "type": wi.type,
                "priority": wi.priority,
                "storyPoints": wi.story_points,
                "assignee": wi.assignee.display_name if wi.assignee else None,
                "assigneeId": wi.assignee_id,
                "sourceTool": wi.source_tool,
                "labels": wi.labels or [],
                "updatedAt": wi.updated_at.isoformat() if wi.updated_at else None,
            }
            for wi in items
        ]
    }


@router.get("/dashboard/team")
async def get_dashboard_team(
    projectId: str | None = Q(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Team member stats with assigned work counts."""
    org_id = current_user.get("organization_id", "demo-org")

    result = await db.execute(
        select(TeamMember)
        .where(TeamMember.organization_id == org_id)
        .order_by(TeamMember.display_name)
    )
    members = result.scalars().all()

    team = []
    for m in members:
        # Count work items by status (scoped to project if provided)
        wi_conds = [WorkItem.assignee_id == m.id]
        if projectId:
            wi_conds.append(WorkItem.imported_project_id == projectId)

        wi_result = await db.execute(
            select(WorkItem.status, func.count().label("cnt"))
            .where(*wi_conds)
            .group_by(WorkItem.status)
        )
        status_counts: dict[str, int] = {}
        for row in wi_result.all():
            status_counts[row[0]] = row[1]

        total_assigned = sum(status_counts.values())
        in_progress = status_counts.get("IN_PROGRESS", 0)
        done = status_counts.get("DONE", 0)

        # Story points (scoped to project if provided)
        sp_result = await db.execute(
            select(func.coalesce(func.sum(WorkItem.story_points), 0))
            .where(*wi_conds)
        )
        total_sp = float(sp_result.scalar() or 0)

        team.append({
            "id": m.id,
            "name": m.display_name,
            "email": m.email,
            "avatarUrl": m.avatar_url,
            "capacity": m.default_capacity,
            "totalAssigned": total_assigned,
            "inProgress": in_progress,
            "done": done,
            "totalStoryPoints": total_sp,
            "skillTags": m.skill_tags or [],
        })

    return {"team": team}


@router.get("/dashboard/sprints")
async def get_dashboard_sprints(
    projectId: str | None = Q(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Active and recent iterations with work item counts."""
    org_id = current_user.get("organization_id", "demo-org")
    iter_conds = _iter_filters(org_id, projectId)

    result = await db.execute(
        select(Iteration)
        .where(*iter_conds)
        .order_by(Iteration.start_date.desc())
        .limit(10)
    )
    iterations = result.scalars().all()

    sprints = []
    for it in iterations:
        # Count work items in this iteration
        wi_result = await db.execute(
            select(WorkItem.status, func.count().label("cnt"))
            .where(WorkItem.iteration_id == it.id)
            .group_by(WorkItem.status)
        )
        status_counts: dict[str, int] = {}
        for row in wi_result.all():
            status_counts[row[0]] = row[1]

        total = sum(status_counts.values())
        done = status_counts.get("DONE", 0)

        # Story points in this iteration
        sp_result = await db.execute(
            select(
                func.coalesce(func.sum(WorkItem.story_points), 0),
                func.coalesce(
                    func.sum(
                        case(
                            (WorkItem.status == "DONE", WorkItem.story_points),
                            else_=0.0,
                        )
                    ), 0
                ),
            )
            .where(WorkItem.iteration_id == it.id)
        )
        sp_row = sp_result.one()
        total_sp = float(sp_row[0])
        done_sp = float(sp_row[1])

        sprints.append({
            "id": it.id,
            "name": it.name,
            "state": it.state,
            "startDate": it.start_date.isoformat() if it.start_date else None,
            "endDate": it.end_date.isoformat() if it.end_date else None,
            "sourceTool": it.source_tool,
            "totalItems": total,
            "completedItems": done,
            "totalStoryPoints": total_sp,
            "completedStoryPoints": done_sp,
            "completionPct": int((done / total) * 100) if total > 0 else 0,
        })

    return {"sprints": sprints}

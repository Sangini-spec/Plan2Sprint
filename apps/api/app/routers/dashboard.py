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

    # ── Auto-complete expired sprints on dashboard load ──
    try:
        from ..services.sprint_completion import check_and_complete_sprints
        completed = await check_and_complete_sprints(db, org_id, projectId)
        if completed:
            import logging
            logging.getLogger(__name__).info(
                f"Auto-completed {len(completed)} sprint(s) on dashboard load"
            )
    except Exception:
        pass  # Non-fatal — dashboard still loads

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

    # Active sprints (scoped to project, with org-wide fallback)
    iter_conds = _iter_filters(org_id, projectId)
    active_sprints = await db.execute(
        select(func.count()).select_from(Iteration)
        .where(*iter_conds, Iteration.state == "active")
    )
    active_sprint_count = active_sprints.scalar() or 0

    # Fallback: if no project-scoped active sprints, try org-wide
    if active_sprint_count == 0 and projectId:
        fallback_sprints = await db.execute(
            select(func.count()).select_from(Iteration)
            .where(Iteration.organization_id == org_id, Iteration.state == "active")
        )
        active_sprint_count = fallback_sprints.scalar() or 0

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
    iterationId: str | None = Q(None),
    sprintState: str | None = Q(None),
    status: str | None = Q(None),
    type: str | None = Q(None),
    assignee: str | None = Q(None),
    limit: int = Q(50),
    offset: int = Q(0),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Work items list with optional filters.

    New params:
      iterationId — filter by specific iteration (sprint)
      sprintState — filter by iteration state ("active" → only items in the active sprint)
    """
    org_id = current_user.get("organization_id", "demo-org")
    wi_conds = _wi_filters(org_id, projectId)

    query = (
        select(WorkItem)
        .where(*wi_conds)
        .options(selectinload(WorkItem.assignee))
        .order_by(WorkItem.priority.asc(), WorkItem.updated_at.desc())
    )

    # Filter by iteration (sprint)
    if iterationId:
        query = query.where(WorkItem.iteration_id == iterationId)
    elif sprintState:
        # Find iterations matching that state and filter work items to them
        iter_conds = _iter_filters(org_id, projectId)
        iter_subq = (
            select(Iteration.id)
            .where(*iter_conds, Iteration.state == sprintState.lower())
        )
        query = query.where(WorkItem.iteration_id.in_(iter_subq))

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
                "sourceStatus": wi.source_status,
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

    # Batch: status counts + SP per member in TWO queries (was 2*N)
    member_ids = [m.id for m in members]
    status_map: dict[str, dict[str, int]] = {mid: {} for mid in member_ids}
    sp_map: dict[str, float] = {}

    if member_ids:
        wi_conds_base = [WorkItem.assignee_id.in_(member_ids)]
        if projectId:
            wi_conds_base.append(WorkItem.imported_project_id == projectId)

        # Status counts per member — single query
        status_result = await db.execute(
            select(
                WorkItem.assignee_id,
                WorkItem.status,
                func.count().label("cnt"),
            )
            .where(*wi_conds_base)
            .group_by(WorkItem.assignee_id, WorkItem.status)
        )
        for row in status_result.all():
            status_map.setdefault(row[0], {})[row[1]] = row[2]

        # Story points per member — single query
        sp_result = await db.execute(
            select(
                WorkItem.assignee_id,
                func.coalesce(func.sum(WorkItem.story_points), 0).label("sp"),
            )
            .where(*wi_conds_base)
            .group_by(WorkItem.assignee_id)
        )
        for row in sp_result.all():
            sp_map[row[0]] = float(row[1])

    team = []
    for m in members:
        sc = status_map.get(m.id, {})
        total_assigned = sum(sc.values())
        in_progress = sc.get("IN_PROGRESS", 0)
        done = sc.get("DONE", 0)
        total_sp = sp_map.get(m.id, 0.0)

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
    iterations = list(result.scalars().all())

    # Fallback: if no project-scoped iterations, try org-wide
    if not iterations and projectId:
        result = await db.execute(
            select(Iteration)
            .where(Iteration.organization_id == org_id)
            .order_by(Iteration.start_date.desc())
            .limit(10)
        )
        iterations = list(result.scalars().all())

    # Batch: status counts + SP per iteration in TWO queries (was 2*N)
    iter_ids = [it.id for it in iterations]
    iter_status_map: dict[str, dict[str, int]] = {iid: {} for iid in iter_ids}
    iter_sp_map: dict[str, tuple[float, float]] = {}

    if iter_ids:
        # Status counts per iteration — single query
        iter_status_result = await db.execute(
            select(
                WorkItem.iteration_id,
                WorkItem.status,
                func.count().label("cnt"),
            )
            .where(WorkItem.iteration_id.in_(iter_ids))
            .group_by(WorkItem.iteration_id, WorkItem.status)
        )
        for row in iter_status_result.all():
            iter_status_map.setdefault(row[0], {})[row[1]] = row[2]

        # Story points per iteration — single query
        iter_sp_result = await db.execute(
            select(
                WorkItem.iteration_id,
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
            .where(WorkItem.iteration_id.in_(iter_ids))
            .group_by(WorkItem.iteration_id)
        )
        for row in iter_sp_result.all():
            iter_sp_map[row[0]] = (float(row[1]), float(row[2]))

    sprints = []
    for it in iterations:
        sc = iter_status_map.get(it.id, {})
        total = sum(sc.values())
        done = sc.get("DONE", 0)
        total_sp, done_sp = iter_sp_map.get(it.id, (0.0, 0.0))

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


# ---------------------------------------------------------------------------
# PATCH /api/work-items/{id}/status — Update work item status in local DB
# ---------------------------------------------------------------------------

@router.patch("/work-items/{item_id}/status")
async def update_work_item_status(
    item_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a work item's status in the local DB only (for manual board moves).
    Does NOT write back to ADO/Jira — that happens on "Approve & Sync".

    Body: { "status": "IN_PROGRESS" }
    """
    org_id = current_user.get("organization_id", "demo-org")
    new_status = body.get("status", "").upper()

    valid_statuses = {"BACKLOG", "TODO", "IN_PROGRESS", "IN_REVIEW", "DONE", "CANCELLED"}
    if new_status not in valid_statuses:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(valid_statuses))}",
        )

    result = await db.execute(
        select(WorkItem).where(
            WorkItem.id == item_id,
            WorkItem.organization_id == org_id,
        )
    )
    wi = result.scalar_one_or_none()

    if not wi:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Work item not found")

    old_status = wi.status
    wi.status = new_status
    await db.commit()

    return {
        "ok": True,
        "workItemId": item_id,
        "oldStatus": old_status,
        "newStatus": new_status,
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/feature-progress — Feature/Epic progress for overview
# ---------------------------------------------------------------------------

def _derive_phase(source_status: str | None) -> str:
    """Derive a phase badge from a feature's raw source status."""
    if not source_status:
        return "PLANNING"
    s = source_status.lower()
    if s in ("resolved", "done", "closed"):
        return "TESTING"
    if s in ("active", "committed", "in progress"):
        return "DEVELOPMENT"
    return "PLANNING"


@router.get("/dashboard/feature-progress")
async def get_feature_progress(
    projectId: str | None = Q(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Feature/epic progress cards — aggregates child story counts per feature.

    Returns top-level KPIs and per-feature breakdown:
    done / inProgress / readyForTest / remaining with % complete.
    """
    org_id = current_user.get("organization_id", "demo-org")
    wi_conds = _wi_filters(org_id, projectId)

    # 1. Fetch features/epics
    feature_result = await db.execute(
        select(WorkItem)
        .where(*wi_conds, WorkItem.type.in_(["feature", "epic"]))
        .order_by(WorkItem.priority.asc(), WorkItem.title.asc())
    )
    features = feature_result.scalars().all()

    if not features:
        return {
            "totalFeatures": 0,
            "totalStories": 0,
            "overallCompletePct": 0,
            "readyForTestCount": 0,
            "features": [],
        }

    feature_ids = [f.id for f in features]

    # 2. Aggregate child work items by epic_id + status (single query)
    child_agg = await db.execute(
        select(
            WorkItem.epic_id,
            WorkItem.status,
            func.count().label("cnt"),
        )
        .where(
            WorkItem.organization_id == org_id,
            WorkItem.epic_id.in_(feature_ids),
        )
        .group_by(WorkItem.epic_id, WorkItem.status)
    )

    # Build per-feature status maps
    feature_status: dict[str, dict[str, int]] = {fid: {} for fid in feature_ids}
    for row in child_agg.all():
        feature_status.setdefault(row[0], {})[row[1]] = row[2]

    # 3. Build response
    total_stories = 0
    total_done = 0
    total_ready_for_test = 0
    feature_cards = []

    for f in features:
        sc = feature_status.get(f.id, {})
        done = sc.get("DONE", 0)
        in_progress = sc.get("IN_PROGRESS", 0)
        ready_for_test = sc.get("IN_REVIEW", 0)
        remaining = sc.get("TODO", 0) + sc.get("BACKLOG", 0) + sc.get("CANCELLED", 0)
        story_count = done + in_progress + ready_for_test + remaining
        pct = int((done / story_count) * 100) if story_count > 0 else 0

        total_stories += story_count
        total_done += done
        total_ready_for_test += ready_for_test

        feature_cards.append({
            "id": f.id,
            "externalId": f.external_id,
            "title": f.title,
            "description": (f.description or "")[:120],
            "phase": _derive_phase(f.source_status),
            "completePct": pct,
            "totalStories": story_count,
            "breakdown": {
                "done": done,
                "inProgress": in_progress,
                "readyForTest": ready_for_test,
                "remaining": remaining,
            },
            "plannedStart": f.planned_start.isoformat() if f.planned_start else None,
            "plannedEnd": f.planned_end.isoformat() if f.planned_end else None,
            "sourceStatus": f.source_status,
            "sourceTool": f.source_tool,
        })

    overall_pct = int((total_done / total_stories) * 100) if total_stories > 0 else 0

    return {
        "totalFeatures": len(features),
        "totalStories": total_stories,
        "overallCompletePct": overall_pct,
        "readyForTestCount": total_ready_for_test,
        "features": feature_cards,
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/project-plan — Gantt data for Project Plan tab
# ---------------------------------------------------------------------------

@router.get("/dashboard/project-plan")
async def get_project_plan(
    projectId: str | None = Q(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Project Plan / Gantt timeline — features with planned vs actual progress.

    Returns features grouped by phase, with planned dates, assignees,
    completion %, and status for Gantt rendering.
    """
    org_id = current_user.get("organization_id", "demo-org")
    wi_conds = _wi_filters(org_id, projectId)

    # 1. Fetch features ordered by planned_start
    feature_result = await db.execute(
        select(WorkItem)
        .where(*wi_conds, WorkItem.type.in_(["feature", "epic"]))
        .order_by(
            WorkItem.planned_start.asc().nullslast(),
            WorkItem.title.asc(),
        )
    )
    features = feature_result.scalars().all()

    if not features:
        return {"features": [], "phases": [], "totalPhases": 0, "complete": 0, "inProgress": 0}

    feature_ids = [f.id for f in features]

    # 2. Aggregate child work items by epic_id + status (same as feature-progress)
    child_agg = await db.execute(
        select(
            WorkItem.epic_id,
            WorkItem.status,
            func.count().label("cnt"),
        )
        .where(
            WorkItem.organization_id == org_id,
            WorkItem.epic_id.in_(feature_ids),
        )
        .group_by(WorkItem.epic_id, WorkItem.status)
    )
    feature_status: dict[str, dict[str, int]] = {fid: {} for fid in feature_ids}
    for row in child_agg.all():
        feature_status.setdefault(row[0], {})[row[1]] = row[2]

    # 3. Top assignees per feature (most-assigned developers) — single query
    assignee_agg = await db.execute(
        select(
            WorkItem.epic_id,
            TeamMember.display_name,
            func.count().label("cnt"),
        )
        .join(TeamMember, TeamMember.id == WorkItem.assignee_id)
        .where(
            WorkItem.organization_id == org_id,
            WorkItem.epic_id.in_(feature_ids),
        )
        .group_by(WorkItem.epic_id, TeamMember.display_name)
        .order_by(func.count().desc())
    )
    feature_assignees: dict[str, list[str]] = {fid: [] for fid in feature_ids}
    for row in assignee_agg.all():
        if len(feature_assignees.get(row[0], [])) < 3:
            feature_assignees.setdefault(row[0], []).append(row[1])

    # 4. Build per-feature rows
    rows = []
    phase_counts: dict[str, int] = {}
    complete_count = 0
    in_progress_count = 0

    for f in features:
        sc = feature_status.get(f.id, {})
        done = sc.get("DONE", 0)
        total = sum(sc.values())
        pct = int((done / total) * 100) if total > 0 else 0
        phase = _derive_phase(f.source_status)

        # Derive Gantt status
        src_lower = (f.source_status or "").lower()
        if pct == 100:
            gantt_status = "complete"
            complete_count += 1
        elif "block" in src_lower:
            gantt_status = "blocked"
        elif pct > 0:
            gantt_status = "in_progress"
            in_progress_count += 1
        else:
            gantt_status = "not_started"

        phase_counts[phase] = phase_counts.get(phase, 0) + 1

        rows.append({
            "id": f.id,
            "externalId": f.external_id,
            "title": f.title,
            "phase": phase,
            "status": gantt_status,
            "completePct": pct,
            "totalStories": total,
            "doneStories": done,
            "plannedStart": f.planned_start.isoformat() if f.planned_start else None,
            "plannedEnd": f.planned_end.isoformat() if f.planned_end else None,
            "assignees": feature_assignees.get(f.id, []),
        })

    # Estimate duration from date range
    all_starts = [f.planned_start for f in features if f.planned_start]
    all_ends = [f.planned_end for f in features if f.planned_end]
    est_weeks = None
    if all_starts and all_ends:
        span = max(all_ends) - min(all_starts)
        est_weeks = max(1, round(span.days / 7))

    return {
        "features": rows,
        "phases": [{"name": k, "count": v} for k, v in phase_counts.items()],
        "totalPhases": len(phase_counts),
        "complete": complete_count,
        "inProgress": in_progress_count,
        "estDurationWeeks": est_weeks,
    }

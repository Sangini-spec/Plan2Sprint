"""
Dashboard data API — serves real data from synced DB for dashboard panels.
Phase-aware: uses project_phases + assignment rules (v2).

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
from ..models.sprint_plan import SprintPlan, PlanAssignment

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
                "iterationId": wi.iteration_id,
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

async def _load_phase_context(
    db: AsyncSession, org_id: str, project_id: str | None
) -> tuple[dict[str, dict], list[dict]]:
    """
    Load phases + rules for a project.  Returns:
      - phase_map: {phase_id: {id, name, slug, color, sortOrder}}
      - rules: flat list for resolve_phase_for_feature()
    Falls back to legacy derivation if no project_id.
    """
    if not project_id:
        return {}, []

    from ..models.project_phase import ProjectPhase, PhaseAssignmentRule
    from ..routers.phases import resolve_phase_for_feature, _seed_defaults, _load_rules_flat, _ensure_board_column_rules

    # Auto-seed if no phases exist
    from sqlalchemy import func as safunc
    count = (await db.execute(
        select(safunc.count()).where(
            ProjectPhase.project_id == project_id,
            ProjectPhase.organization_id == org_id,
        )
    )).scalar() or 0
    if count == 0:
        await _seed_defaults(db, project_id, org_id)
    else:
        # Ensure board_column rules exist on existing default phases
        await _ensure_board_column_rules(db, project_id, org_id)

    # Load phases
    phase_rows = (await db.execute(
        select(ProjectPhase)
        .where(ProjectPhase.project_id == project_id, ProjectPhase.organization_id == org_id)
        .order_by(ProjectPhase.sort_order)
    )).scalars().all()

    phase_map = {
        p.id: {
            "id": p.id,
            "name": p.name,
            "slug": p.slug,
            "color": p.color,
            "sortOrder": p.sort_order,
            "isDefault": p.is_default,
        }
        for p in phase_rows
    }

    rules = await _load_rules_flat(db, project_id, org_id)
    return phase_map, rules


def _resolve_feature_phase(
    feature,
    phase_map: dict[str, dict],
    rules: list[dict],
    *,
    persist: bool = False,
) -> str | None:
    """Resolve phase_id for a feature — manual override > rules > None.

    If *persist* is True the resolved phase_id is written back onto
    the ORM object so a subsequent ``db.commit()`` saves it — making
    future requests deterministic without re-running rules.
    """
    # Manual override (already persisted)
    if feature.phase_id and feature.phase_id in phase_map:
        return feature.phase_id

    # Run rules (pass item_type so features prefer keyword over board_column)
    from ..routers.phases import resolve_phase_for_feature
    resolved = resolve_phase_for_feature(
        title=feature.title,
        source_status=feature.source_status,
        iteration_path=None,
        rules=rules,
        item_type=getattr(feature, "type", None),
    )

    if persist and resolved:
        feature.phase_id = resolved

    return resolved


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

    # Load phase context (auto-seeds defaults if needed)
    phase_map, rules = await _load_phase_context(db, org_id, projectId)

    # 1. Fetch features/epics
    feature_result = await db.execute(
        select(WorkItem)
        .where(*wi_conds, WorkItem.type.in_(["feature", "epic"]))
        .order_by(WorkItem.priority.asc(), WorkItem.title.asc())
    )
    features = feature_result.scalars().all()

    # ── Flat-story fallback: if no features/epics, treat standalone stories
    #    as top-level items so projects without epics still show data ──
    if not features:
        story_result = await db.execute(
            select(WorkItem)
            .where(*wi_conds, WorkItem.type.in_(["story", "task", "bug", "issue"]))
            .order_by(WorkItem.priority.asc(), WorkItem.title.asc())
        )
        standalone_stories = story_result.scalars().all()

        if not standalone_stories:
            return {
                "totalFeatures": 0,
                "totalStories": 0,
                "overallCompletePct": 0,
                "readyForTestCount": 0,
                "features": [],
            }

        # Each standalone story becomes its own "module" card
        total_done = 0
        total_ready_for_test = 0
        feature_cards = []

        for s in standalone_stories:
            is_done = s.status in ("DONE", "CLOSED", "RESOLVED")
            is_rft = s.status in ("IN_REVIEW", "READY_FOR_TEST")
            is_ip = s.status in ("IN_PROGRESS", "ACTIVE")
            pct = 100 if is_done else (50 if is_ip or is_rft else 0)

            if is_done:
                total_done += 1
            if is_rft:
                total_ready_for_test += 1

            phase_id = _resolve_feature_phase(s, phase_map, rules, persist=True)
            phase_info = phase_map.get(phase_id) if phase_id else None

            feature_cards.append({
                "id": s.id,
                "externalId": s.external_id,
                "title": s.title or "Untitled",
                "description": (s.description or "")[:120],
                "phaseId": phase_id,
                "phaseInfo": phase_info,
                "completePct": pct,
                "totalStories": 1,
                "breakdown": {
                    "done": 1 if is_done else 0,
                    "inProgress": 1 if is_ip else 0,
                    "readyForTest": 1 if is_rft else 0,
                    "remaining": 0 if (is_done or is_ip or is_rft) else 1,
                },
                "plannedStart": s.planned_start.isoformat() if s.planned_start else None,
                "plannedEnd": s.planned_end.isoformat() if s.planned_end else None,
                "sourceStatus": s.source_status,
                "sourceTool": s.source_tool,
            })

        overall_pct = int((total_done / len(standalone_stories)) * 100)

        # Persist any newly-resolved phase_ids
        await db.commit()

        return {
            "totalFeatures": len(standalone_stories),
            "totalStories": len(standalone_stories),
            "overallCompletePct": overall_pct,
            "readyForTestCount": total_ready_for_test,
            "features": feature_cards,
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

        phase_id = _resolve_feature_phase(f, phase_map, rules, persist=True)
        phase_info = phase_map.get(phase_id) if phase_id else None

        feature_cards.append({
            "id": f.id,
            "externalId": f.external_id,
            "title": f.title,
            "description": (f.description or "")[:120],
            "phaseId": phase_id,
            "phaseInfo": phase_info,
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

    # Persist any newly-resolved phase_ids so future requests are stable
    await db.commit()

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

    # Load phase context (auto-seeds defaults if needed)
    phase_map, rules = await _load_phase_context(db, org_id, projectId)

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
        return {
            "features": [],
            "unassigned": [],
            "phases": list(phase_map.values()),
            "totalPhases": len(phase_map),
            "complete": 0,
            "inProgress": 0,
        }

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

    # 4. Build per-feature rows grouped by phase
    assigned_rows = []
    unassigned_rows = []
    complete_count = 0
    in_progress_count = 0

    for f in features:
        sc = feature_status.get(f.id, {})
        done = sc.get("DONE", 0)
        total = sum(sc.values())
        pct = int((done / total) * 100) if total > 0 else 0

        phase_id = _resolve_feature_phase(f, phase_map, rules, persist=True)
        phase_info = phase_map.get(phase_id) if phase_id else None

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

        row = {
            "id": f.id,
            "externalId": f.external_id,
            "title": f.title,
            "phaseId": phase_id,
            "phaseInfo": phase_info,
            "status": gantt_status,
            "completePct": pct,
            "totalStories": total,
            "doneStories": done,
            "plannedStart": f.planned_start.isoformat() if f.planned_start else None,
            "plannedEnd": f.planned_end.isoformat() if f.planned_end else None,
            "assignees": feature_assignees.get(f.id, []),
        }

        if phase_id:
            assigned_rows.append(row)
        else:
            unassigned_rows.append(row)

    # Estimate duration from date range
    all_starts = [f.planned_start for f in features if f.planned_start]
    all_ends = [f.planned_end for f in features if f.planned_end]
    est_weeks = None
    if all_starts and all_ends:
        span = max(all_ends) - min(all_starts)
        est_weeks = max(1, round(span.days / 7))

    # Persist any newly-resolved phase_ids so future requests are stable
    await db.commit()

    return {
        "features": assigned_rows,
        "unassigned": unassigned_rows,
        "phases": list(phase_map.values()),
        "totalPhases": len(phase_map),
        "complete": complete_count,
        "inProgress": in_progress_count,
        "estDurationWeeks": est_weeks,
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/plan-summary — Latest sprint plan summary for hero banner
# ---------------------------------------------------------------------------

@router.get("/dashboard/plan-summary")
async def get_plan_summary(
    projectId: str | None = Q(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Latest sprint plan summary for the hero banner.

    Returns plan status, estimated end date, confidence, success probability
    so the hero banner can show AI-optimized data when a plan exists.
    """
    org_id = current_user.get("organization_id", "demo-org")

    if not projectId:
        return {"hasPlan": False}

    # Prefer the latest APPROVED / SYNCED / SYNCED_PARTIAL plan.
    # Fall back to the most-recent plan of any status so the banner
    # can still show "pending review" / "generating" badges.
    _active_statuses = ("APPROVED", "SYNCED", "SYNCED_PARTIAL")
    result = await db.execute(
        select(SprintPlan)
        .where(
            SprintPlan.organization_id == org_id,
            SprintPlan.project_id == projectId,
            SprintPlan.status.in_(_active_statuses),
        )
        .order_by(SprintPlan.created_at.desc())
        .limit(1)
    )
    plan = result.scalar_one_or_none()

    # Fallback: latest plan regardless of status
    if not plan:
        fallback = await db.execute(
            select(SprintPlan)
            .where(
                SprintPlan.organization_id == org_id,
                SprintPlan.project_id == projectId,
            )
            .order_by(SprintPlan.created_at.desc())
            .limit(1)
        )
        plan = fallback.scalar_one_or_none()

    if not plan:
        return {"hasPlan": False}

    return {
        "hasPlan": True,
        "planId": plan.id,
        "status": plan.status,
        "estimatedEndDate": plan.estimated_end_date.isoformat() if plan.estimated_end_date else None,
        "estimatedWeeksTotal": plan.estimated_weeks_total,
        "estimatedSprints": plan.estimated_sprints,
        "confidenceScore": round(plan.confidence_score, 1) if plan.confidence_score else None,
        "successProbability": plan.success_probability,
        "totalStoryPoints": plan.total_story_points,
        "riskSummary": plan.risk_summary,
        "projectCompletionSummary": plan.project_completion_summary,
        "approvedAt": plan.approved_at.isoformat() if plan.approved_at else None,
        "createdAt": plan.created_at.isoformat() if plan.created_at else None,
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/project-plan/optimized — Sprint-plan-based Gantt data
# ---------------------------------------------------------------------------

@router.get("/dashboard/project-plan/optimized")
async def get_project_plan_optimized(
    projectId: str | None = Q(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Optimized project plan — features grouped by sprint number from the latest
    APPROVED sprint plan. Used by the Gantt "Optimized Plan" view toggle.

    Returns same shape as /project-plan but with sprints as "phases".
    """
    org_id = current_user.get("organization_id", "demo-org")

    if not projectId:
        return {"hasPlan": False}

    # Find latest APPROVED / SYNCED / SYNCED_PARTIAL plan
    _opt_statuses = ("APPROVED", "SYNCED", "SYNCED_PARTIAL")
    result = await db.execute(
        select(SprintPlan)
        .where(
            SprintPlan.organization_id == org_id,
            SprintPlan.project_id == projectId,
            SprintPlan.status.in_(_opt_statuses),
        )
        .order_by(SprintPlan.created_at.desc())
        .limit(1)
    )
    plan = result.scalar_one_or_none()

    if not plan:
        return {"hasPlan": False}

    # Load the iteration to get sprint dates
    from ..models.iteration import Iteration as IterModel
    iter_result = await db.execute(
        select(IterModel).where(IterModel.id == plan.iteration_id)
    )
    iteration = iter_result.scalar_one_or_none()

    # Derive sprint duration from the plan's own estimates, NOT the iteration
    # window (which is just the current active cycle, often 2 weeks).
    # Plan says: estimated_sprints=8, estimated_weeks_total=16 → 2 wks/sprint
    sprint_duration_days = 14  # default 2 weeks
    if plan.estimated_weeks_total and plan.estimated_sprints:
        sprint_duration_days = max(
            7, (plan.estimated_weeks_total * 7) // plan.estimated_sprints
        )

    # Sprint start = iteration start (the plan's anchor date)
    sprint_start = None
    if iteration and iteration.start_date:
        sprint_start = iteration.start_date

    # Load plan assignments with work items and team members
    assign_result = await db.execute(
        select(PlanAssignment)
        .where(PlanAssignment.sprint_plan_id == plan.id)
        .options(
            selectinload(PlanAssignment.work_item),
            selectinload(PlanAssignment.team_member),
        )
    )
    assignments = assign_result.scalars().all()

    if not assignments:
        return {
            "hasPlan": True,
            "planId": plan.id,
            "planStatus": plan.status,
            "features": [],
            "unassigned": [],
            "phases": [],
            "totalPhases": 0,
            "complete": 0,
            "inProgress": 0,
            "estDurationWeeks": plan.estimated_weeks_total,
        }

    # Group assignments by work item's parent feature (epic_id)
    # and determine which sprint each feature spans
    feature_sprint_map: dict[str, set[int]] = {}  # feature_id -> set of sprint numbers
    feature_assignee_map: dict[str, set[str]] = {}  # feature_id -> set of assignee names
    story_ids = set()

    for a in assignments:
        wi = a.work_item
        if not wi:
            continue
        story_ids.add(wi.id)
        parent_id = wi.epic_id or wi.id  # if no parent, treat as self
        sprint_num = a.sprint_number or 1

        feature_sprint_map.setdefault(parent_id, set()).add(sprint_num)
        if a.team_member:
            feature_assignee_map.setdefault(parent_id, set()).add(
                a.team_member.display_name
            )

    # Determine unique sprint numbers and build sprint "phases"
    all_sprint_nums = sorted(set(sn for snset in feature_sprint_map.values() for sn in snset))

    # Sprint color palette
    sprint_colors = ["#3b82f6", "#8b5cf6", "#06b6d4", "#f59e0b", "#f97316", "#22c55e", "#ec4899", "#6366f1"]

    sprint_phases = []
    for i, sn in enumerate(all_sprint_nums):
        # Calculate sprint date range
        s_start = None
        s_end = None
        if sprint_start:
            s_start = sprint_start + timedelta(days=(sn - 1) * sprint_duration_days)
            s_end = s_start + timedelta(days=sprint_duration_days)

        date_label = ""
        if s_start and s_end:
            s_fmt = s_start.strftime("%b %d")
            e_fmt = s_end.strftime("%b %d")
            date_label = f" ({s_fmt}–{e_fmt})"

        sprint_phases.append({
            "id": f"sprint-{sn}",
            "name": f"Sprint {sn}{date_label}",
            "slug": f"sprint-{sn}",
            "color": sprint_colors[i % len(sprint_colors)],
            "sortOrder": sn,
            "isDefault": False,
            "_startDate": s_start,
            "_endDate": s_end,
            "_sprintNumber": sn,
        })

    # Build date lookup for sprints
    sprint_date_map = {
        sp["_sprintNumber"]: (sp["_startDate"], sp["_endDate"])
        for sp in sprint_phases
    }

    # Now load the actual features (epics) to build Gantt rows
    wi_conds = _wi_filters(org_id, projectId)
    feature_result = await db.execute(
        select(WorkItem)
        .where(*wi_conds, WorkItem.type.in_(["feature", "epic"]))
        .order_by(WorkItem.planned_start.asc().nullslast(), WorkItem.title.asc())
    )
    features = feature_result.scalars().all()
    feature_ids = [f.id for f in features]

    # Aggregate child work item statuses (same as project-plan endpoint)
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

    # Build Gantt rows grouped by sprint
    assigned_rows = []
    unassigned_rows = []
    complete_count = 0
    in_progress_count = 0

    for f in features:
        sc = feature_status.get(f.id, {})
        done = sc.get("DONE", 0)
        total = sum(sc.values())
        pct = int((done / total) * 100) if total > 0 else 0

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

        # Determine which sprint this feature belongs to (primary = earliest sprint)
        sprints_for_feature = feature_sprint_map.get(f.id, set())
        assignees = list(feature_assignee_map.get(f.id, set()))[:3]

        if sprints_for_feature:
            primary_sprint = min(sprints_for_feature)

            # Completed features are already done — show them in the earliest
            # sprint window (Sprint 1) so the timeline reflects reality: done
            # work appears at the start, remaining work is planned forward.
            if gantt_status == "complete" and all_sprint_nums:
                primary_sprint = all_sprint_nums[0]

            phase_id = f"sprint-{primary_sprint}"

            # Use the primary sprint's date range for the Gantt bar.
            # This keeps each feature as a clean 2-week bar in its assigned
            # sprint slot — matching what the Sprint Planning table shows.
            opt_start, opt_end = sprint_date_map.get(primary_sprint, (None, None))

            row_start = (
                opt_start.isoformat() if opt_start
                else (f.planned_start.isoformat() if f.planned_start else None)
            )
            row_end = (
                opt_end.isoformat() if opt_end
                else (f.planned_end.isoformat() if f.planned_end else None)
            )

            row = {
                "id": f.id,
                "externalId": f.external_id,
                "title": f.title,
                "phaseId": phase_id,
                "phaseInfo": next(
                    (sp for sp in sprint_phases if sp["_sprintNumber"] == primary_sprint),
                    None,
                ),
                "status": gantt_status,
                "completePct": pct,
                "totalStories": total,
                "doneStories": done,
                "plannedStart": row_start,
                "plannedEnd": row_end,
                "assignees": assignees,
            }
            assigned_rows.append(row)
        else:
            row = {
                "id": f.id,
                "externalId": f.external_id,
                "title": f.title,
                "phaseId": None,
                "phaseInfo": None,
                "status": gantt_status,
                "completePct": pct,
                "totalStories": total,
                "doneStories": done,
                "plannedStart": f.planned_start.isoformat() if f.planned_start else None,
                "plannedEnd": f.planned_end.isoformat() if f.planned_end else None,
                "assignees": assignees,
            }
            unassigned_rows.append(row)

    # Clean up internal fields from sprint phases before returning
    clean_phases = [
        {k: v for k, v in sp.items() if not k.startswith("_")}
        for sp in sprint_phases
    ]

    return {
        "hasPlan": True,
        "planId": plan.id,
        "planStatus": plan.status,
        "features": assigned_rows,
        "unassigned": unassigned_rows,
        "phases": clean_phases,
        "totalPhases": len(clean_phases),
        "complete": complete_count,
        "inProgress": in_progress_count,
        "estDurationWeeks": plan.estimated_weeks_total,
    }

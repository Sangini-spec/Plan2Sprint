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
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query as Q
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, case
from sqlalchemy.orm import selectinload

from ..auth.supabase import get_current_user, require_write_role
from ..database import get_db
from ..models.work_item import WorkItem
from ..models.iteration import Iteration
from ..models.team_member import TeamMember
from ..models.analytics import HealthSignal, VelocityProfile
from ..models.repository import PullRequest, Commit
from ..models.imported_project import ImportedProject, StakeholderProjectAssignment
from ..models.user import User
from ..models.sprint_plan import SprintPlan, PlanAssignment

router = APIRouter()


# ---------------------------------------------------------------------------
# Hotfix 36 — cross-org project access for stakeholders
# ---------------------------------------------------------------------------
# Stakeholders sometimes have a User account in a different org from the
# projects they were assigned to (e.g. they signed up with their personal
# email which spawned a new org, but a PO from another org explicitly
# granted them access to a project). Without special handling, every
# dashboard query scopes by ``JWT.organization_id`` and returns empty
# data when the project belongs to another org.
#
# This helper resolves the correct org_id to use for downstream queries:
#   * No projectId given             → user's own org (default)
#   * Project belongs to user's org  → user's own org (no change)
#   * Project belongs to another org → if a stakeholder assignment exists
#                                       matching the user's email, return
#                                       the project's org. Else 403.
# Callers should treat the returned org_id as the authoritative scope for
# all downstream WHERE clauses (work_items, iterations, sprint_plans, …).

async def _resolve_org_for_project(
    db: AsyncSession,
    current_user: dict,
    project_id: str | None,
) -> str:
    """Pick the org_id to use for queries on this project.

    Falls back to the user's JWT org for non-cross-org access. For
    stakeholders viewing projects assigned by a PO in another org,
    returns the project's actual org so dashboard queries find data.
    Raises 403 if the user has no path to view this project.
    """
    user_org = current_user.get("organization_id", "demo-org")
    if not project_id:
        return user_org

    proj_q = await db.execute(
        select(ImportedProject).where(ImportedProject.id == project_id)
    )
    project = proj_q.scalar_one_or_none()
    if not project:
        # Project doesn't exist at all — let the downstream query
        # return empty rather than 404 here (back-compat with the
        # historical behaviour where unknown projectId silently
        # returned empty).
        return user_org

    if project.organization_id == user_org:
        return user_org  # Normal same-org access

    # Cross-org access — only allow if there's an explicit grant.
    user_email = (current_user.get("email") or "").lower()
    if not user_email:
        raise HTTPException(status_code=403, detail="Not authorised to view this project")

    # Collect every user_id that could match this email (User and
    # TeamMember rows in any org — same logic as my-projects).
    user_ids: list[str] = []
    u_q = await db.execute(select(User).where(User.email.ilike(user_email)))
    user_ids.extend(u.id for u in u_q.scalars().all())
    tm_q = await db.execute(select(TeamMember).where(TeamMember.email.ilike(user_email)))
    user_ids.extend(tm.id for tm in tm_q.scalars().all())

    # Hotfix 56 (HIGH-9) — strengthen the cross-org check.
    #
    # Previously: "if any StakeholderProjectAssignment matches this email
    # for this project, grant access". That was too loose: any caller
    # could be granted into any project their email had ever been
    # assigned to, regardless of role and regardless of WHO created the
    # assignment. Combined with CRIT-2 (since-fixed) it was an
    # unbounded cross-org write surface.
    #
    # New rule: cross-org access only fires when ALL of these hold:
    #   1. caller's role is 'stakeholder' (paid read-only role),
    #   2. an assignment exists for the caller's email,
    #   3. the assignment's ``assigned_by`` resolves to a User whose
    #      role is product_owner / admin / owner in the TARGET project's
    #      org. This prevents a stakeholder from spoofing assignments
    #      they (or another stakeholder) created.
    role = (current_user.get("role") or "").lower()
    if role != "stakeholder":
        raise HTTPException(
            status_code=403,
            detail="Not authorised to view this project",
        )

    if user_ids:
        asg_q = await db.execute(
            select(StakeholderProjectAssignment).where(
                StakeholderProjectAssignment.imported_project_id == project_id,
                StakeholderProjectAssignment.user_id.in_(user_ids),
            )
        )
        assignment = asg_q.scalar_one_or_none()
        if assignment:
            # Verify the assigner is a PO/admin/owner of the target org.
            assigner_q = await db.execute(
                select(User).where(User.id == assignment.assigned_by)
            )
            assigner = assigner_q.scalar_one_or_none()
            if (
                assigner
                and assigner.organization_id == project.organization_id
                and (assigner.role or "").lower()
                in ("product_owner", "admin", "owner")
            ):
                return project.organization_id

    raise HTTPException(status_code=403, detail="Not authorised to view this project")


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
    # Hotfix 36 — pick project's org for cross-org stakeholders
    org_id = await _resolve_org_for_project(db, current_user, projectId)

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
    org_id = await _resolve_org_for_project(db, current_user, projectId)
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
    org_id = await _resolve_org_for_project(db, current_user, projectId)

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
    org_id = await _resolve_org_for_project(db, current_user, projectId)
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
    require_write_role(current_user)  # Hotfix 55 (HIGH-6) — block stakeholders
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
# PATCH /api/work-items/{id}/planned-dates — set Gantt planned start/end
# ---------------------------------------------------------------------------

@router.patch("/work-items/{item_id}/planned-dates")
async def update_work_item_planned_dates(
    item_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sprint D — persist Gantt edits.

    The Project Plan Gantt's pencil-edit modal posts to this endpoint when
    a PO sets or changes a feature's planned start week and duration. Local
    DB only — no write-back to ADO/Jira (the planned dates are a
    Plan2Sprint planning overlay, not a system-of-record value).

    Body shape (both forms accepted):
        { "plannedStart": "2026-05-06T00:00:00Z", "plannedEnd": "..." }
        { "plannedStart": null, "plannedEnd": null }   # clear
    """
    require_write_role(current_user)  # Hotfix 55 (HIGH-6)
    from datetime import datetime, timezone
    from fastapi import HTTPException

    org_id = current_user.get("organization_id", "demo-org")

    def _parse(raw):
        if raw is None or raw == "":
            return None
        if isinstance(raw, datetime):
            dt = raw
        else:
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except (ValueError, TypeError) as e:
                raise HTTPException(400, f"Invalid date '{raw}': {e}")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    # Either both provided or both null — partial updates not allowed,
    # because a half-set planned range can't render on the Gantt.
    if "plannedStart" not in body or "plannedEnd" not in body:
        raise HTTPException(400, "Both plannedStart and plannedEnd are required (use null to clear).")

    new_start = _parse(body["plannedStart"])
    new_end = _parse(body["plannedEnd"])

    if (new_start is None) != (new_end is None):
        raise HTTPException(400, "plannedStart and plannedEnd must both be set or both be null.")

    if new_start and new_end and new_end <= new_start:
        raise HTTPException(400, "plannedEnd must be after plannedStart.")

    result = await db.execute(
        select(WorkItem).where(
            WorkItem.id == item_id,
            WorkItem.organization_id == org_id,
        )
    )
    wi = result.scalar_one_or_none()
    if not wi:
        raise HTTPException(404, "Work item not found")

    wi.planned_start = new_start
    wi.planned_end = new_end
    await db.commit()

    return {
        "ok": True,
        "workItemId": item_id,
        "plannedStart": new_start.isoformat() if new_start else None,
        "plannedEnd": new_end.isoformat() if new_end else None,
    }


# ---------------------------------------------------------------------------
# PATCH /api/work-items/{id}/visibility — Sprint E: hide/show on Gantt
# ---------------------------------------------------------------------------

@router.patch("/work-items/{item_id}/visibility")
async def update_work_item_visibility(
    item_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sprint E — toggle ``WorkItem.hidden_from_gantt``.

    The PO uses this to declutter the Project Plan Gantt without
    deleting the underlying work item (so sprint history, retros,
    velocity, etc. stay intact). Only the ``/dashboard/project-plan``
    and ``/dashboard/project-plan/optimized`` endpoints honour the flag.

    Body shape: ``{"hidden": true}`` or ``{"hidden": false}``.
    """
    require_write_role(current_user)  # Hotfix 55 (HIGH-6)
    from fastapi import HTTPException

    org_id = current_user.get("organization_id", "demo-org")

    if "hidden" not in body:
        raise HTTPException(400, "Missing 'hidden' boolean in body.")
    new_hidden = bool(body["hidden"])

    result = await db.execute(
        select(WorkItem).where(
            WorkItem.id == item_id,
            WorkItem.organization_id == org_id,
        )
    )
    wi = result.scalar_one_or_none()
    if not wi:
        raise HTTPException(404, "Work item not found")

    wi.hidden_from_gantt = new_hidden
    await db.commit()

    return {
        "ok": True,
        "workItemId": item_id,
        "hidden": new_hidden,
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
    """Synchronous resolve — manual > rules > AI cache > status fallback.

    NOTE: this is the synchronous resolver used by hot-path call sites
    that don't have a usable async db handle. The AI-classifier tier
    only **reads** the cache here — never calls Grok inline. Async
    classification (cache miss → LLM call → cache write) lives in
    ``_resolve_feature_phase_async`` below, which the dashboard endpoint
    calls.
    """
    # Manual override (already persisted)
    if feature.phase_id and feature.phase_id in phase_map:
        return feature.phase_id

    # Tier 2 — rules engine
    from ..routers.phases import resolve_phase_for_feature
    resolved = resolve_phase_for_feature(
        title=feature.title,
        source_status=feature.source_status,
        iteration_path=None,
        rules=rules,
        item_type=getattr(feature, "type", None),
    )
    # Tier 2 wins persistence — when rules match, write phase_id so the
    # next request short-circuits at tier 1 with no rule-engine cost.
    if persist and resolved:
        feature.phase_id = resolved

    # Tier 3 (cache only — no LLM call from sync path) — use the cached
    # AI classification if it points at a still-valid phase. Wins over
    # the status fallback. NOT persisted into ``phase_id`` because that
    # would make the feature look manually-placed and the AI cache
    # would never get re-queried even if the description changes; we
    # let the resolver re-derive on each read instead.
    if not resolved:
        ai_phase_id = getattr(feature, "ai_classified_phase_id", None)
        if ai_phase_id and ai_phase_id in phase_map:
            resolved = ai_phase_id

    # Tier 4 — status-driven fallback (defensive default). Hotfix 22 —
    # explicitly DO NOT persist this into ``phase_id``. Doing so would
    # mask features as "already placed" so the background AI classifier
    # would skip them forever, and the fallback would be permanent
    # rather than transitional. Now tier 4 only sets the return value
    # for THIS render; the next render will still see ``phase_id IS NULL``
    # and the AI tier gets a chance to win.
    if not resolved and phase_map:
        from ..services._planning_status import TERMINAL_STATUSES

        status_norm = (feature.status or "").upper()
        src_norm = "".join(
            ch for ch in (feature.source_status or "").upper() if ch.isalnum()
        )
        is_terminal = (
            status_norm in TERMINAL_STATUSES or src_norm in TERMINAL_STATUSES
        )

        phases_sorted = sorted(
            phase_map.values(),
            key=lambda p: p.get("sortOrder", 999),
        )
        first_phase = phases_sorted[0] if phases_sorted else None
        last_work_phase = next(
            (p for p in reversed(phases_sorted) if p.get("slug") != "ready"),
            None,
        )

        if is_terminal and last_work_phase:
            resolved = last_work_phase["id"]
        elif first_phase:
            resolved = first_phase["id"]
        # NOTE: deliberately not persisting the tier-4 result.

    return resolved


async def _resolve_feature_phase_async(
    feature,
    phase_map: dict[str, dict],
    rules: list[dict],
    db,
    *,
    persist: bool = False,
) -> str | None:
    """Async resolver — same chain as ``_resolve_feature_phase`` but with
    an active LLM call on tier-3 cache miss.

    The dashboard project-plan endpoint calls this. Used to fire the
    AI phase classifier (Hotfix 19) inline when rules don't match AND
    the AI cache is empty / stale. First-load latency cost is bounded:
    one classifier call per genuinely-unmatched feature, then cached on
    the WorkItem so subsequent loads are free.

    Tier breakdown:
      1. ``feature.phase_id`` (manual PO drag) — return immediately
      2. Rules engine (keyword + board_column)
      3. AI classifier (read cache; on miss/stale, call Grok)
      4. Status fallback (terminal → last work phase, else → first)
    """
    # Tier 1 — manual
    if feature.phase_id and feature.phase_id in phase_map:
        return feature.phase_id

    # Tier 2 — rules
    from ..routers.phases import resolve_phase_for_feature
    resolved = resolve_phase_for_feature(
        title=feature.title,
        source_status=feature.source_status,
        iteration_path=None,
        rules=rules,
        item_type=getattr(feature, "type", None),
    )

    # Tier 3 — AI classifier with cache (read + write)
    if not resolved and phase_map:
        try:
            from ..services.ai_phase_classifier import classify_and_cache
            phases_for_ai = [
                {"id": p["id"], "slug": p["slug"], "name": p["name"]}
                for p in phase_map.values()
            ]
            ai_resolved = await classify_and_cache(
                feature, phases_for_ai, db
            )
            if ai_resolved and ai_resolved in phase_map:
                resolved = ai_resolved
        except Exception:
            # Never let classifier failure block the dashboard; fall
            # through to the status-based safety net.
            import logging as _log
            _log.getLogger(__name__).exception(
                "AI phase classifier crashed; falling back to status rule"
            )

    # Tier 4 — status fallback (safety net)
    if not resolved and phase_map:
        from ..services._planning_status import TERMINAL_STATUSES

        status_norm = (feature.status or "").upper()
        src_norm = "".join(
            ch for ch in (feature.source_status or "").upper() if ch.isalnum()
        )
        is_terminal = (
            status_norm in TERMINAL_STATUSES or src_norm in TERMINAL_STATUSES
        )

        phases_sorted = sorted(
            phase_map.values(),
            key=lambda p: p.get("sortOrder", 999),
        )
        first_phase = phases_sorted[0] if phases_sorted else None
        last_work_phase = next(
            (p for p in reversed(phases_sorted) if p.get("slug") != "ready"),
            None,
        )

        if is_terminal and last_work_phase:
            resolved = last_work_phase["id"]
        elif first_phase:
            resolved = first_phase["id"]

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
    org_id = await _resolve_org_for_project(db, current_user, projectId)
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

    # Composite confidence score — replaces the hero banner's AI-only score.
    # Blends velocity / CI-CD / AI-plan / target-feasibility / sprint reliability
    # into a single 0-100 number that actually reacts to delivery reality.
    # See services/confidence_engine.py for the full formula and fallbacks.
    confidence_block = None
    if projectId:
        try:
            from ..services.confidence_engine import compute_confidence
            cr = await compute_confidence(db, org_id, projectId)
            # Round breakdown values so the tooltip stays readable.
            def _r(v):
                return None if v is None else round(float(v))
            confidence_block = {
                "score": cr.score,
                "breakdown": {
                    "velocity": _r(cr.breakdown.velocity),
                    "cicd": _r(cr.breakdown.cicd),
                    "aiPlan": _r(cr.breakdown.ai_plan),
                    "targetFeasibility": _r(cr.breakdown.target_feasibility),
                    "sprintReliability": _r(cr.breakdown.sprint_reliability),
                },
                "weights": cr.weights,
                "factorsUsed": cr.factors_used,
                "reasonHidden": cr.reason_hidden,
            }
        except Exception as e:  # noqa: BLE001 — never fail the dashboard because of the confidence engine
            import logging
            logging.getLogger(__name__).exception("confidence_engine failed: %s", e)
            confidence_block = None

    return {
        "totalFeatures": len(features),
        "totalStories": total_stories,
        "overallCompletePct": overall_pct,
        "readyForTestCount": total_ready_for_test,
        "features": feature_cards,
        "confidence": confidence_block,
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/project-plan — Gantt data for Project Plan tab
# ---------------------------------------------------------------------------

@router.get("/dashboard/project-plan")
async def get_project_plan(
    background_tasks: BackgroundTasks,
    projectId: str | None = Q(None),
    includeHidden: bool = Q(False),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Project Plan / Gantt timeline — features with planned vs actual progress.

    Returns features grouped by phase, with planned dates, assignees,
    completion %, and status for Gantt rendering.

    Sprint E — when ``includeHidden`` is False (default), features the PO
    has hidden from the Gantt (``WorkItem.hidden_from_gantt = True``) are
    excluded but still counted in ``hiddenCount`` so the UI can show a
    "Show N hidden features" toggle.
    """
    org_id = await _resolve_org_for_project(db, current_user, projectId)
    wi_conds = _wi_filters(org_id, projectId)

    # Load phase context (auto-seeds defaults if needed)
    phase_map, rules = await _load_phase_context(db, org_id, projectId)

    # 1. Fetch features ordered by planned_start
    feature_query = select(WorkItem).where(
        *wi_conds, WorkItem.type.in_(["feature", "epic"])
    )
    if not includeHidden:
        feature_query = feature_query.where(
            WorkItem.hidden_from_gantt.is_(False)
        )
    feature_query = feature_query.order_by(
        WorkItem.planned_start.asc().nullslast(),
        WorkItem.title.asc(),
    )
    feature_result = await db.execute(feature_query)
    features = feature_result.scalars().all()

    # Count hidden features (so UI can show "Show N hidden" toggle even
    # when includeHidden=False). Cheap aggregate query.
    hidden_count_result = await db.execute(
        select(func.count())
        .select_from(WorkItem)
        .where(
            *wi_conds,
            WorkItem.type.in_(["feature", "epic"]),
            WorkItem.hidden_from_gantt.is_(True),
        )
    )
    hidden_count = int(hidden_count_result.scalar() or 0)

    if not features:
        return {
            "features": [],
            "unassigned": [],
            "phases": list(phase_map.values()),
            "totalPhases": len(phase_map),
            "complete": 0,
            "inProgress": 0,
            "hiddenCount": hidden_count,
            "includeHidden": includeHidden,
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

    # Terminal status set used to force-complete features that ADO/Jira
    # has closed at the parent level even if their child-story rollup
    # hasn't fully caught up. See services._planning_status for the
    # canonical denylist.
    from ..services._planning_status import TERMINAL_STATUSES

    for f in features:
        sc = feature_status.get(f.id, {})
        done = sc.get("DONE", 0)
        total = sum(sc.values())
        pct = int((done / total) * 100) if total > 0 else 0

        # Hotfix 20 — switched back to the sync resolver (cache-only
        # AI tier). The dashboard returns immediately with whatever
        # the cache + rules + status-fallback chain yields, and the
        # actual LLM classification happens in a background task
        # scheduled below. Next dashboard load picks up the classified
        # phases from the cache. Trade-off: first-load latency stays
        # under 50ms even on projects with many unmatched features;
        # cost is one render cycle of "approximate" placement before
        # the AI verdict lands.
        phase_id = _resolve_feature_phase(f, phase_map, rules, persist=True)
        phase_info = phase_map.get(phase_id) if phase_id else None

        # Derive Gantt status
        src_lower = (f.source_status or "").lower()
        # If the feature itself is in a terminal status (closed/resolved/
        # done at the parent level in ADO/Jira), force it to "complete"
        # regardless of child-story rollup. Stops "Landing Page closed in
        # ADO 3 weeks ago" from showing as in-progress just because one
        # stale child task wasn't moved across.
        #
        # We check BOTH the unified ``status`` AND the raw ``source_status``
        # because the unified mapping treats some terminal-ish ADO states
        # (notably "Resolved") as IN_REVIEW. So `f.status` alone misses
        # the "Resolved-but-actually-done" case that's common when a team's
        # ADO process template uses Resolved as the final state. The raw
        # string preserves the ADO state verbatim and matches TERMINAL_STATUSES
        # entries like "RESOLVED" / "CLOSED" / "DONE" directly.
        feature_status_norm = (f.status or "").upper()
        source_status_norm = "".join(
            ch for ch in (f.source_status or "").upper() if ch.isalnum()
        )
        feature_status_terminal = (
            feature_status_norm in TERMINAL_STATUSES
            or source_status_norm in TERMINAL_STATUSES
        )

        if feature_status_terminal or pct == 100:
            gantt_status = "complete"
            complete_count += 1
            # Lift visible completion % to 100 so the Gantt bar fills
            # correctly even when child rollup lags.
            if feature_status_terminal:
                pct = 100
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
            # Sprint E — propagate the hide flag so the UI can render an
            # "unhide" affordance when the PO is in show-hidden mode.
            "hidden": bool(f.hidden_from_gantt),
            # Diagnostic — surface the raw external status so the PO can
            # hover a "stuck" row and see what string ADO/Jira returned.
            # Useful when our terminal-status alias list misses a custom
            # column ("Deployed to Prod", "Live", etc.).
            "sourceStatus": f.source_status,
        }

        if phase_id:
            assigned_rows.append(row)
        else:
            unassigned_rows.append(row)

    # ------------------------------------------------------------------
    # Hidden-independent KPI counts. The PO expects "Complete: 15" to stay
    # at 15 even when they hide a couple of done features for screen
    # cleanup — hiding is a visual operation, not a delete. So we run the
    # complete / in-progress aggregates over the FULL feature set
    # (including hidden rows) by re-computing on top of the data we already
    # have plus a topup query for the rows that the visibility filter
    # excluded from `features`.
    # ------------------------------------------------------------------
    if not includeHidden and hidden_count > 0:
        hidden_features_q = await db.execute(
            select(WorkItem).where(
                *wi_conds,
                WorkItem.type.in_(["feature", "epic"]),
                WorkItem.hidden_from_gantt.is_(True),
            )
        )
        hidden_features = hidden_features_q.scalars().all()
        if hidden_features:
            hidden_ids = [h.id for h in hidden_features]
            hidden_child_agg = await db.execute(
                select(
                    WorkItem.epic_id,
                    WorkItem.status,
                    func.count().label("cnt"),
                )
                .where(
                    WorkItem.organization_id == org_id,
                    WorkItem.epic_id.in_(hidden_ids),
                )
                .group_by(WorkItem.epic_id, WorkItem.status)
            )
            hidden_status_map: dict[str, dict[str, int]] = {hid: {} for hid in hidden_ids}
            for r in hidden_child_agg.all():
                hidden_status_map.setdefault(r[0], {})[r[1]] = r[2]
            for hf in hidden_features:
                hsc = hidden_status_map.get(hf.id, {})
                hdone = hsc.get("DONE", 0)
                htotal = sum(hsc.values())
                hpct = int((hdone / htotal) * 100) if htotal > 0 else 0
                h_status_norm = (hf.status or "").upper()
                h_src_norm = "".join(
                    ch for ch in (hf.source_status or "").upper() if ch.isalnum()
                )
                h_terminal = (
                    h_status_norm in TERMINAL_STATUSES
                    or h_src_norm in TERMINAL_STATUSES
                )
                if h_terminal or hpct == 100:
                    complete_count += 1
                elif hpct > 0:
                    in_progress_count += 1

    # Hotfix 20 — schedule background AI phase classification for any
    # features that are still un-cached or whose inputs have changed.
    # Runs AFTER the response is sent so the dashboard render is fast;
    # next reload picks up the AI verdict from the cache. Skipped when
    # there's no project_id (org-wide view has no single phase set).
    if projectId:
        from ..services.ai_phase_classifier import (
            classify_unmatched_features_in_background,
        )
        background_tasks.add_task(
            classify_unmatched_features_in_background, projectId, org_id
        )

    # Estimate duration from date range
    all_starts = [f.planned_start for f in features if f.planned_start]
    all_ends = [f.planned_end for f in features if f.planned_end]
    est_weeks = None
    if all_starts and all_ends:
        span = max(all_ends) - min(all_starts)
        est_weeks = max(1, round(span.days / 7))

    # Persist any newly-resolved phase_ids so future requests are stable
    await db.commit()

    # ------------------------------------------------------------------
    # Timeline revamp (Sprint 6): include the TimelineDTO so the PO hero
    # banner can render phase dates, current phase, target launch, and any
    # target-violation warnings without doing math in the UI. The old
    # ``phases`` / ``estDurationWeeks`` keys are kept untouched for backward
    # compatibility; Sprint 7's frontend migrates to read ``timeline``.
    # ------------------------------------------------------------------
    timeline_block: dict | None = None
    if projectId:
        try:
            from ..services.timeline_engine import compute_timeline
            tl = await compute_timeline(db, org_id, projectId, persist=True)

            # Hotfix 83 — surface the "project is past target launch" state
            # to the UI. Computed from the same source the cron-fired email
            # uses, so the red Target Launch tile and the email can never
            # disagree about whether a project is overdue.
            #
            # Use story-level completion (matches what the hero banner shows
            # as "% Complete"), not feature-level — features often roll
            # 100% only on launch day, so feature-pct would mark every late
            # project "delivered_late" even when half the stories under
            # them are still in flight.
            _story_total = 0
            _story_done = 0
            for _sc in feature_status.values():
                for _st, _cnt in _sc.items():
                    _story_total += _cnt
                    if str(_st).upper() in ("DONE", "CLOSED", "RESOLVED"):
                        _story_done += _cnt
            _story_pct = (_story_done / _story_total * 100) if _story_total > 0 else 0

            from ..services.project_status import compute_overdue_status
            from ..models.imported_project import ImportedProject as _IP
            proj = (await db.execute(
                select(_IP).where(_IP.id == projectId)
            )).scalar_one_or_none()
            overdue = compute_overdue_status(
                target_launch_date=tl.target_launch_date,
                completion_pct=_story_pct,
                is_active=bool(proj.is_active) if proj else False,
            )

            timeline_block = {
                "mode": tl.mode,
                "phases": [
                    {
                        "id": p.id,
                        "slug": p.slug,
                        "name": p.name,
                        "sortOrder": p.sort_order,
                        "color": p.color,
                        "plannedStart": p.planned_start.isoformat() if p.planned_start else None,
                        "plannedEnd": p.planned_end.isoformat() if p.planned_end else None,
                    }
                    for p in tl.phases
                ],
                "targetLaunchDate": tl.target_launch_date.isoformat() if tl.target_launch_date else None,
                "targetLaunchSource": tl.target_launch_source,
                "targetViolated": tl.target_violated,
                "targetViolatedDays": tl.target_violated_days,
                "currentPhaseSlug": tl.current_phase_slug,
                "currentPhaseSource": tl.current_phase_source,
                # Hotfix 16 — earlier phases that still have in-flight
                # work even though the project's frontier has moved past
                # them. UI renders these in the cyan "also active" glow
                # alongside the orange current-phase indicator.
                "alsoActivePhaseSlugs": list(tl.also_active_phase_slugs or []),
                # Hotfix 83 — overdue alert state for the hero banner.
                "lifecycleStatus": overdue.status,        # "on_track" | "overdue" | "delivered_late"
                "daysPastTarget": overdue.days_past,
            }
        except Exception as e:  # noqa: BLE001 - never crash the dashboard if engine misbehaves
            import logging
            logging.getLogger(__name__).exception("Timeline engine failed: %s", e)
            timeline_block = None

    return {
        "features": assigned_rows,
        "unassigned": unassigned_rows,
        "phases": list(phase_map.values()),
        "totalPhases": len(phase_map),
        "complete": complete_count,
        "inProgress": in_progress_count,
        "estDurationWeeks": est_weeks,
        "timeline": timeline_block,
        "hiddenCount": hidden_count,
        "includeHidden": includeHidden,
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
    org_id = await _resolve_org_for_project(db, current_user, projectId)

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
        "isRebalanced": getattr(plan, 'is_rebalanced', False),
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/project-plan/optimized — Sprint-plan-based Gantt data
# ---------------------------------------------------------------------------

@router.get("/dashboard/project-plan/optimized")
async def get_project_plan_optimized(
    projectId: str | None = Q(None),
    includeHidden: bool = Q(False),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Optimized project plan — features grouped by sprint number from the latest
    APPROVED sprint plan. Used by the Gantt "Optimized Plan" view toggle.

    Returns same shape as /project-plan but with sprints as "phases".
    """
    org_id = await _resolve_org_for_project(db, current_user, projectId)

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

    # Now load the actual features (epics) to build Gantt rows. Sprint E
    # — respect the per-row hide flag unless the PO has explicitly
    # toggled "show hidden" in the UI.
    wi_conds = _wi_filters(org_id, projectId)
    feature_query_opt = select(WorkItem).where(
        *wi_conds, WorkItem.type.in_(["feature", "epic"])
    )
    if not includeHidden:
        feature_query_opt = feature_query_opt.where(
            WorkItem.hidden_from_gantt.is_(False)
        )
    feature_query_opt = feature_query_opt.order_by(
        WorkItem.planned_start.asc().nullslast(), WorkItem.title.asc()
    )
    feature_result = await db.execute(feature_query_opt)
    features = feature_result.scalars().all()
    feature_ids = [f.id for f in features]

    # Aggregate hidden count for the optimized view too.
    hidden_count_opt = int(
        (
            await db.execute(
                select(func.count())
                .select_from(WorkItem)
                .where(
                    *wi_conds,
                    WorkItem.type.in_(["feature", "epic"]),
                    WorkItem.hidden_from_gantt.is_(True),
                )
            )
        ).scalar()
        or 0
    )

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
    from ..services._planning_status import TERMINAL_STATUSES

    assigned_rows = []
    completed_rows: list[dict] = []     # Hotfix 34 — DONE features go here
    out_of_plan_rows: list[dict] = []   # Hotfix 34 — open features missing from current plan
    new_since_plan_titles: list[str] = []  # Hotfix 34 — for the stale-plan banner
    complete_count = 0
    in_progress_count = 0

    plan_created_at = plan.created_at  # for stale-plan detection

    for f in features:
        sc = feature_status.get(f.id, {})
        done = sc.get("DONE", 0)
        total = sum(sc.values())
        pct = int((done / total) * 100) if total > 0 else 0

        # Derive Gantt status — mirrors /project-plan logic (Sprint A + the
        # source_status fallback). Resolved features in some ADO process
        # templates are terminal even though their unified status is
        # IN_REVIEW; check both columns so the bar turns green.
        src_lower = (f.source_status or "").lower()
        feature_status_norm = (f.status or "").upper()
        source_status_norm = "".join(
            ch for ch in (f.source_status or "").upper() if ch.isalnum()
        )
        feature_status_terminal = (
            feature_status_norm in TERMINAL_STATUSES
            or source_status_norm in TERMINAL_STATUSES
        )
        if feature_status_terminal or pct == 100:
            gantt_status = "complete"
            complete_count += 1
            if feature_status_terminal:
                pct = 100
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

            # Keep features in their assigned sprint regardless of completion status.
            # This preserves the AI plan's distribution across sprints.
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
                "hidden": bool(f.hidden_from_gantt),
                "sourceStatus": f.source_status,
            }
            assigned_rows.append(row)
        else:
            # Feature has no PlanAssignment — it's either delivered already
            # (Completed) or genuinely out of the current plan.
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
                "hidden": bool(f.hidden_from_gantt),
                "sourceStatus": f.source_status,
            }

            # Hotfix 34 — categorize:
            # If the feature is terminal (closed/resolved/100% done) → Completed
            # Otherwise → Out of Plan (genuinely missing from current plan)
            if gantt_status == "complete":
                completed_rows.append(row)
            else:
                out_of_plan_rows.append(row)
                # Hotfix 34 — flag as "new since last plan" if the feature
                # was created AFTER the plan was generated. This drives the
                # banner message ("3 new features added since last plan").
                if (
                    plan_created_at is not None
                    and getattr(f, "created_at", None) is not None
                    and f.created_at > plan_created_at
                ):
                    new_since_plan_titles.append(f.title)

    # Clean up internal fields from sprint phases before returning
    clean_phases = [
        {k: v for k, v in sp.items() if not k.startswith("_")}
        for sp in sprint_phases
    ]

    return {
        "hasPlan": True,
        "planId": plan.id,
        "planStatus": plan.status,
        "planCreatedAt": plan.created_at.isoformat() if plan.created_at else None,
        "isRebalanced": getattr(plan, 'is_rebalanced', False),
        "features": assigned_rows,
        # Hotfix 34 — split former "unassigned" into two semantic buckets:
        # ``completed`` = features already delivered (status terminal /
        # all stories DONE). Frontend should render these in green with
        # a checkmark, NOT under "unassigned".
        # ``outOfPlan`` = features with open stories that aren't in the
        # current plan. Usually means the plan is stale (features added
        # since last regen) — frontend should show a "Regenerate to
        # include them" banner above this section.
        "completed": completed_rows,
        "outOfPlan": out_of_plan_rows,
        # Old field kept for any consumers that still read it; will phase
        # out once the dashboard is fully migrated.
        "unassigned": completed_rows + out_of_plan_rows,
        "newSincePlan": {
            "count": len(new_since_plan_titles),
            "titles": new_since_plan_titles[:10],  # cap for the banner tooltip
        },
        "phases": clean_phases,
        "totalPhases": len(clean_phases),
        "complete": complete_count,
        "inProgress": in_progress_count,
        "estDurationWeeks": plan.estimated_weeks_total,
        "hiddenCount": hidden_count_opt,
        "includeHidden": includeHidden,
    }


# ---------------------------------------------------------------------------
# Admin repair endpoint — gated on DEBUG env. Removed in production via config.
# ---------------------------------------------------------------------------
@router.post("/_admin/repair-iteration-links")
async def _debug_repair_iteration_links(
    projectId: str = Q(...),
    db: AsyncSession = Depends(get_db),
):
    """One-shot repair: re-point orphaned work_items to current project's iterations
    by matching iteration external_id.

    Scenario: project was re-imported → new iteration rows created with new internal
    IDs but same external_ids. work_items still point to old iteration_ids that
    belong to a different project (or a deleted project).
    """
    from sqlalchemy import text as _text
    # Orphan iteration_ids: any iteration_id on work_items in this project that
    # doesn't exist in this project's iterations table.
    r = await db.execute(_text("""
        SELECT DISTINCT wi.iteration_id, old_i.external_id as old_ext, old_i.name as old_name
        FROM work_items wi
        LEFT JOIN iterations old_i ON old_i.id = wi.iteration_id
        WHERE wi.imported_project_id = :p
          AND wi.iteration_id IS NOT NULL
          AND (old_i.imported_project_id IS NULL OR old_i.imported_project_id != :p)
    """), {"p": projectId})
    orphans = [dict(row._mapping) for row in r.all()]

    # Load current iterations for this project (for matching)
    r2 = await db.execute(_text(
        "SELECT id, name, external_id FROM iterations WHERE imported_project_id = :p"
    ), {"p": projectId})
    current_iters = [dict(row._mapping) for row in r2.all()]

    def find_match(old_ext, old_name, old_id):
        """Try to find a current iteration matching by ext, then by name, then by position."""
        if old_ext:
            for it in current_iters:
                if it["external_id"] == old_ext:
                    return it["id"]
        if old_name:
            for it in current_iters:
                if it["name"] == old_name:
                    return it["id"]
        # Last resort: peek at another Plan2Sprint-ish project holding that iteration
        return None

    repairs = []
    unrepaired = []
    for orphan in orphans:
        old_iter_id = orphan["iteration_id"]
        old_ext = orphan["old_ext"]
        old_name = orphan["old_name"]

        # If old iteration was deleted (old_ext and old_name both NULL), try to
        # infer which iteration it was via another surviving import.
        if not old_name:
            r3 = await db.execute(_text(
                "SELECT name, external_id FROM iterations WHERE id = :id"
            ), {"id": old_iter_id})
            row = r3.first()
            if row:
                old_name = row[0]
                old_ext = row[1]

        new_id = find_match(old_ext, old_name, old_iter_id)
        if not new_id:
            unrepaired.append({"old_iteration_id": old_iter_id, "old_name": old_name, "old_ext": old_ext})
            continue

        upd = await db.execute(_text("""
            UPDATE work_items
            SET iteration_id = :new_id
            WHERE imported_project_id = :p AND iteration_id = :old_id
        """), {"new_id": new_id, "old_id": old_iter_id, "p": projectId})
        repairs.append({
            "old_iteration_id": old_iter_id,
            "old_name": old_name,
            "new_iteration_id": new_id,
            "rows_updated": upd.rowcount,
        })

    await db.commit()
    return {
        "orphansFound": len(orphans),
        "repairs": repairs,
        "unrepaired": unrepaired,
        "currentIterations": current_iters,
    }



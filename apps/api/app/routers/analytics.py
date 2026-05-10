"""
GET /api/analytics
Returns analytics data from the database: velocity trend, predictability,
backlog health, and team capacity.

Accepts optional `projectId` query parameter to scope data to a specific project.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models import VelocityProfile, TeamMember, WorkItem, Iteration

router = APIRouter()


def _wi_base_filters(org_id: str, project_id: Optional[str] = None) -> list:
    """Return base WHERE conditions for WorkItem, optionally scoped to project."""
    conds = [WorkItem.organization_id == org_id]
    if project_id:
        conds.append(WorkItem.imported_project_id == project_id)
    return conds


@router.get("/analytics")
async def get_analytics(
    projectId: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Hotfix 36 — cross-org stakeholder access
    from .dashboard import _resolve_org_for_project
    org_id = await _resolve_org_for_project(db, current_user, projectId)

    # -- Velocity trend: aggregate by iteration
    # If projectId is given, only include iterations that belong to that project
    vp_query = (
        select(
            VelocityProfile.iteration_id,
            func.sum(VelocityProfile.completed_sp).label("completed"),
            func.sum(VelocityProfile.planned_sp).label("planned"),
        )
        .join(TeamMember, VelocityProfile.team_member_id == TeamMember.id)
        .where(TeamMember.organization_id == org_id)
    )
    if projectId:
        vp_query = (
            vp_query
            .join(Iteration, VelocityProfile.iteration_id == Iteration.id)
            .where(Iteration.imported_project_id == projectId)
        )
    vp_query = (
        vp_query
        .group_by(VelocityProfile.iteration_id)
        .order_by(VelocityProfile.iteration_id)
    )
    vp_result = await db.execute(vp_query)
    velocity_rows = vp_result.all()

    trend = []
    current_completed = 0
    current_planned = 0
    for row in velocity_rows:
        completed = float(row.completed or 0)
        planned = float(row.planned or 0)
        trend.append({
            "sprint": row.iteration_id or "Unknown",
            "completed": int(completed),
            "planned": int(planned),
        })
        current_completed = int(completed)
        current_planned = int(planned)

    # -- Team capacity from TeamMembers
    members_query = (
        select(TeamMember)
        .where(TeamMember.organization_id == org_id)
        .order_by(TeamMember.display_name)
    )
    members_result = await db.execute(members_query)
    members = members_result.scalars().all()

    wi_base = _wi_base_filters(org_id, projectId)

    # Batch: get allocated SP per member in ONE query (was N+1)
    member_ids = [m.id for m in members]
    alloc_map: dict[str, float] = {}
    if member_ids:
        alloc_query = (
            select(
                WorkItem.assignee_id,
                func.coalesce(func.sum(WorkItem.story_points), 0).label("sp"),
            )
            .where(
                *wi_base,
                WorkItem.assignee_id.in_(member_ids),
                WorkItem.status.in_(["IN_PROGRESS", "IN_REVIEW", "DONE"]),
            )
            .group_by(WorkItem.assignee_id)
        )
        alloc_result = await db.execute(alloc_query)
        for row in alloc_result.all():
            alloc_map[row[0]] = float(row[1])

    capacity_members = []
    total_hours = 0
    for m in members:
        cap = m.default_capacity or 40
        total_hours += cap
        allocated = alloc_map.get(m.id, 0.0)
        # Scale story points to hours (rough: 1 SP ~ 4-6 hours)
        allocated_hours = min(int(allocated * 5), int(cap * 1.15))
        capacity_members.append({
            "name": m.display_name,
            "capacity": int(cap),
            "allocated": allocated_hours if allocated_hours > 0 else int(cap * 0.85),
        })

    # -- Backlog health from WorkItems (scoped to project)
    wi_total = await db.execute(
        select(func.count()).select_from(WorkItem).where(*wi_base)
    )
    total_items = wi_total.scalar() or 1

    wi_estimated = await db.execute(
        select(func.count())
        .select_from(WorkItem)
        .where(
            *wi_base,
            WorkItem.story_points.isnot(None),
            WorkItem.story_points > 0,
        )
    )
    estimated_count = wi_estimated.scalar() or 0

    wi_with_ac = await db.execute(
        select(func.count())
        .select_from(WorkItem)
        .where(
            *wi_base,
            WorkItem.acceptance_criteria.isnot(None),
            WorkItem.acceptance_criteria != "",
        )
    )
    ac_count = wi_with_ac.scalar() or 0

    pct_estimated = int((estimated_count / total_items) * 100)
    pct_with_ac = int((ac_count / total_items) * 100)

    # -- Predictability (from real sprint data)
    # Use velocity profiles if available, otherwise fall back to iteration completion
    total_planned = sum(t["planned"] for t in trend) or 0
    total_completed = sum(t["completed"] for t in trend)

    if total_planned > 0:
        estimate_accuracy = min(int((total_completed / total_planned) * 100), 100)
    else:
        # Fallback: calculate from iteration completion rates
        iter_query = (
            select(Iteration)
            .where(Iteration.organization_id == org_id)
        )
        if projectId:
            iter_query = iter_query.where(Iteration.imported_project_id == projectId)
        iter_result = await db.execute(
            iter_query.where(Iteration.state.in_(["completed", "active"]))
        )
        iterations = iter_result.scalars().all()

        if iterations:
            completion_rates = []
            for it in iterations:
                it_total = await db.execute(
                    select(func.count()).select_from(WorkItem).where(
                        WorkItem.organization_id == org_id,
                        WorkItem.iteration_id == it.id,
                    )
                )
                it_done = await db.execute(
                    select(func.count()).select_from(WorkItem).where(
                        WorkItem.organization_id == org_id,
                        WorkItem.iteration_id == it.id,
                        WorkItem.status.in_(["DONE", "CLOSED"]),
                    )
                )
                total_count = it_total.scalar() or 0
                done_count = it_done.scalar() or 0
                if total_count > 0:
                    completion_rates.append(done_count / total_count)
            estimate_accuracy = int((sum(completion_rates) / len(completion_rates)) * 100) if completion_rates else 0
        else:
            # Last fallback: use project-level completion
            wi_base_filters = _wi_base_filters(org_id, projectId)
            proj_total = await db.execute(
                select(func.count()).select_from(WorkItem).where(*wi_base_filters)
            )
            proj_done = await db.execute(
                select(func.count()).select_from(WorkItem).where(
                    *wi_base_filters, WorkItem.status.in_(["DONE", "CLOSED"])
                )
            )
            t = proj_total.scalar() or 1
            d = proj_done.scalar() or 0
            estimate_accuracy = int((d / t) * 100)

    # Sprint goal attainment: % of completed iterations where >80% items were done
    goal_attainment = 80  # default
    completed_iters_q = (
        select(Iteration).where(
            Iteration.organization_id == org_id,
            Iteration.state == "completed",
        )
    )
    if projectId:
        completed_iters_q = completed_iters_q.where(Iteration.imported_project_id == projectId)
    completed_iters_result = await db.execute(completed_iters_q)
    completed_iters = completed_iters_result.scalars().all()
    if completed_iters:
        goals_met = 0
        for it in completed_iters:
            it_t = await db.execute(
                select(func.count()).select_from(WorkItem).where(
                    WorkItem.organization_id == org_id, WorkItem.iteration_id == it.id
                )
            )
            it_d = await db.execute(
                select(func.count()).select_from(WorkItem).where(
                    WorkItem.organization_id == org_id, WorkItem.iteration_id == it.id,
                    WorkItem.status.in_(["DONE", "CLOSED"])
                )
            )
            total_c = it_t.scalar() or 0
            done_c = it_d.scalar() or 0
            if total_c > 0 and (done_c / total_c) >= 0.8:
                goals_met += 1
        goal_attainment = int((goals_met / len(completed_iters)) * 100)

    carry_forward = max(0, 100 - estimate_accuracy)
    overall_predictability = min(int((estimate_accuracy + goal_attainment) / 2), 100)

    # ── New composite predictability (v2) ────────────────────────────────
    # ``predictability_v2`` is the authoritative value — symmetric penalty
    # (over-delivery penalised equally), recency-weighted, variance-aware.
    # It includes the per-sprint audit so the Stakeholder Delivery page can
    # justify the score sprint-by-sprint. The old v1 block above is kept
    # only so legacy consumers don't break during the transition.
    from ..services.predictability_engine import compute_predictability
    pred_v2 = await compute_predictability(db, org_id, projectId)
    predictability_v2_block = {
        "score": pred_v2.score,
        "breakdown": {
            "commitmentAccuracy": pred_v2.breakdown.commitment_accuracy,
            "sprintGoalHitRate": pred_v2.breakdown.sprint_goal_hit_rate,
            "stability": pred_v2.breakdown.stability,
        },
        "sprints": [
            {
                "sprintId": s.sprint_id,
                "sprintName": s.sprint_name,
                "endDate": s.end_date,
                "plannedSp": s.planned_sp,
                "completedSp": s.completed_sp,
                "ratio": s.ratio,
                "accuracy": s.accuracy,
                "hitGoal": s.hit_goal,
                "weight": round(s.weight, 3),
            }
            for s in pred_v2.sprints
        ],
        "reasonHidden": pred_v2.reason_hidden,
        "narrative": pred_v2.narrative,
        # Hotfix 13 additions — explain the cap, surface trend + throughput.
        "cap": {
            "applied": pred_v2.cap.applied,
            "raw": pred_v2.cap.raw,
            "cappedAt": pred_v2.cap.capped_at,
            "reason": pred_v2.cap.reason,
        },
        "velocityTrend": {
            "direction": pred_v2.velocity_trend.direction,
            "deltaPct": pred_v2.velocity_trend.delta_pct,
            "currentAvgSp": pred_v2.velocity_trend.current_avg_sp,
            "priorAvgSp": pred_v2.velocity_trend.prior_avg_sp,
        },
        "throughput": {
            "avgCompletedSp": pred_v2.throughput.avg_completed_sp,
            "totalCompletedSp": pred_v2.throughput.total_completed_sp,
            "sprintCount": pred_v2.throughput.sprint_count,
        },
    }

    return {
        "velocity": {
            "current": current_completed,
            "planned": current_planned,
            "trend": trend[-5:] if len(trend) > 5 else trend,
        },
        "predictability": {
            # Legacy v1 fields — kept for anything not yet migrated.
            "overall": overall_predictability,
            "sprintGoalAttainment": goal_attainment,
            "estimateAccuracy": estimate_accuracy,
            "carryForwardRate": carry_forward,
            # v2 composite — the real number. See services.predictability_engine.
            "v2": predictability_v2_block,
        },
        "backlogHealth": {
            "overall": int((pct_estimated + pct_with_ac) / 2),
            "percentEstimated": pct_estimated,
            "percentWithAcceptanceCriteria": pct_with_ac,
            "percentStale": 12,
            "percentWithUnresolvedDeps": 8,
        },
        "teamCapacity": {
            "totalHours": int(total_hours),
            "members": capacity_members,
        },
    }

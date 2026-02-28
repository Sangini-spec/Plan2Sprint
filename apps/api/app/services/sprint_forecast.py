"""
Sprint Forecast Service — success probability & spillover risk calculations.

Functions:
  calculate_success_probability()  — overall sprint success score (0-100)
  calculate_spillover_risk()       — per-ticket spillover tagging + total SP at risk
  refresh_forecast()               — orchestrator: recalculates and persists both
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.sprint_plan import SprintPlan, PlanAssignment
from ..models.work_item import WorkItem
from ..models.iteration import Iteration
from ..models.team_member import TeamMember
from ..models.activity import ActivityEvent
from ..models.analytics import VelocityProfile, HealthSignal
from ..models.standup import BlockerFlag, StandupReport
from ..models.repository import PullRequest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Success Probability
# ---------------------------------------------------------------------------

async def calculate_success_probability(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    iteration_id: str | None = None,
) -> dict[str, Any]:
    """
    Calculate sprint success probability (0-100).

    Uses:
      * Current completion % vs expected pacing %
      * Active blocker count weighted by age
      * PR review lag on sprint tickets
      * Historical completion rate (from VelocityProfile)
      * CI failure rate on active PRs
    """
    # --- Resolve active iteration ---
    if iteration_id:
        it_result = await db.execute(
            select(Iteration).where(Iteration.id == iteration_id)
        )
    else:
        iter_filters = [
            Iteration.organization_id == org_id,
            Iteration.state == "active",
        ]
        if project_id:
            iter_filters.append(Iteration.imported_project_id == project_id)
        it_result = await db.execute(
            select(Iteration)
            .where(*iter_filters)
            .order_by(Iteration.start_date.desc())
            .limit(1)
        )
    iteration = it_result.scalar_one_or_none()
    if not iteration:
        return {"successProbability": None, "spilloverRiskSP": 0, "error": "No active iteration"}

    now = datetime.now(timezone.utc)
    sprint_start = iteration.start_date
    sprint_end = iteration.end_date
    if not sprint_start or not sprint_end:
        return {"successProbability": None, "spilloverRiskSP": 0, "error": "Iteration missing dates"}

    # Ensure timezone-aware
    if sprint_start.tzinfo is None:
        sprint_start = sprint_start.replace(tzinfo=timezone.utc)
    if sprint_end.tzinfo is None:
        sprint_end = sprint_end.replace(tzinfo=timezone.utc)

    total_days = max((sprint_end - sprint_start).days, 1)
    elapsed_days = max((now - sprint_start).days, 0)
    elapsed_pct = min(elapsed_days / total_days, 1.0)

    # --- Work item stats for this iteration ---
    wi_filters = [
        WorkItem.organization_id == org_id,
        WorkItem.iteration_id == iteration.id,
    ]
    if project_id:
        wi_filters.append(WorkItem.imported_project_id == project_id)

    wi_result = await db.execute(
        select(
            func.count().label("total"),
            func.coalesce(func.sum(WorkItem.story_points), 0).label("total_sp"),
        )
        .where(*wi_filters)
    )
    row = wi_result.one()
    total_items = row[0]
    total_sp = float(row[1])

    done_result = await db.execute(
        select(
            func.count().label("done"),
            func.coalesce(func.sum(WorkItem.story_points), 0).label("done_sp"),
        )
        .where(
            *wi_filters,
            WorkItem.status.in_(["DONE", "CLOSED"]),
        )
    )
    done_row = done_result.one()
    done_sp = float(done_row[1])

    # Pacing score: how far along are we vs how far we should be
    expected_sp_by_now = total_sp * elapsed_pct if total_sp > 0 else 0
    pacing_score = (done_sp / expected_sp_by_now) if expected_sp_by_now > 0 else 1.0
    pacing_score = min(pacing_score, 1.5)  # Cap at 150% (ahead of schedule)

    # --- Active blockers ---
    blocker_result = await db.execute(
        select(BlockerFlag)
        .join(StandupReport, BlockerFlag.standup_report_id == StandupReport.id)
        .where(
            StandupReport.organization_id == org_id,
            BlockerFlag.status.in_(["OPEN", "ACKNOWLEDGED", "ESCALATED"]),
        )
    )
    active_blockers = list(blocker_result.scalars().all())
    # Weight older blockers more heavily
    blocker_penalty = 0.0
    for b in active_blockers:
        flagged = b.flagged_at
        if flagged and flagged.tzinfo is None:
            flagged = flagged.replace(tzinfo=timezone.utc)
        age_days = max((now - flagged).days, 1) if flagged else 1
        blocker_penalty += 0.05 * min(age_days, 5)  # Max 25% per blocker, capped at 5 days

    # --- PR review lag ---
    stalled_prs_result = await db.execute(
        select(func.count())
        .select_from(PullRequest)
        .where(
            PullRequest.status.in_(["OPEN", "AWAITING_REVIEW", "CHANGES_REQUESTED"]),
            PullRequest.created_at < now - timedelta(hours=48),
        )
    )
    stalled_prs = stalled_prs_result.scalar() or 0
    review_lag_penalty = stalled_prs * 0.03

    # --- CI failure rate ---
    ci_events_result = await db.execute(
        select(
            func.count().label("total_ci"),
            func.sum(
                func.cast(
                    ActivityEvent.metadata_.op("->>")("status") == "FAILED",
                    type_=func.count().type,
                )
            ).label("failed_ci"),
        )
        .where(
            ActivityEvent.organization_id == org_id,
            ActivityEvent.event_type == "CI_RUN",
            ActivityEvent.occurred_at >= sprint_start,
        )
    )
    ci_row = ci_events_result.one()
    total_ci = ci_row[0] or 0
    # Simple CI penalty: if >30% failure rate, apply penalty
    ci_penalty = 0.0
    if total_ci > 3:
        try:
            failed_ci = int(ci_row[1] or 0)
            failure_rate = failed_ci / total_ci
            if failure_rate > 0.3:
                ci_penalty = (failure_rate - 0.3) * 0.2  # Scale from 0-14%
        except (TypeError, ValueError):
            pass

    # --- Historical completion rate (team average) ---
    velocity_result = await db.execute(
        select(VelocityProfile)
        .join(TeamMember, VelocityProfile.team_member_id == TeamMember.id)
        .where(
            TeamMember.organization_id == org_id,
            TeamMember.role == "developer",
            VelocityProfile.is_cold_start == False,
        )
    )
    velocity_profiles = list(velocity_result.scalars().all())
    if velocity_profiles:
        completion_rates = []
        for vp in velocity_profiles:
            if vp.planned_sp and vp.planned_sp > 0:
                completion_rates.append(min(vp.completed_sp / vp.planned_sp, 1.0))
        historical_base = sum(completion_rates) / len(completion_rates) if completion_rates else 0.75
    else:
        historical_base = 0.75  # Default if no history

    # --- Final calculation ---
    raw_probability = (
        historical_base * pacing_score * 100
        - blocker_penalty * 100
        - review_lag_penalty * 100
        - ci_penalty * 100
    )
    success_probability = max(0, min(100, round(raw_probability)))

    return {
        "successProbability": success_probability,
        "iterationId": iteration.id,
        "pacingScore": round(pacing_score, 2),
        "blockerPenalty": round(blocker_penalty, 3),
        "reviewLagPenalty": round(review_lag_penalty, 3),
        "ciPenalty": round(ci_penalty, 3),
        "historicalBase": round(historical_base, 3),
        "completionPct": round(done_sp / total_sp * 100, 1) if total_sp > 0 else 0,
        "elapsedPct": round(elapsed_pct * 100, 1),
        "totalSP": total_sp,
        "doneSP": done_sp,
        "activeBlockers": len(active_blockers),
        "stalledPRs": stalled_prs,
    }


# ---------------------------------------------------------------------------
# Per-ticket Spillover Risk
# ---------------------------------------------------------------------------

async def calculate_spillover_risk(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    iteration_id: str | None = None,
) -> dict[str, Any]:
    """
    Tag each active work item with spillover risk (low/medium/high/critical).

    Criteria:
      * In Progress > 60% sprint elapsed with < 20% SP completed → high/critical
      * No commit or PR activity in last 3 days → high
      * Assigned developer at > 90% capacity with other items in progress → medium
      * Has unresolved blocker from standup → critical
    """
    # --- Resolve iteration ---
    if iteration_id:
        it_result = await db.execute(
            select(Iteration).where(Iteration.id == iteration_id)
        )
    else:
        iter_filters = [
            Iteration.organization_id == org_id,
            Iteration.state == "active",
        ]
        if project_id:
            iter_filters.append(Iteration.imported_project_id == project_id)
        it_result = await db.execute(
            select(Iteration)
            .where(*iter_filters)
            .order_by(Iteration.start_date.desc())
            .limit(1)
        )
    iteration = it_result.scalar_one_or_none()
    if not iteration:
        return {"items": [], "totalSpilloverSP": 0}

    now = datetime.now(timezone.utc)
    sprint_start = iteration.start_date
    sprint_end = iteration.end_date
    if sprint_start and sprint_start.tzinfo is None:
        sprint_start = sprint_start.replace(tzinfo=timezone.utc)
    if sprint_end and sprint_end.tzinfo is None:
        sprint_end = sprint_end.replace(tzinfo=timezone.utc)

    total_days = max((sprint_end - sprint_start).days, 1) if sprint_start and sprint_end else 14
    elapsed_pct = min(max((now - sprint_start).days, 0) / total_days, 1.0) if sprint_start else 0.5

    # --- Load active work items in this iteration ---
    wi_filters = [
        WorkItem.organization_id == org_id,
        WorkItem.iteration_id == iteration.id,
        WorkItem.status.in_(["BACKLOG", "TODO", "IN_PROGRESS", "IN_REVIEW"]),
    ]
    if project_id:
        wi_filters.append(WorkItem.imported_project_id == project_id)

    wi_result = await db.execute(
        select(WorkItem)
        .options(selectinload(WorkItem.assignee))
        .where(*wi_filters)
    )
    work_items = list(wi_result.scalars().all())
    if not work_items:
        return {"items": [], "totalSpilloverSP": 0}

    # --- Load active blockers by ticket reference ---
    blocker_result = await db.execute(
        select(BlockerFlag.ticket_reference)
        .join(StandupReport, BlockerFlag.standup_report_id == StandupReport.id)
        .where(
            StandupReport.organization_id == org_id,
            BlockerFlag.status.in_(["OPEN", "ACKNOWLEDGED", "ESCALATED"]),
            BlockerFlag.ticket_reference.isnot(None),
        )
    )
    blocked_ticket_refs = {r[0] for r in blocker_result.all() if r[0]}

    # --- Recent activity per team member (last 3 days) ---
    three_days_ago = now - timedelta(days=3)
    activity_result = await db.execute(
        select(
            ActivityEvent.linked_ticket_id,
            func.count().label("cnt"),
        )
        .where(
            ActivityEvent.organization_id == org_id,
            ActivityEvent.occurred_at >= three_days_ago,
            ActivityEvent.event_type.in_(["COMMIT_PUSHED", "PR_OPENED", "PR_UPDATED", "PR_MERGED"]),
        )
        .group_by(ActivityEvent.linked_ticket_id)
    )
    recent_activity: dict[str, int] = {}
    for ticket_id, cnt in activity_result.all():
        if ticket_id:
            recent_activity[ticket_id] = cnt

    # --- Developer load: count in-progress items per assignee ---
    load_filters = [
        WorkItem.organization_id == org_id,
        WorkItem.iteration_id == iteration.id,
        WorkItem.status.in_(["IN_PROGRESS", "IN_REVIEW"]),
        WorkItem.assignee_id.isnot(None),
    ]
    if project_id:
        load_filters.append(WorkItem.imported_project_id == project_id)

    load_result = await db.execute(
        select(
            WorkItem.assignee_id,
            func.count().label("active_count"),
            func.coalesce(func.sum(WorkItem.story_points), 0).label("active_sp"),
        )
        .where(*load_filters)
        .group_by(WorkItem.assignee_id)
    )
    dev_load: dict[str, dict] = {}
    for assignee_id, count, sp in load_result.all():
        dev_load[assignee_id] = {"count": count, "sp": float(sp)}

    # --- Developer capacity ---
    member_result = await db.execute(
        select(TeamMember)
        .where(
            TeamMember.organization_id == org_id,
            TeamMember.role == "developer",
        )
    )
    members = {m.id: m for m in member_result.scalars().all()}
    sprint_weeks = max(total_days / 7, 1)
    dev_capacity: dict[str, float] = {}
    for mid, m in members.items():
        dev_capacity[mid] = (m.default_capacity * sprint_weeks) / 5.0  # SP capacity

    # --- Tag each work item ---
    tagged_items: list[dict] = []
    total_spillover_sp = 0

    for wi in work_items:
        risk = "low"
        reasons: list[str] = []
        sp = wi.story_points or 0

        # Check 1: Has unresolved blocker → critical
        if wi.external_id in blocked_ticket_refs:
            risk = "critical"
            reasons.append("Unresolved blocker from standup")

        # Check 2: In Progress with no recent activity
        if wi.status in ("IN_PROGRESS", "IN_REVIEW"):
            has_activity = recent_activity.get(wi.external_id, 0) > 0
            if not has_activity:
                if risk != "critical":
                    risk = "high"
                reasons.append("No commit/PR activity in last 3 days")

        # Check 3: In Progress but sprint > 60% elapsed
        if wi.status == "IN_PROGRESS" and elapsed_pct > 0.6:
            if risk not in ("critical", "high"):
                risk = "high"
            reasons.append(f"Sprint {round(elapsed_pct*100)}% elapsed, still in progress")

        # Check 4: Developer capacity overloaded
        if wi.assignee_id and wi.assignee_id in dev_capacity:
            cap = dev_capacity[wi.assignee_id]
            load = dev_load.get(wi.assignee_id, {}).get("sp", 0)
            if cap > 0 and (load / cap) > 0.9:
                if risk == "low":
                    risk = "medium"
                reasons.append("Assigned developer at >90% capacity")

        # Check 5: TODO items late in sprint
        if wi.status in ("BACKLOG", "TODO") and elapsed_pct > 0.5:
            if risk == "low":
                risk = "medium"
            reasons.append("Not started, sprint >50% elapsed")

        # Persist risk to DB
        wi.spillover_risk = risk
        wi.spillover_reason = "; ".join(reasons) if reasons else None

        if risk in ("medium", "high", "critical"):
            total_spillover_sp += sp
            tagged_items.append({
                "workItemId": wi.id,
                "externalId": wi.external_id,
                "title": wi.title,
                "status": wi.status,
                "storyPoints": sp,
                "assigneeId": wi.assignee_id,
                "assigneeName": wi.assignee.display_name if wi.assignee else None,
                "spilloverRisk": risk,
                "spilloverReason": "; ".join(reasons),
            })

    await db.flush()

    # Sort: critical first, then high, then medium
    risk_order = {"critical": 0, "high": 1, "medium": 2}
    tagged_items.sort(key=lambda x: risk_order.get(x["spilloverRisk"], 3))

    return {
        "items": tagged_items,
        "totalSpilloverSP": round(total_spillover_sp),
        "iterationId": iteration.id,
    }


# ---------------------------------------------------------------------------
# Orchestrator: refresh forecast and persist to SprintPlan
# ---------------------------------------------------------------------------

async def refresh_forecast(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    iteration_id: str | None = None,
) -> dict[str, Any]:
    """
    Recalculate success probability + spillover risk, persist to SprintPlan.

    Called:
      * On ActivityEvent arrival for this project
      * On explicit forecast refresh request
    """
    prob_data = await calculate_success_probability(db, org_id, project_id, iteration_id)
    spillover_data = await calculate_spillover_risk(db, org_id, project_id, iteration_id)

    resolved_iteration_id = prob_data.get("iterationId") or spillover_data.get("iterationId")
    if not resolved_iteration_id:
        return {**prob_data, **spillover_data}

    # Find the latest plan for this iteration
    plan_result = await db.execute(
        select(SprintPlan)
        .where(
            SprintPlan.organization_id == org_id,
            SprintPlan.iteration_id == resolved_iteration_id,
        )
        .order_by(SprintPlan.created_at.desc())
        .limit(1)
    )
    plan = plan_result.scalar_one_or_none()

    if plan:
        plan.success_probability = prob_data.get("successProbability")
        plan.spillover_risk_sp = spillover_data.get("totalSpilloverSP", 0)
        plan.forecast_updated_at = datetime.now(timezone.utc)
        await db.flush()
        logger.info(
            f"Forecast updated: plan={plan.id} "
            f"success={plan.success_probability}% "
            f"spillover={plan.spillover_risk_sp}SP"
        )

    return {
        **prob_data,
        "spilloverItems": spillover_data["items"],
        "totalSpilloverSP": spillover_data["totalSpilloverSP"],
        "forecastUpdatedAt": datetime.now(timezone.utc).isoformat(),
    }

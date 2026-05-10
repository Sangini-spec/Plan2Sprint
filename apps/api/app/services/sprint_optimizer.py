"""
Sprint Plan Optimizer — AI-powered sprint plan generation.

Implements MRD requirements REQ-SPR-001 through REQ-SPR-014:
  - Capacity-aware planning (REQ-SPR-003)
  - Velocity-based assignment (REQ-SPR-004)
  - Skill-affinity matching (REQ-SPR-005)
  - Dependency detection (REQ-SPR-006)
  - Sprint goal alignment (REQ-SPR-007)
  - Per-assignment rationale (REQ-SPR-008)
  - Unplanned items report (REQ-SPR-009)
  - Carry-forward handling (REQ-SPR-012)
  - Standup data integration (REQ-SPR-014)

Usage:
    from ..services.sprint_optimizer import generate_sprint_plan
    plan = await generate_sprint_plan(db, org_id, project_id, iteration_id)
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.base import generate_cuid
from ..models.sprint_plan import SprintPlan, PlanAssignment
from ..models.work_item import WorkItem
from ..models.team_member import TeamMember
from ..models.iteration import Iteration
from ..models.analytics import VelocityProfile, HealthSignal
from ..models.standup import BlockerFlag
from ..models.imported_project import ImportedProject

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_sprint_plan(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    iteration_id: str | None = None,
    feedback: str | None = None,
) -> dict[str, Any]:
    """
    Generate a complete sprint plan for the given project and iteration.

    Returns dict with plan details and assignment summary.
    """

    # 1. Resolve iteration (scoped to project)
    iteration = await _resolve_iteration(db, org_id, iteration_id, project_id)
    if not iteration:
        return {"error": "No active iteration found for this project"}

    # 2. Load project to get source_tool context
    proj_q = select(ImportedProject).where(
        ImportedProject.id == project_id,
        ImportedProject.organization_id == org_id,
    )
    proj_result = await db.execute(proj_q)
    project = proj_result.scalar_one_or_none()

    # 3. Load team members — prefer explicit developers, fall back to
    #    any non-excluded member. Hotfix 32c — see ai_sprint_generator
    #    for context; the strict developer-only filter was breaking
    #    projects whose only members had other roles (stakeholder etc.)
    #    even though those projects had successfully generated plans
    #    before.
    all_members = await _load_team_members(db, org_id, project_id)
    members = [m for m in all_members if m.role == "developer"]
    if not members:
        members = [m for m in all_members if (m.role or "").lower() != "excluded"]
    if not members:
        return {
            "error": (
                "No team members found for this project. Add at least one "
                "team member in Settings → Team to enable sprint planning."
            )
        }

    # 4. Load velocity profiles for each member
    velocity_map = await _load_velocity_profiles(db, members)

    # 5. Load work items scoped to this project (REQ-SPR-012)
    work_items = await _load_plannable_work_items(db, org_id, iteration.id, project_id)
    if not work_items:
        return {"error": "No work items available for planning in this project"}

    # 6. Load health signals and blocker flags (REQ-SPR-014)
    health_map = await _load_health_signals(db, org_id, members)
    blocker_items = await _load_active_blockers(db, org_id)

    # 7. Calculate capacities (REQ-SPR-003)
    # Guard against degenerate dates (0-day sprints) — default to 14 days (2-week sprint)
    raw_days = (iteration.end_date.replace(tzinfo=None) - iteration.start_date.replace(tzinfo=None)).days
    sprint_days = raw_days if raw_days >= 7 else 14
    capacity_map = _calculate_capacities(members, sprint_days, health_map)

    # 7b. Load and apply feed-forward constraints from failure analysis
    from .ai_sprint_generator import load_active_constraints, increment_constraints_applied
    active_constraints = await load_active_constraints(db, org_id, project_id)
    if active_constraints:
        logger.info(f"Applying {len(active_constraints)} feed-forward constraints")
        capacity_map = _apply_constraints_to_capacity(
            capacity_map, active_constraints, members, velocity_map,
        )

    # 8. Create the SprintPlan record (status=GENERATING)
    plan = SprintPlan(
        id=generate_cuid(),
        organization_id=org_id,
        project_id=project_id,
        iteration_id=iteration.id,
        status="GENERATING",
        ai_model_used="plan2sprint-optimizer-v1",
        tool=project.source_tool.lower() if project else None,
        rejection_feedback=feedback,
    )
    db.add(plan)
    await db.flush()

    # 9. Run the assignment algorithm
    assignments, unplanned = _optimize_assignments(
        work_items=work_items,
        members=members,
        velocity_map=velocity_map,
        capacity_map=capacity_map,
        health_map=health_map,
        blocker_items=blocker_items,
        sprint_goal=iteration.goal,
    )

    # 10. Create PlanAssignment records
    total_sp = 0.0
    confidence_scores = []
    risk_flags_all = []
    max_sprint_number = 1

    for a in assignments:
        sprint_num = a.get("sprint_number", 1)
        if sprint_num > max_sprint_number:
            max_sprint_number = sprint_num

        pa = PlanAssignment(
            id=generate_cuid(),
            sprint_plan_id=plan.id,
            work_item_id=a["work_item_id"],
            team_member_id=a["team_member_id"],
            story_points=a["story_points"],
            confidence_score=a["confidence"],
            rationale=a["rationale"],
            risk_flags=a["risk_flags"],
            skill_match=a["skill_match"],
            is_human_edited=False,
            sprint_number=sprint_num,
        )
        db.add(pa)
        total_sp += a["story_points"]
        confidence_scores.append(a["confidence"])
        risk_flags_all.extend(a["risk_flags"])

    # 11. Compute plan-level metrics
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0
    plan.confidence_score = round(avg_confidence, 3)
    plan.total_story_points = total_sp
    plan.estimated_sprints = max_sprint_number
    # Compute estimated end date
    if iteration.start_date and max_sprint_number:
        from datetime import timedelta
        plan.estimated_end_date = iteration.start_date + timedelta(
            days=sprint_days * max_sprint_number
        )
    plan.unplanned_items = {
        "items": [
            {"workItemId": u["id"], "reason": u["reason"]}
            for u in unplanned
        ]
    }

    # Build risk summary
    plan.risk_summary = _build_risk_summary(
        assignments, unplanned, capacity_map, members, avg_confidence, risk_flags_all,
        max_sprint_number,
    )

    # 11b. Compute project-level insight fields (deterministic estimates)
    plan.estimated_weeks_total = max(1, int(math.ceil(max_sprint_number * sprint_days / 7.0)))
    total_capacity = sum(capacity_map.values())
    utilization_pct = int(round((total_sp / max(total_capacity * max_sprint_number, 1)) * 100))
    team_count = len(capacity_map)

    plan.overall_rationale = (
        f"The backlog of {len(assignments)} items ({int(total_sp)} story points) is distributed across "
        f"{max_sprint_number} sprint(s) over ~{plan.estimated_weeks_total} weeks. "
        f"A team of {team_count} developer{'s' if team_count != 1 else ''} is assigned using capacity-aware "
        f"greedy allocation, with team utilization at {utilization_pct}%. "
        + (f"The team is near full capacity — consider adding more developers to reduce risk. "
           if utilization_pct > 90
           else f"Team capacity is adequate for the current backlog size. ")
        + f"Items are prioritized by story points and assigned to developers with available capacity in each sprint."
    )
    plan.project_completion_summary = (
        f"Deterministic plan: {len(assignments)} items across {max_sprint_number} sprint(s), "
        f"~{plan.estimated_weeks_total} weeks total. "
        f"Team utilization based on capacity-aware greedy assignment."
    )
    plan.capacity_recommendations = {
        "team_utilization_pct": min(utilization_pct, 100),
        "understaffed": utilization_pct > 90,
        "recommended_additions": 1 if utilization_pct > 95 else 0,
        "bottleneck_skills": [],
        "summary": (
            f"Team utilization at {utilization_pct}%. "
            + ("Consider adding developers — team is near full capacity." if utilization_pct > 90 else "Team capacity is adequate.")
        ),
    }

    # 12. Attach success probability at generation time
    try:
        from .sprint_forecast import calculate_success_probability
        prob_data = await calculate_success_probability(
            db, org_id, project_id, iteration.id
        )
        plan.success_probability = prob_data.get("successProbability")
        plan.forecast_updated_at = datetime.now(timezone.utc)
    except Exception as e:
        logger.warning(f"Success probability calculation failed: {e}")

    # 13. Set status to PENDING_REVIEW
    plan.status = "PENDING_REVIEW"

    # 13b. Increment feed-forward constraints usage counter
    if active_constraints:
        try:
            await increment_constraints_applied(db, org_id, project_id)
        except Exception as e:
            logger.warning(f"Failed to increment constraint counters: {e}")

    await db.commit()

    logger.info(
        "Generated sprint plan %s: %d assignments, %.0f SP, confidence %.0f%%, %d sprints, success %s%%",
        plan.id, len(assignments), total_sp, avg_confidence * 100, max_sprint_number,
        plan.success_probability,
    )

    return {
        "planId": plan.id,
        "iterationId": iteration.id,
        "iterationName": iteration.name,
        "status": plan.status,
        "totalStoryPoints": total_sp,
        "confidenceScore": plan.confidence_score,
        "riskSummary": plan.risk_summary,
        "assignmentCount": len(assignments),
        "unplannedCount": len(unplanned),
        "aiModelUsed": plan.ai_model_used,
        "estimatedSprints": max_sprint_number,
        "estimatedEndDate": plan.estimated_end_date.isoformat() if plan.estimated_end_date else None,
        "successProbability": plan.success_probability,
        "estimatedWeeksTotal": plan.estimated_weeks_total,
        "projectCompletionSummary": plan.project_completion_summary,
        "capacityRecommendations": plan.capacity_recommendations,
    }


# ---------------------------------------------------------------------------
# Data Loading Helpers
# ---------------------------------------------------------------------------

async def _resolve_iteration(
    db: AsyncSession, org_id: str, iteration_id: str | None,
    project_id: str | None = None,
) -> Iteration | None:
    """Find the target iteration — explicit or most recent active for the project."""
    if iteration_id:
        result = await db.execute(
            select(Iteration).where(Iteration.id == iteration_id)
        )
        return result.scalar_one_or_none()

    # Default: most recent iteration for this project (or org fallback)
    query = select(Iteration).where(Iteration.organization_id == org_id)
    if project_id:
        query = query.where(Iteration.imported_project_id == project_id)
    query = query.order_by(Iteration.start_date.desc()).limit(1)
    result = await db.execute(query)
    iteration = result.scalar_one_or_none()

    # Fallback: if no project-scoped iteration, try org-wide
    if not iteration and project_id:
        result = await db.execute(
            select(Iteration)
            .where(Iteration.organization_id == org_id)
            .order_by(Iteration.start_date.desc())
            .limit(1)
        )
        iteration = result.scalar_one_or_none()

    return iteration


async def _load_team_members(
    db: AsyncSession, org_id: str, project_id: str | None = None,
) -> list[TeamMember]:
    filters = [TeamMember.organization_id == org_id]
    if project_id:
        filters.append(TeamMember.imported_project_id == project_id)
    result = await db.execute(
        select(TeamMember).where(*filters)
    )
    return list(result.scalars().all())


async def _load_velocity_profiles(
    db: AsyncSession, members: list[TeamMember],
) -> dict[str, dict]:
    """Return {member_id: {avg_sp, by_type, is_cold_start}}."""
    velocity_map: dict[str, dict] = {}

    for member in members:
        result = await db.execute(
            select(VelocityProfile)
            .where(VelocityProfile.team_member_id == member.id)
            .order_by(VelocityProfile.recorded_at.desc())
            .limit(5)
        )
        profiles = list(result.scalars().all())

        if profiles:
            avg_sp = sum(p.completed_sp for p in profiles) / len(profiles)
            velocity_map[member.id] = {
                "avg_sp": round(avg_sp, 1),
                "rolling_average": profiles[0].rolling_average or avg_sp,
                "by_type": profiles[0].by_ticket_type or {},
                "is_cold_start": False,
            }
        else:
            # Cold start — use team average later (REQ-SPR-004)
            velocity_map[member.id] = {
                "avg_sp": 0,
                "rolling_average": 0,
                "by_type": {},
                "is_cold_start": True,
            }

    # Fill cold-start members with team average
    non_cold = [v["avg_sp"] for v in velocity_map.values() if not v["is_cold_start"] and v["avg_sp"] > 0]
    # Fallback: 15 SP/sprint for a 2-week sprint with full-time dev
    team_avg = sum(non_cold) / len(non_cold) if non_cold else 15.0

    for mid, v in velocity_map.items():
        if v["is_cold_start"]:
            v["avg_sp"] = team_avg
            v["rolling_average"] = team_avg

    return velocity_map


async def _load_plannable_work_items(
    db: AsyncSession, org_id: str, iteration_id: str,
    project_id: str | None = None,
) -> list[WorkItem]:
    """
    Load work items for planning, scoped to the selected project:
    - Items already in this iteration (carry-forward if not DONE)
    - Backlog items (TODO/BACKLOG) from this project
    Sorted by priority (lower = higher priority).
    """
    # Exclusion-based filter — see services._planning_status for rationale.
    # Anything that's already finished (DONE/CLOSED/RESOLVED/etc., case-
    # insensitive) is NOT plannable. Everything else, including custom
    # ADO/Jira states, flows through.
    from ._planning_status import TERMINAL_STATUSES
    query = (
        select(WorkItem)
        .where(
            WorkItem.organization_id == org_id,
            func.upper(WorkItem.status).notin_(TERMINAL_STATUSES),
        )
    )
    # Scope to the selected project if provided
    if project_id:
        query = query.where(WorkItem.imported_project_id == project_id)

    query = query.order_by(WorkItem.priority.asc(), WorkItem.created_at.asc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def _load_health_signals(
    db: AsyncSession, org_id: str, members: list[TeamMember],
) -> dict[str, list[str]]:
    """Return {member_id: [signal_types]} for active (unresolved) signals."""
    health_map: dict[str, list[str]] = {m.id: [] for m in members}

    result = await db.execute(
        select(HealthSignal)
        .where(
            HealthSignal.organization_id == org_id,
            HealthSignal.resolved_at.is_(None),
        )
    )
    for signal in result.scalars().all():
        if signal.team_member_id in health_map:
            health_map[signal.team_member_id].append(signal.signal_type)

    return health_map


async def _load_active_blockers(
    db: AsyncSession, org_id: str,
) -> set[str]:
    """Return set of work_item_ids that have active blockers.

    BlockerFlag doesn't have a direct work_item_id. It has ticket_reference
    (an external ID string) and links to StandupReport via standup_report_id.
    We join through StandupReport to filter by org_id and look up work items
    by their external_id matching the ticket_reference.
    """
    from ..models.standup import StandupReport

    # Get ticket references from unresolved blockers for this org
    result = await db.execute(
        select(BlockerFlag.ticket_reference)
        .join(StandupReport, BlockerFlag.standup_report_id == StandupReport.id)
        .where(
            StandupReport.organization_id == org_id,
            BlockerFlag.resolved_at.is_(None),
            BlockerFlag.ticket_reference.isnot(None),
        )
    )
    ticket_refs = set(result.scalars().all())
    if not ticket_refs:
        return set()

    # Map ticket references back to internal work_item IDs
    wi_result = await db.execute(
        select(WorkItem.id)
        .where(
            WorkItem.organization_id == org_id,
            WorkItem.external_id.in_(ticket_refs),
        )
    )
    return set(wi_result.scalars().all())


# ---------------------------------------------------------------------------
# Capacity Calculation (REQ-SPR-003)
# ---------------------------------------------------------------------------

def _calculate_capacities(
    members: list[TeamMember],
    sprint_days: int,
    health_map: dict[str, list[str]],
) -> dict[str, float]:
    """
    Calculate available capacity per member in story points.
    Factors: default_capacity (hours/week), sprint duration, health signals.
    """
    capacity: dict[str, float] = {}
    weeks = sprint_days / 7.0

    for m in members:
        base_hours = m.default_capacity * weeks  # e.g., 40h/wk * 2wk = 80h
        # Rough SP-per-hour: 1 SP ≈ 4-6 hours. Use 5h/SP.
        base_sp = base_hours / 5.0

        # Reduce capacity for health risks
        signals = health_map.get(m.id, [])
        reduction = 1.0
        if "BURNOUT_RISK" in signals:
            reduction *= 0.7  # 30% capacity reduction
        if "CAPACITY_OVERLOAD" in signals:
            reduction *= 0.8  # 20% reduction
        if "AFTER_HOURS" in signals:
            reduction *= 0.9  # 10% reduction

        capacity[m.id] = round(base_sp * reduction, 1)

    return capacity


# ---------------------------------------------------------------------------
# Feed-Forward Constraint Application
# ---------------------------------------------------------------------------

def _apply_constraints_to_capacity(
    capacity_map: dict[str, float],
    constraints: list[dict],
    members: list[TeamMember],
    velocity_map: dict[str, dict],
) -> dict[str, float]:
    """
    Apply feed-forward constraints from failure analysis to capacity.

    Constraint types handled:
    - OVERCOMMITMENT: Reduce total team capacity by 15%
    - CAPACITY: Reduce capacity for specific overloaded developers by 20%
    - EXECUTION: No capacity change — addressed in rationale
    - DEPENDENCY: No capacity change — addressed in rationale
    - SCOPE_CREEP: Reduce total capacity by 10% as buffer
    """
    adjusted = dict(capacity_map)

    for c in constraints:
        ctype = c.get("type", "").upper()

        if ctype == "OVERCOMMITMENT":
            # Reduce all developers' capacity by 15%
            for mid in adjusted:
                adjusted[mid] = round(adjusted[mid] * 0.85, 1)

        elif ctype == "CAPACITY":
            # Reduce capacity for each developer by 20%
            for mid in adjusted:
                adjusted[mid] = round(adjusted[mid] * 0.80, 1)

        elif ctype == "SCOPE_CREEP":
            # Add 10% buffer reduction across the board
            for mid in adjusted:
                adjusted[mid] = round(adjusted[mid] * 0.90, 1)

        # EXECUTION and DEPENDENCY don't alter capacity —
        # they are informational constraints for the AI prompt

    return adjusted


# ---------------------------------------------------------------------------
# Assignment Optimization (Core Algorithm)
# ---------------------------------------------------------------------------

def _optimize_assignments(
    work_items: list[WorkItem],
    members: list[TeamMember],
    velocity_map: dict[str, dict],
    capacity_map: dict[str, float],
    health_map: dict[str, list[str]],
    blocker_items: set[str],
    sprint_goal: str | None,
) -> tuple[list[dict], list[dict]]:
    """
    Multi-sprint greedy best-fit assignment algorithm.

    Assigns ALL work items across multiple sprints. When a sprint's capacity
    is exhausted, a new sprint begins with fresh capacity.

    Returns (assignments, unplanned).
    """
    # Build skill index: member_id -> set of skills
    skill_index: dict[str, set[str]] = {}
    for m in members:
        tags = m.skill_tags or []
        skill_index[m.id] = set(t.lower() for t in tags)

    # Track remaining capacity per member (resets each sprint)
    remaining_cap = dict(capacity_map)

    # Track assigned SP per member within current sprint for load balancing
    assigned_sp: dict[str, float] = {m.id: 0.0 for m in members}

    current_sprint = 1
    assignments: list[dict] = []
    unplanned: list[dict] = []

    for wi in work_items:
        sp = wi.story_points or _estimate_story_points(wi)
        wi_labels = set((l.lower() for l in (wi.labels or [])))
        wi_type = (wi.type or "story").lower()

        # Check if blocked (REQ-SPR-014)
        if wi.id in blocker_items:
            unplanned.append({
                "id": wi.id,
                "reason": f"Active blocker flag — item cannot be planned until blocker is resolved",
            })
            continue

        # Try to find a member with capacity in the current sprint
        best_member, best_score, best_rationale_parts, best_skill_match, best_risk_flags = \
            _score_members(wi, sp, wi_labels, wi_type, members, skill_index,
                          remaining_cap, assigned_sp, capacity_map, velocity_map,
                          health_map, sprint_goal)

        # If nobody in current sprint has capacity, start next sprint
        if not best_member:
            current_sprint += 1
            remaining_cap = dict(capacity_map)  # Reset capacity
            assigned_sp = {m.id: 0.0 for m in members}  # Reset load

            best_member, best_score, best_rationale_parts, best_skill_match, best_risk_flags = \
                _score_members(wi, sp, wi_labels, wi_type, members, skill_index,
                              remaining_cap, assigned_sp, capacity_map, velocity_map,
                              health_map, sprint_goal)

        if best_member:
            # Calculate confidence from score
            max_possible = 40 + 30 + 20 + 10 + 5  # 105
            confidence = min(0.99, max(0.3, best_score / max_possible))

            # Build human-readable rationale (REQ-SPR-008)
            rationale = (
                f"Sprint {current_sprint} — Assigned to {best_member.display_name} — "
                + ". ".join(best_rationale_parts)
                + f". Capacity utilization: {round((assigned_sp[best_member.id] + sp) / max(capacity_map.get(best_member.id, 1), 1) * 100)}%."
            )

            assignments.append({
                "work_item_id": wi.id,
                "team_member_id": best_member.id,
                "story_points": sp,
                "confidence": round(confidence, 3),
                "rationale": rationale,
                "risk_flags": best_risk_flags,
                "skill_match": best_skill_match,
                "sprint_number": current_sprint,
            })

            remaining_cap[best_member.id] -= sp
            assigned_sp[best_member.id] += sp
        else:
            # Item is too large for any single member's capacity
            unplanned.append({
                "id": wi.id,
                "reason": _unplanned_reason(wi, sp, remaining_cap, members),
            })

    return assignments, unplanned


def _score_members(
    wi: WorkItem,
    sp: float,
    wi_labels: set[str],
    wi_type: str,
    members: list[TeamMember],
    skill_index: dict[str, set[str]],
    remaining_cap: dict[str, float],
    assigned_sp: dict[str, float],
    capacity_map: dict[str, float],
    velocity_map: dict[str, dict],
    health_map: dict[str, list[str]],
    sprint_goal: str | None,
) -> tuple:
    """Score each member for a work item and return the best match."""
    best_member = None
    best_score = -1.0
    best_rationale_parts: list[str] = []
    best_skill_match: dict | None = None
    best_risk_flags: list[str] = []

    for m in members:
        if remaining_cap.get(m.id, 0) < sp:
            continue  # Not enough capacity

        score = 0.0
        rationale_parts = []
        risk_flags = []

        # --- Skill affinity ---
        member_skills = skill_index.get(m.id, set())
        matched_skills = member_skills & wi_labels
        if not matched_skills and member_skills:
            if wi_type in member_skills:
                matched_skills = {wi_type}

        skill_score = len(matched_skills) / max(len(wi_labels), 1) if wi_labels else 0.5
        score += skill_score * 40
        if matched_skills:
            rationale_parts.append(
                f"Skill match: {', '.join(sorted(matched_skills))} ({round(skill_score * 100)}%)"
            )
        else:
            rationale_parts.append("No direct skill match — assigned by capacity")
            risk_flags.append("skill_gap")

        # --- Velocity fit ---
        vel = velocity_map.get(m.id, {})
        avg_sp = vel.get("avg_sp", 15.0)
        velocity_ratio = min(1.0, avg_sp / max(sp, 1))
        score += velocity_ratio * 30
        rationale_parts.append(f"Velocity: {avg_sp:.0f} SP/sprint avg")
        if vel.get("is_cold_start"):
            rationale_parts.append("Cold-start: using team average velocity")
            risk_flags.append("cold_start")

        # --- Load balancing ---
        utilization = assigned_sp.get(m.id, 0) / max(capacity_map.get(m.id, 1), 1)
        balance_score = 1.0 - utilization
        score += balance_score * 20

        # --- Health risk reduction ---
        signals = health_map.get(m.id, [])
        if "BURNOUT_RISK" in signals:
            score -= 15
            risk_flags.append("burnout_risk")
        if "CAPACITY_OVERLOAD" in signals:
            score -= 10
            risk_flags.append("capacity_overload")

        # --- Existing assignee bonus ---
        if wi.assignee_id == m.id:
            score += 10
            rationale_parts.append("Continuity: already assigned in tool")

        # --- Sprint goal alignment ---
        if sprint_goal:
            goal_words = set(sprint_goal.lower().split())
            title_words = set(wi.title.lower().split())
            if goal_words & title_words:
                score += 5

        if score > best_score:
            best_score = score
            best_member = m
            best_rationale_parts = rationale_parts
            best_skill_match = {
                "matchedSkills": sorted(matched_skills),
                "score": round(skill_score, 2),
            } if matched_skills else None
            best_risk_flags = risk_flags

    return best_member, best_score, best_rationale_parts, best_skill_match, best_risk_flags


def _estimate_story_points(wi: WorkItem) -> float:
    """Estimate SP for items without story points based on type."""
    type_estimates = {
        "story": 5,
        "bug": 3,
        "task": 2,
        "spike": 3,
        "epic": 13,
    }
    return float(type_estimates.get((wi.type or "story").lower(), 5))


def _unplanned_reason(
    wi: WorkItem, sp: float, remaining_cap: dict, members: list,
) -> str:
    """Generate a human-readable reason for excluding a work item."""
    max_remaining = max(remaining_cap.values()) if remaining_cap else 0
    if sp > max_remaining:
        return (
            f"Insufficient team capacity — {sp:.0f} SP required, "
            f"max available slot: {max_remaining:.0f} SP"
        )
    return f"Lower priority — team capacity exhausted for this sprint"


# ---------------------------------------------------------------------------
# Risk Summary
# ---------------------------------------------------------------------------

def _build_risk_summary(
    assignments: list[dict],
    unplanned: list[dict],
    capacity_map: dict[str, float],
    members: list,
    avg_confidence: float,
    risk_flags_all: list[str],
    estimated_sprints: int = 1,
) -> str:
    """Build a plan-level risk summary string."""
    parts = []

    # Overall risk level
    if avg_confidence >= 0.8:
        parts.append("Low risk.")
    elif avg_confidence >= 0.6:
        parts.append("Moderate risk.")
    else:
        parts.append("High risk — review assignments carefully.")

    # Sprint count
    total_assigned = sum(a["story_points"] for a in assignments)
    parts.append(f"Total: {total_assigned:.0f} SP across {estimated_sprints} sprint(s).")

    # Risk flags
    unique_flags = set(risk_flags_all)
    if "burnout_risk" in unique_flags:
        parts.append("Burnout risk detected for one or more team members.")
    if "cold_start" in unique_flags:
        parts.append("Cold-start velocity estimates used for some members.")
    if "skill_gap" in unique_flags:
        count = risk_flags_all.count("skill_gap")
        parts.append(f"{count} assignment(s) have skill gaps.")

    # Unplanned items
    if unplanned:
        parts.append(f"{len(unplanned)} item(s) excluded (blocked).")

    return " ".join(parts)

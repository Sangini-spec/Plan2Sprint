"""
Velocity Profile Calculator — calculate and update team member velocity from sprint history.

For each team member:
  1. Query completed work items from past sprints (PlanAssignment → WorkItem)
  2. Group by iteration (sprint) and sum completed story points
  3. Calculate rolling average
  4. Store/update VelocityProfile records

Cold-start handling: if a member has fewer than 3 sprints of history,
use the team average with is_cold_start=True.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.base import generate_cuid
from ..models.sprint_plan import SprintPlan, PlanAssignment
from ..models.work_item import WorkItem
from ..models.team_member import TeamMember
from ..models.iteration import Iteration
from ..models.analytics import VelocityProfile

logger = logging.getLogger(__name__)


async def calculate_velocity_profiles(
    db: AsyncSession,
    org_id: str,
    team_members: list[TeamMember] | None = None,
) -> dict[str, dict]:
    """
    Calculate velocity profiles for all team members in the org.

    Returns a dict: { member_id: { avg_sp, rolling_average, by_type, is_cold_start } }
    """
    # Load team members if not provided
    if team_members is None:
        result = await db.execute(
            select(TeamMember).where(TeamMember.organization_id == org_id)
        )
        team_members = list(result.scalars().all())

    if not team_members:
        return {}

    velocity_map: dict[str, dict] = {}

    for member in team_members:
        # Query completed assignments from past APPROVED sprint plans
        # Join PlanAssignment → SprintPlan (APPROVED/SYNCED) → get completed work items
        assignments_q = (
            select(
                PlanAssignment.story_points,
                SprintPlan.iteration_id,
                WorkItem.type,
                WorkItem.status,
            )
            .join(SprintPlan, PlanAssignment.sprint_plan_id == SprintPlan.id)
            .join(WorkItem, PlanAssignment.work_item_id == WorkItem.id)
            .where(
                PlanAssignment.team_member_id == member.id,
                SprintPlan.organization_id == org_id,
                SprintPlan.status.in_(["APPROVED", "SYNCED", "SYNCED_PARTIAL"]),
            )
        )
        result = await db.execute(assignments_q)
        rows = result.all()

        if not rows:
            # No historical data — mark as cold start
            velocity_map[member.id] = {
                "avg_sp": 0,
                "rolling_average": 0,
                "by_type": {},
                "is_cold_start": True,
            }
            continue

        # Group by iteration to get per-sprint totals
        sprint_totals: dict[str, float] = {}
        type_totals: dict[str, float] = {}

        for sp, iter_id, wi_type, wi_status in rows:
            sp_val = sp or 0
            sprint_totals[iter_id] = sprint_totals.get(iter_id, 0) + sp_val

            # Only count completed items for velocity by type
            if wi_status in ("DONE", "IN_REVIEW"):
                type_key = (wi_type or "story").lower()
                type_totals[type_key] = type_totals.get(type_key, 0) + sp_val

        # Calculate rolling average from last N sprints
        sprint_sps = list(sprint_totals.values())
        last_n = sprint_sps[-10:]  # Last 10 sprints

        avg_sp = sum(last_n) / len(last_n) if last_n else 0
        is_cold_start = len(last_n) < 3

        velocity_map[member.id] = {
            "avg_sp": round(avg_sp, 1),
            "rolling_average": round(avg_sp, 1),
            "by_type": type_totals,
            "is_cold_start": is_cold_start,
        }

    # Fill cold-start members with team average
    non_cold = [
        v["avg_sp"]
        for v in velocity_map.values()
        if not v["is_cold_start"] and v["avg_sp"] > 0
    ]
    # Fallback: 15 SP/sprint is a reasonable 2-week estimate for a full-time dev
    # (~3 SP/day × 5 days = 15 SP, or 40h/wk × 2wk ÷ 5h/SP = 16 SP)
    team_avg = sum(non_cold) / len(non_cold) if non_cold else 15.0

    for mid, v in velocity_map.items():
        if v["is_cold_start"]:
            v["avg_sp"] = team_avg
            v["rolling_average"] = team_avg

    # Persist velocity profiles to DB
    for member in team_members:
        vel = velocity_map.get(member.id)
        if not vel:
            continue

        # Create or update the latest velocity profile
        existing_q = (
            select(VelocityProfile)
            .where(VelocityProfile.team_member_id == member.id)
            .order_by(VelocityProfile.recorded_at.desc())
            .limit(1)
        )
        existing_result = await db.execute(existing_q)
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.planned_sp = vel["avg_sp"]
            existing.completed_sp = vel["avg_sp"]
            existing.rolling_average = vel["rolling_average"]
            existing.by_ticket_type = vel["by_type"]
            existing.is_cold_start = vel["is_cold_start"]
            existing.recorded_at = datetime.now(timezone.utc)
        else:
            profile = VelocityProfile(
                id=generate_cuid(),
                team_member_id=member.id,
                iteration_id=None,
                planned_sp=vel["avg_sp"],
                completed_sp=vel["avg_sp"],
                rolling_average=vel["rolling_average"],
                by_ticket_type=vel["by_type"],
                is_cold_start=vel["is_cold_start"],
            )
            db.add(profile)

    await db.flush()

    logger.info(
        f"Velocity profiles updated: {len(velocity_map)} members, "
        f"team avg: {team_avg:.1f} SP/sprint, "
        f"{sum(1 for v in velocity_map.values() if v['is_cold_start'])} cold-start"
    )

    return velocity_map


async def record_sprint_velocity(
    db: AsyncSession,
    org_id: str,
    iteration_id: str,
) -> dict[str, dict]:
    """
    Record per-sprint VelocityProfile entries for all team members.

    Called when a sprint is completed. Creates one VelocityProfile row per
    team member WITH iteration_id set, so the analytics trend chart can
    show per-sprint planned vs completed SP.

    Returns: { member_id: { planned_sp, completed_sp, rolling_average } }
    """
    # Load the iteration
    iter_result = await db.execute(
        select(Iteration).where(Iteration.id == iteration_id)
    )
    iteration = iter_result.scalar_one_or_none()
    if not iteration:
        logger.warning(f"Iteration {iteration_id} not found for velocity recording")
        return {}

    # Check if we already recorded velocity for this iteration (idempotent)
    existing_check = await db.execute(
        select(func.count())
        .select_from(VelocityProfile)
        .where(VelocityProfile.iteration_id == iteration_id)
    )
    if (existing_check.scalar() or 0) > 0:
        logger.info(f"Velocity already recorded for iteration {iteration_id}")
        return {}

    # Load team members
    members_result = await db.execute(
        select(TeamMember).where(TeamMember.organization_id == org_id)
    )
    members = list(members_result.scalars().all())
    if not members:
        return {}

    velocity_records: dict[str, dict] = {}

    for member in members:
        # Planned SP: all work items assigned to this member in this iteration
        planned_result = await db.execute(
            select(func.coalesce(func.sum(WorkItem.story_points), 0))
            .where(
                WorkItem.assignee_id == member.id,
                WorkItem.iteration_id == iteration_id,
            )
        )
        planned_sp = float(planned_result.scalar() or 0)

        # Completed SP: only items with DONE/Closed status
        completed_result = await db.execute(
            select(func.coalesce(func.sum(WorkItem.story_points), 0))
            .where(
                WorkItem.assignee_id == member.id,
                WorkItem.iteration_id == iteration_id,
                WorkItem.status.in_(["DONE", "Closed", "CLOSED", "Done"]),
            )
        )
        completed_sp = float(completed_result.scalar() or 0)

        # Skip members with no assignment in this sprint
        if planned_sp == 0 and completed_sp == 0:
            continue

        # Calculate rolling average from historical per-sprint records
        hist_result = await db.execute(
            select(VelocityProfile.completed_sp)
            .where(
                VelocityProfile.team_member_id == member.id,
                VelocityProfile.iteration_id.isnot(None),
            )
            .order_by(VelocityProfile.recorded_at.desc())
            .limit(10)
        )
        past_completions = [float(r[0]) for r in hist_result.all()]
        all_completions = [completed_sp] + past_completions
        rolling_avg = round(sum(all_completions) / len(all_completions), 1)

        # By ticket type breakdown
        type_result = await db.execute(
            select(WorkItem.type, func.sum(WorkItem.story_points))
            .where(
                WorkItem.assignee_id == member.id,
                WorkItem.iteration_id == iteration_id,
                WorkItem.status.in_(["DONE", "Closed", "CLOSED", "Done"]),
            )
            .group_by(WorkItem.type)
        )
        by_type = {
            (r[0] or "story").lower(): float(r[1] or 0)
            for r in type_result.all()
        }

        profile = VelocityProfile(
            id=generate_cuid(),
            team_member_id=member.id,
            iteration_id=iteration_id,
            planned_sp=planned_sp,
            completed_sp=completed_sp,
            rolling_average=rolling_avg,
            by_ticket_type=by_type,
            is_cold_start=len(all_completions) < 3,
        )
        db.add(profile)

        velocity_records[member.id] = {
            "planned_sp": planned_sp,
            "completed_sp": completed_sp,
            "rolling_average": rolling_avg,
            "by_type": by_type,
        }

    await db.flush()

    logger.info(
        f"Per-sprint velocity recorded for iteration {iteration_id}: "
        f"{len(velocity_records)} members"
    )

    return velocity_records

"""
Sprint Failure Analysis Service — classifies sprint failures and generates feed-forward constraints.

Called after a sprint closes when completion rate < 85%.

Classification types:
  OVERCOMMITMENT  — team was assigned more SP than velocity supports
  EXECUTION       — work started but didn't finish (blockers, PR lag, CI)
  DEPENDENCY      — external blockers outside team control
  CAPACITY        — key developer was unavailable/overloaded
  SCOPE_CREEP     — new tickets added mid-sprint
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.base import generate_cuid
from ..models.sprint_plan import SprintPlan, PlanAssignment
from ..models.work_item import WorkItem
from ..models.iteration import Iteration
from ..models.team_member import TeamMember
from ..models.activity import ActivityEvent
from ..models.analytics import VelocityProfile, HealthSignal
from ..models.standup import BlockerFlag, StandupReport
from ..models.repository import PullRequest
from ..models.retrospective import Retrospective
from ..models.sprint_constraint import SprintConstraint
from ..config import settings

logger = logging.getLogger(__name__)


async def analyze_sprint_failure(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    iteration_id: str,
) -> dict[str, Any]:
    """
    Analyze a completed sprint, classify the primary failure mode,
    detect patterns, and generate feed-forward constraints.

    Only called when sprint completion rate < 85%.
    """
    # --- Load iteration ---
    it_result = await db.execute(
        select(Iteration).where(Iteration.id == iteration_id)
    )
    iteration = it_result.scalar_one_or_none()
    if not iteration:
        return {"error": "Iteration not found"}

    # --- Completion stats (scoped to project) ---
    wi_filters = [
        WorkItem.organization_id == org_id,
        WorkItem.iteration_id == iteration_id,
    ]
    if project_id:
        wi_filters.append(WorkItem.imported_project_id == project_id)

    total_result = await db.execute(
        select(
            func.count().label("total"),
            func.coalesce(func.sum(WorkItem.story_points), 0).label("total_sp"),
        )
        .where(*wi_filters)
    )
    total_row = total_result.one()
    total_items = total_row[0]
    total_sp = float(total_row[1])

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
    completion_rate = (done_sp / total_sp * 100) if total_sp > 0 else 100

    if completion_rate >= 85:
        return {"skipped": True, "completionRate": completion_rate}

    # --- Gather evidence ---
    # Blocker history
    blocker_result = await db.execute(
        select(BlockerFlag)
        .join(StandupReport, BlockerFlag.standup_report_id == StandupReport.id)
        .where(StandupReport.organization_id == org_id)
    )
    blockers = list(blocker_result.scalars().all())
    blocker_count = len(blockers)
    unresolved_blockers = len([b for b in blockers if b.status in ("OPEN", "ACKNOWLEDGED", "ESCALATED")])

    # PR review lag
    pr_result = await db.execute(
        select(PullRequest)
        .where(PullRequest.status.in_(["OPEN", "AWAITING_REVIEW", "CHANGES_REQUESTED"]))
    )
    stalled_prs = list(pr_result.scalars().all())
    avg_pr_age_hours = 0
    if stalled_prs:
        now = datetime.now(timezone.utc)
        ages = []
        for pr in stalled_prs:
            created = pr.created_at
            if created and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created:
                ages.append((now - created).total_seconds() / 3600)
        avg_pr_age_hours = round(sum(ages) / len(ages), 1) if ages else 0

    # Developer capacity utilization
    members_result = await db.execute(
        select(TeamMember)
        .where(
            TeamMember.organization_id == org_id,
            TeamMember.role == "developer",
        )
    )
    developers = list(members_result.scalars().all())

    overloaded_devs = []
    for dev in developers:
        dev_wi_filters = [
            WorkItem.assignee_id == dev.id,
            WorkItem.iteration_id == iteration_id,
        ]
        if project_id:
            dev_wi_filters.append(WorkItem.imported_project_id == project_id)
        assigned_result = await db.execute(
            select(func.coalesce(func.sum(WorkItem.story_points), 0))
            .where(*dev_wi_filters)
        )
        assigned_sp = float(assigned_result.scalar() or 0)
        sprint_weeks = max((iteration.end_date - iteration.start_date).days / 7, 1) if iteration.start_date and iteration.end_date else 2
        capacity_sp = (dev.default_capacity * sprint_weeks) / 5.0
        utilization = (assigned_sp / capacity_sp * 100) if capacity_sp > 0 else 0
        if utilization > 90:
            overloaded_devs.append({
                "name": dev.display_name,
                "utilization": round(utilization),
                "assignedSP": assigned_sp,
                "capacitySP": round(capacity_sp, 1),
            })

    # Carry-forward items (items not done in this sprint)
    carry_result = await db.execute(
        select(func.count())
        .select_from(WorkItem)
        .where(
            *wi_filters,
            WorkItem.status.notin_(["DONE", "CLOSED"]),
        )
    )
    carry_forward_count = carry_result.scalar() or 0

    # No-activity items
    no_activity_result = await db.execute(
        select(func.count())
        .select_from(WorkItem)
        .where(
            *wi_filters,
            WorkItem.spillover_risk.in_(["high", "critical"]),
        )
    )
    no_activity_count = no_activity_result.scalar() or 0

    # Velocity check: was team overcommitted?
    plan_result = await db.execute(
        select(SprintPlan)
        .where(
            SprintPlan.organization_id == org_id,
            SprintPlan.iteration_id == iteration_id,
        )
        .order_by(SprintPlan.created_at.desc())
        .limit(1)
    )
    plan = plan_result.scalar_one_or_none()
    planned_sp = plan.total_story_points if plan else total_sp

    vel_result = await db.execute(
        select(VelocityProfile)
        .join(TeamMember, VelocityProfile.team_member_id == TeamMember.id)
        .where(
            TeamMember.organization_id == org_id,
            TeamMember.role == "developer",
        )
    )
    velocity_profiles = list(vel_result.scalars().all())
    team_velocity = sum(vp.rolling_average or vp.completed_sp for vp in velocity_profiles)
    overcommitted = planned_sp > team_velocity * 1.15 if team_velocity > 0 else False

    # --- Build evidence ---
    evidence: list[str] = []

    if no_activity_count > 0:
        evidence.append(f"{no_activity_count} tickets had no activity for 3+ days mid-sprint")
    if avg_pr_age_hours > 24:
        evidence.append(f"Average PR review lag was {avg_pr_age_hours:.0f} hours (threshold: 24h)")
    if overloaded_devs:
        evidence.append(
            f"{len(overloaded_devs)} developer(s) were above 90% capacity from day 1"
        )
    if unresolved_blockers > 0:
        evidence.append(f"{unresolved_blockers} unresolved blockers during the sprint")
    if overcommitted:
        evidence.append(
            f"Sprint was overcommitted: {planned_sp:.0f} SP planned vs {team_velocity:.0f} SP team velocity"
        )
    if carry_forward_count > 0:
        evidence.append(f"{carry_forward_count} items carried forward to next sprint")

    # --- Classify failure ---
    # Use AI if available, otherwise deterministic
    classification = await _classify_failure(
        completion_rate=completion_rate,
        blocker_count=blocker_count,
        unresolved_blockers=unresolved_blockers,
        avg_pr_age_hours=avg_pr_age_hours,
        overloaded_devs=overloaded_devs,
        overcommitted=overcommitted,
        carry_forward_count=carry_forward_count,
        no_activity_count=no_activity_count,
        evidence=evidence,
        db=db,
        org_id=org_id,
    )

    # --- Pattern detection ---
    # Check previous retrospectives for consecutive failures
    prev_retros = await db.execute(
        select(Retrospective)
        .where(
            Retrospective.organization_id == org_id,
            Retrospective.failure_classification.isnot(None),
        )
        .order_by(Retrospective.created_at.desc())
        .limit(5)
    )
    recent_failures = list(prev_retros.scalars().all())
    consecutive_count = 1  # This sprint
    pattern_detected = False

    for retro in recent_failures:
        if retro.failure_classification == classification["type"]:
            consecutive_count += 1
            if consecutive_count >= 2:
                pattern_detected = True
        else:
            break

    # --- Generate feed-forward signals ---
    feed_forward: list[dict] = []

    if overloaded_devs:
        for dev in overloaded_devs:
            feed_forward.append({
                "type": "reduce_capacity",
                "target": dev["name"],
                "adjustment": -15,
                "reason": f"Reduce {dev['name']}'s capacity target by 15%",
            })

    if avg_pr_age_hours > 24:
        feed_forward.append({
            "type": "pr_review_lag_signal",
            "reason": "Added PR review lag as a risk signal for affected tickets",
        })

    if overcommitted:
        feed_forward.append({
            "type": "max_commitment_cap",
            "adjustment": 85,
            "reason": "Max sprint commitment reduced to 85% of team velocity",
        })

    # --- Persist to retrospective ---
    retro_result = await db.execute(
        select(Retrospective)
        .where(
            Retrospective.organization_id == org_id,
            Retrospective.iteration_id == iteration_id,
        )
        .limit(1)
    )
    retro = retro_result.scalar_one_or_none()

    if retro:
        retro.failure_classification = classification["type"]
        retro.failure_evidence = {
            "evidence": evidence,
            "confidence": classification["confidence"],
            "completionRate": completion_rate,
            "totalSP": total_sp,
            "doneSP": done_sp,
            "overloadedDevs": overloaded_devs,
        }
        retro.pattern_detected = pattern_detected
        retro.consecutive_failure_count = consecutive_count
        retro.feed_forward_signals = {
            "signals": [ff["reason"] for ff in feed_forward],
            "details": feed_forward,
        }
    else:
        retro = Retrospective(
            id=generate_cuid(),
            organization_id=org_id,
            iteration_id=iteration_id,
            what_went_well={"items": []},
            what_didnt_go_well={"items": evidence},
            failure_classification=classification["type"],
            failure_evidence={
                "evidence": evidence,
                "confidence": classification["confidence"],
                "completionRate": completion_rate,
                "totalSP": total_sp,
                "doneSP": done_sp,
                "overloadedDevs": overloaded_devs,
            },
            pattern_detected=pattern_detected,
            consecutive_failure_count=consecutive_count,
            feed_forward_signals={
                "signals": [ff["reason"] for ff in feed_forward],
                "details": feed_forward,
            },
            is_draft=False,
            finalized_at=datetime.now(timezone.utc),
        )
        db.add(retro)

    # --- Write feed-forward constraints ---
    if feed_forward:
        for ff in feed_forward:
            constraint = SprintConstraint(
                id=generate_cuid(),
                organization_id=org_id,
                project_id=project_id,
                source="failure_analysis",
                constraint_data=ff,
                expires_after_sprints=3,
                sprints_applied=0,
            )
            db.add(constraint)

    await db.flush()

    logger.info(
        "Failure analysis for iteration %s: %s (%.0f%% confidence), "
        "pattern=%s, consecutive=%d, %d feed-forward signals",
        iteration_id, classification["type"], classification["confidence"],
        pattern_detected, consecutive_count, len(feed_forward),
    )

    return {
        "classification": classification["type"],
        "confidence": classification["confidence"],
        "evidence": evidence,
        "patternDetected": pattern_detected,
        "consecutiveFailureCount": consecutive_count,
        "feedForward": [ff["reason"] for ff in feed_forward],
        "completionRate": completion_rate,
    }


async def _classify_failure(
    completion_rate: float,
    blocker_count: int,
    unresolved_blockers: int,
    avg_pr_age_hours: float,
    overloaded_devs: list[dict],
    overcommitted: bool,
    carry_forward_count: int,
    no_activity_count: int,
    evidence: list[str],
    db: AsyncSession,
    org_id: str,
) -> dict[str, Any]:
    """Classify the primary failure type. Uses AI if available, else deterministic."""

    # Try AI classification
    if settings.azure_ai_api_key and settings.azure_ai_endpoint:
        try:
            return await _classify_with_ai(
                completion_rate, evidence, db, org_id
            )
        except Exception as e:
            logger.warning(f"AI classification failed, using deterministic: {e}")

    # Deterministic classification
    scores = {
        "OVERCOMMITMENT": 0.0,
        "EXECUTION": 0.0,
        "DEPENDENCY": 0.0,
        "CAPACITY": 0.0,
        "SCOPE_CREEP": 0.0,
    }

    if overcommitted:
        scores["OVERCOMMITMENT"] += 40
    if no_activity_count > 2:
        scores["EXECUTION"] += 30
    if avg_pr_age_hours > 24:
        scores["EXECUTION"] += 20
    if unresolved_blockers > 2:
        scores["DEPENDENCY"] += 35
    if overloaded_devs:
        scores["CAPACITY"] += 25 + len(overloaded_devs) * 5
    if blocker_count > 0:
        scores["DEPENDENCY"] += blocker_count * 5

    # Normalize
    total = sum(scores.values()) or 1
    for k in scores:
        scores[k] = scores[k] / total

    primary = max(scores, key=scores.get)  # type: ignore
    confidence = round(scores[primary] * 100)

    return {"type": primary, "confidence": confidence}


async def _classify_with_ai(
    completion_rate: float,
    evidence: list[str],
    db: AsyncSession,
    org_id: str,
) -> dict[str, Any]:
    """Use the LLM to classify the failure type."""
    import httpx

    prompt = f"""You are a sprint failure analyst. Given the following sprint data, classify the PRIMARY failure type.

Completion rate: {completion_rate:.1f}%
Evidence:
{chr(10).join(f"- {e}" for e in evidence)}

Classify into exactly ONE of:
- OVERCOMMITMENT: team was assigned more SP than velocity supports
- EXECUTION: work started but didn't finish (blockers, PR lag, CI failures)
- DEPENDENCY: external blockers outside team control
- CAPACITY: key developer was unavailable/overloaded
- SCOPE_CREEP: new tickets added mid-sprint

Return ONLY valid JSON:
{{"type": "EXECUTION", "confidence": 72}}
"""

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.azure_ai_endpoint}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "api-key": settings.azure_ai_api_key,
            },
            json={
                "model": settings.azure_ai_model or "grok-4-fast-reasoning",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 256,
                "temperature": 0.1,
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        # Parse JSON from response
        import re
        match = re.search(r"\{[^}]+\}", content)
        if match:
            result = json.loads(match.group())
            return {
                "type": result.get("type", "EXECUTION"),
                "confidence": result.get("confidence", 50),
            }

    return {"type": "EXECUTION", "confidence": 50}

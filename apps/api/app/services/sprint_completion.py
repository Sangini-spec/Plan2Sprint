"""
Automatic Sprint Completion Service — real-time tracking that detects sprint
completion from actual work-item status, not just calendar dates.

Two detection triggers (checked on every sync / dashboard load / sprint fetch):

  1. STATUS-BASED (primary): If ALL work items assigned to a sprint have status
     "Done"/"Closed" → the sprint is complete immediately, even before the end
     date.  This is real-time tracking — the platform reacts to actual progress.

  2. DATE-BASED (secondary): If the sprint end date has passed and there are
     still incomplete items → auto-complete with spillover/failure analysis.
     The end date is primarily used for *forecasting* ("will we finish on time?"),
     but also acts as a hard deadline that closes the sprint.

Pipeline for each completed sprint:
  1. Mark iteration.state = "completed"
  2. Calculate completion stats per team member
  3. Record per-sprint VelocityProfile entries
  4. Identify and auto-move spillover items to next iteration
  5. Trigger retrospective analysis (failure or success)
  6. Evaluate health signals
  7. Broadcast "sprint_completed" WebSocket event
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.base import generate_cuid
from ..models.iteration import Iteration
from ..models.work_item import WorkItem
from ..models.team_member import TeamMember
from ..models.in_app_notification import InAppNotification
from ..models.sprint_plan import SprintPlan
from ..models.retrospective import Retrospective

logger = logging.getLogger(__name__)


async def check_and_complete_sprints(
    db: AsyncSession,
    org_id: str,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Hotfix 82 — retrospective trigger driven by AI Sprint Plan timeline.

    Old behaviour (Iteration.state == "active" + end_date or all-items-done)
    was tied to ADO/Jira sprint state, which never flipped to "active" if
    the team worked exclusively in Plan2Sprint. Result: AI plans came and
    went without retros. Sangini's call: replace the trigger with the AI
    plan's own ``estimated_end_date``.

    New behaviour:
      - Find SprintPlans in APPROVED or SYNCED status for this org.
      - Whose ``estimated_end_date`` is in the past.
      - With no Retrospective yet for the same ``iteration_id``.
      - For each: run the full completion pipeline on the linked
        Iteration. The pipeline already handles failure-vs-success retro,
        spillover, velocity, notifications, etc. — we just changed who
        decides "this sprint is done".

    Returns a list of completion summaries. Idempotent: deduplicated by
    iteration_id (one retro per iteration even if multiple superseding
    plans exist for it).
    """
    now = datetime.now(timezone.utc)

    # ── Fetch APPROVED/SYNCED sprint plans whose estimated end is past ──
    plan_query = (
        select(SprintPlan)
        .where(
            SprintPlan.organization_id == org_id,
            SprintPlan.status.in_(["APPROVED", "SYNCED"]),
            SprintPlan.estimated_end_date.isnot(None),
            SprintPlan.estimated_end_date < now,
        )
        .order_by(SprintPlan.estimated_end_date.asc())
    )
    if project_id:
        plan_query = plan_query.where(SprintPlan.project_id == project_id)

    plans_result = await db.execute(plan_query)
    candidate_plans = list(plans_result.scalars().all())

    if not candidate_plans:
        return []

    # ── Drop plans whose iteration already has a retro (dedup) ──
    iteration_ids = {p.iteration_id for p in candidate_plans if p.iteration_id}
    if not iteration_ids:
        return []
    existing_retro_q = await db.execute(
        select(Retrospective.iteration_id).where(
            Retrospective.organization_id == org_id,
            Retrospective.iteration_id.in_(iteration_ids),
        )
    )
    iterations_with_retros = {row[0] for row in existing_retro_q.all() if row[0]}

    seen_iterations: set[str] = set()
    completed_summaries: list[dict[str, Any]] = []

    for plan in candidate_plans:
        if not plan.iteration_id or plan.iteration_id in iterations_with_retros:
            continue
        if plan.iteration_id in seen_iterations:
            continue  # multiple plans for same iteration — only fire once
        seen_iterations.add(plan.iteration_id)

        # Fetch the linked Iteration row (we still want to mark it
        # ``state = completed`` and the existing pipeline expects the
        # Iteration object).
        iter_q = await db.execute(
            select(Iteration).where(Iteration.id == plan.iteration_id)
        )
        iteration = iter_q.scalar_one_or_none()
        if not iteration:
            logger.warning(
                f"SprintPlan {plan.id} references missing iteration {plan.iteration_id}; skipping"
            )
            continue
        if iteration.state == "completed":
            # Iteration was already completed by a prior pass (or via the
            # old iteration-state path) but no retro exists yet — let the
            # pipeline run anyway so the retro lands. ``_complete_single_sprint``
            # handles re-completion idempotently.
            pass

        logger.info(
            f"AI plan timeline trigger: SprintPlan {plan.id} "
            f"(end={plan.estimated_end_date}, status={plan.status}) "
            f"→ generating retro for iteration '{iteration.name}'"
        )

        try:
            summary = await _complete_single_sprint(
                db=db,
                org_id=org_id,
                project_id=plan.project_id or iteration.imported_project_id or project_id,
                iteration=iteration,
                trigger="ai_plan_end_date_passed",
            )
            summary["sprintPlanId"] = plan.id
            completed_summaries.append(summary)
        except Exception as e:
            logger.exception(
                f"Failed to generate AI-plan-driven retro for plan {plan.id} "
                f"(iteration {plan.iteration_id}): {e}"
            )

    return completed_summaries


async def force_complete_sprint(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    iteration_id: str,
) -> dict[str, Any]:
    """
    Force-complete a sprint regardless of end date.
    Used for testing/demo purposes.
    """
    result = await db.execute(
        select(Iteration).where(
            Iteration.id == iteration_id,
            Iteration.organization_id == org_id,
        )
    )
    iteration = result.scalar_one_or_none()
    if not iteration:
        return {"error": "Iteration not found"}

    if iteration.state == "completed":
        return {"error": "Sprint is already completed", "iterationId": iteration_id}

    return await _complete_single_sprint(
        db=db,
        org_id=org_id,
        project_id=project_id,
        iteration=iteration,
    )


async def _complete_single_sprint(
    db: AsyncSession,
    org_id: str,
    project_id: str | None,
    iteration: Iteration,
    trigger: str = "manual",
) -> dict[str, Any]:
    """
    Run the full completion pipeline for a single sprint.

    trigger values:
      - "all_items_done"  — every item in the sprint is Done (status-based)
      - "end_date_passed" — sprint end date has passed (date-based)
      - "manual"          — force-completed via API (testing/demo)
    """
    iteration_id = iteration.id
    iteration_name = iteration.name

    trigger_label = {
        "all_items_done": "all items completed",
        "end_date_passed": f"end date passed ({iteration.end_date})",
        "ai_plan_end_date_passed": "AI sprint plan reached its estimated end date",
        "manual": "manually triggered",
    }.get(trigger, trigger)

    logger.info(
        f"Auto-completing sprint '{iteration_name}' (id={iteration_id}, "
        f"trigger={trigger_label})"
    )

    # ---- Step 1: Mark as completed ----
    iteration.state = "completed"
    await db.flush()

    # ---- Step 2: Calculate completion stats ----
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
        ).where(*wi_filters)
    )
    total_row = total_result.one()
    total_items = total_row[0]
    total_sp = float(total_row[1])

    done_result = await db.execute(
        select(
            func.count().label("done"),
            func.coalesce(func.sum(WorkItem.story_points), 0).label("done_sp"),
        ).where(
            *wi_filters,
            WorkItem.status.in_(["DONE", "Closed", "CLOSED", "Done"]),
        )
    )
    done_row = done_result.one()
    done_items = done_row[0]
    done_sp = float(done_row[1])

    completion_rate = round((done_sp / total_sp * 100), 1) if total_sp > 0 else 100.0

    logger.info(
        f"Sprint '{iteration_name}': {completion_rate:.1f}% complete "
        f"({done_sp:.0f}/{total_sp:.0f} SP, {done_items}/{total_items} items)"
    )

    # ---- Step 3: Record per-sprint velocity ----
    try:
        from .velocity_calculator import record_sprint_velocity
        await record_sprint_velocity(db, org_id, iteration_id)
    except Exception as e:
        logger.warning(f"Velocity recording failed (non-fatal): {e}")

    # ---- Step 4: Identify spillover items ----
    spillover_result = await db.execute(
        select(WorkItem).where(
            *wi_filters,
            WorkItem.status.notin_(["DONE", "Closed", "CLOSED", "Done"]),
        )
    )
    spillover_items = list(spillover_result.scalars().all())
    spillover_count = len(spillover_items)
    spillover_sp = sum(wi.story_points or 0 for wi in spillover_items)

    # ---- Step 5: Auto-move spillovers to next iteration ----
    next_iteration_name = None
    if spillover_items:
        next_iter_result = await db.execute(
            select(Iteration).where(
                Iteration.organization_id == org_id,
                Iteration.imported_project_id == project_id,
                Iteration.start_date > iteration.end_date,
                Iteration.state.in_(["active", "future", "new"]),
            ).order_by(Iteration.start_date.asc()).limit(1)
        )
        next_iteration = next_iter_result.scalar_one_or_none()

        if next_iteration:
            next_iteration_name = next_iteration.name
            for wi in spillover_items:
                wi.iteration_id = next_iteration.id
                wi.spillover_risk = "carried_forward"
                wi.spillover_reason = (
                    f"Auto-moved from {iteration_name} "
                    f"(sprint completed at {completion_rate:.0f}%)"
                )
            await db.flush()
            logger.info(
                f"Moved {spillover_count} spillover items ({spillover_sp:.0f} SP) "
                f"to '{next_iteration.name}'"
            )
        else:
            logger.warning(
                f"No next iteration found — {spillover_count} spillover items remain unassigned"
            )

    # ---- Step 6: Trigger retrospective analysis ----
    retro_generated = False
    retro_type = None
    try:
        if completion_rate < 85:
            from .failure_analysis import analyze_sprint_failure
            retro_result = await analyze_sprint_failure(
                db, org_id, project_id or "", iteration_id
            )
            retro_generated = not retro_result.get("error")
            retro_type = "failure_analysis"
            logger.info(
                f"Failure analysis: {retro_result.get('classification', 'N/A')} "
                f"({retro_result.get('confidence', 0)}% confidence)"
            )
        else:
            from .failure_analysis import generate_success_retrospective
            retro_result = await generate_success_retrospective(
                db, org_id, project_id or "", iteration_id,
                completion_rate=completion_rate,
                done_sp=done_sp,
                total_sp=total_sp,
                done_items=done_items,
                total_items=total_items,
            )
            retro_generated = not retro_result.get("error")
            retro_type = "success"
    except Exception as e:
        logger.warning(f"Retrospective generation failed (non-fatal): {e}")

    # ---- Step 7: Evaluate health signals ----
    try:
        from .activity_engine import evaluate_all_signals
        await evaluate_all_signals(db, org_id)
    except Exception as e:
        logger.warning(f"Health signal evaluation failed (non-fatal): {e}")

    # ---- Step 8: Create in-app notification ----
    try:
        spillover_text = (
            f", {spillover_count} items spilled over"
            + (f" to {next_iteration_name}" if next_iteration_name else "")
            if spillover_count > 0
            else ""
        )

        if trigger == "all_items_done":
            title = f"Sprint '{iteration_name}' completed — all items done!"
        elif trigger == "end_date_passed":
            title = f"Sprint '{iteration_name}' ended — deadline reached"
        elif trigger == "ai_plan_end_date_passed":
            title = f"Sprint '{iteration_name}' wrapped — AI plan timeline ended"
        else:
            title = f"Sprint '{iteration_name}' completed"

        notification = InAppNotification(
            id=generate_cuid(),
            organization_id=org_id,
            recipient_email="__all_po__",  # All POs in the org
            notification_type="sprint_completed",
            title=title,
            body=(
                f"{completion_rate:.0f}% completion rate "
                f"({done_sp:.0f}/{total_sp:.0f} SP){spillover_text}. "
                f"Retrospective {'generated' if retro_generated else 'pending'}."
            ),
            read=False,
        )
        db.add(notification)
    except Exception as e:
        logger.warning(f"Notification creation failed (non-fatal): {e}")

    # ---- Step 9: Broadcast WebSocket event ----
    try:
        from .ws_manager import ws_manager
        await ws_manager.broadcast(org_id, {
            "type": "sprint_completed",
            "data": {
                "iterationId": iteration_id,
                "iterationName": iteration_name,
                "completionRate": completion_rate,
                "doneSP": done_sp,
                "totalSP": total_sp,
                "doneItems": done_items,
                "totalItems": total_items,
                "spilloverCount": spillover_count,
                "spilloverSP": spillover_sp,
                "nextIteration": next_iteration_name,
                "retroGenerated": retro_generated,
                "retroType": retro_type,
                "trigger": trigger,
            },
        })
    except Exception as e:
        logger.warning(f"WebSocket broadcast failed (non-fatal): {e}")

    await db.commit()

    summary = {
        "iterationId": iteration_id,
        "iterationName": iteration_name,
        "completionRate": completion_rate,
        "doneSP": done_sp,
        "totalSP": total_sp,
        "doneItems": done_items,
        "totalItems": total_items,
        "spilloverCount": spillover_count,
        "spilloverSP": spillover_sp,
        "nextIteration": next_iteration_name,
        "retroGenerated": retro_generated,
        "retroType": retro_type,
        "trigger": trigger,
    }

    logger.info(
        f"Sprint '{iteration_name}' auto-completed: "
        f"{completion_rate:.0f}% done, {spillover_count} spillovers, "
        f"retro={'yes' if retro_generated else 'no'}"
    )

    return summary

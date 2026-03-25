"""
GET|POST|PATCH /api/sprints
Sprint overview, plan generation trigger, and plan update.

GET  /api/sprints            — Sprint overview + latest plan for selected project
GET  /api/sprints/plan       — Full plan details with assignments
GET  /api/sprints/forecast   — Sprint forecast (success probability + spillover risk)
POST /api/sprints            — Generate (optimize) a new sprint plan
POST /api/sprints/forecast/refresh — Refresh forecast calculations
PATCH /api/sprints           — Update plan status (approve/reject)
"""

import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models import Iteration, SprintPlan, WorkItem, TeamMember
from ..models.sprint_plan import PlanAssignment
from ..services.ws_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/sprints — Sprint overview for the selected project
# ---------------------------------------------------------------------------

@router.get("/sprints")
async def get_sprint_overview(
    projectId: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")

    # ── Auto-complete expired sprints (date-based detection) ──
    try:
        from ..services.sprint_completion import check_and_complete_sprints
        completed = await check_and_complete_sprints(db, org_id, projectId)
        if completed:
            logger.info(
                f"Auto-completed {len(completed)} sprint(s) on GET /api/sprints: "
                + ", ".join(c["iterationName"] for c in completed)
            )
    except Exception as e:
        logger.warning(f"Auto-completion check failed (non-fatal): {e}")

    # Get the active (or most recent) iteration, scoped to project if provided
    iter_query = select(Iteration).where(Iteration.organization_id == org_id)
    if projectId:
        iter_query = iter_query.where(Iteration.imported_project_id == projectId)
    iter_query = iter_query.order_by(Iteration.start_date.desc()).limit(1)
    iter_result = await db.execute(iter_query)
    iteration = iter_result.scalar_one_or_none()

    # Fallback: if no project-scoped iteration, try org-wide
    if not iteration and projectId:
        iter_query_fallback = (
            select(Iteration)
            .where(Iteration.organization_id == org_id)
            .order_by(Iteration.start_date.desc())
            .limit(1)
        )
        iter_result = await db.execute(iter_query_fallback)
        iteration = iter_result.scalar_one_or_none()

    if not iteration:
        return {
            "iteration": None,
            "health": "GREY",
            "completionPct": 0,
            "daysRemaining": 0,
            "plan": None,
        }

    # Calculate completion % from work items (scoped to project)
    wi_filters = [WorkItem.iteration_id == iteration.id]
    if projectId:
        wi_filters.append(WorkItem.imported_project_id == projectId)

    total_q = select(func.count()).select_from(WorkItem).where(*wi_filters)
    done_q = select(func.count()).select_from(WorkItem).where(*wi_filters, WorkItem.status == "DONE")
    total_res = await db.execute(total_q)
    done_res = await db.execute(done_q)
    total_count = total_res.scalar() or 1
    done_count = done_res.scalar() or 0
    completion_pct = int((done_count / total_count) * 100)

    # Days remaining
    now = datetime.utcnow()
    end = iteration.end_date
    if hasattr(end, 'tzinfo') and end.tzinfo:
        end = end.replace(tzinfo=None)
    days_remaining = max(0, (end - now).days)

    # Sprint health based on pacing
    sprint_days = max(1, (iteration.end_date.replace(tzinfo=None) - iteration.start_date.replace(tzinfo=None)).days)
    expected_pct = max(1, 100 - int((days_remaining / max(sprint_days, 1)) * 100))
    if completion_pct >= expected_pct * 0.8:
        health = "GREEN"
    elif completion_pct >= expected_pct * 0.5:
        health = "AMBER"
    else:
        health = "RED"

    # Get latest non-rejected sprint plan, scoped to project if provided
    # Skip REJECTED plans so the previous good plan surfaces after rejection
    plan_query = (
        select(SprintPlan)
        .where(
            SprintPlan.organization_id == org_id,
            SprintPlan.status != "REJECTED",
        )
    )
    # Prefer project-scoped plan; fall back to iteration-scoped
    if projectId:
        plan_query = plan_query.where(SprintPlan.project_id == projectId)
    else:
        plan_query = plan_query.where(SprintPlan.iteration_id == iteration.id)
    plan_query = plan_query.order_by(SprintPlan.created_at.desc()).limit(1)
    plan_result = await db.execute(plan_query)
    plan = plan_result.scalar_one_or_none()

    plan_data = None
    if plan:
        # Normalize confidence_score: must be 0-1 float.
        # Old seed data may store as percentage (e.g. 82 instead of 0.82).
        cs = plan.confidence_score
        if cs is not None and cs > 1.0:
            cs = cs / 100.0

        plan_data = {
            "id": plan.id,
            "status": plan.status,
            "confidenceScore": cs,
            "totalStoryPoints": plan.total_story_points,
            "riskSummary": plan.risk_summary,
            "overallRationale": plan.overall_rationale,
            "goalAttainmentConfidence": plan.goal_attainment_confidence,
            "aiModelUsed": plan.ai_model_used,
            "tool": plan.tool,
            "approvedAt": plan.approved_at.isoformat() if plan.approved_at else None,
            "syncedAt": plan.synced_at.isoformat() if plan.synced_at else None,
            "createdAt": plan.created_at.isoformat() if plan.created_at else None,
            "unplannedItems": plan.unplanned_items,
            "estimatedSprints": plan.estimated_sprints,
            "estimatedEndDate": plan.estimated_end_date.isoformat() if plan.estimated_end_date else None,
            "successProbability": plan.success_probability,
            "spilloverRiskSP": plan.spillover_risk_sp,
            "forecastUpdatedAt": plan.forecast_updated_at.isoformat() if plan.forecast_updated_at else None,
            "estimatedWeeksTotal": plan.estimated_weeks_total,
            "projectCompletionSummary": plan.project_completion_summary,
            "capacityRecommendations": plan.capacity_recommendations,
        }

    return {
        "iteration": {
            "id": iteration.id,
            "name": iteration.name,
            "goal": iteration.goal,
            "startDate": iteration.start_date.isoformat(),
            "endDate": iteration.end_date.isoformat(),
            "state": iteration.state,
        },
        "health": health,
        "completionPct": completion_pct,
        "daysRemaining": days_remaining,
        "plan": plan_data,
    }


# ---------------------------------------------------------------------------
# GET /api/sprints/plan — Full plan details with assignments
# ---------------------------------------------------------------------------

@router.get("/sprints/plan")
async def get_plan_details(
    planId: str | None = Query(None),
    projectId: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a full plan with all assignments, work items, and team members."""
    org_id = current_user.get("organization_id", "demo-org")

    # Find the plan — skip REJECTED plans so previous good plan surfaces
    if planId:
        plan_q = select(SprintPlan).where(SprintPlan.id == planId)
    elif projectId:
        # Latest non-rejected plan for this project
        plan_q = (
            select(SprintPlan)
            .where(
                SprintPlan.organization_id == org_id,
                SprintPlan.project_id == projectId,
                SprintPlan.status != "REJECTED",
            )
            .order_by(SprintPlan.created_at.desc())
            .limit(1)
        )
    else:
        # Default: latest non-rejected plan for this org
        plan_q = (
            select(SprintPlan)
            .where(
                SprintPlan.organization_id == org_id,
                SprintPlan.status != "REJECTED",
            )
            .order_by(SprintPlan.created_at.desc())
            .limit(1)
        )

    plan_result = await db.execute(plan_q)
    plan = plan_result.scalar_one_or_none()

    if not plan:
        return {"plan": None, "assignments": [], "workItems": [], "teamMembers": []}

    # Load assignments
    assign_q = select(PlanAssignment).where(PlanAssignment.sprint_plan_id == plan.id)
    assign_result = await db.execute(assign_q)
    assignments = list(assign_result.scalars().all())

    # Load referenced work items and team members
    wi_ids = [a.work_item_id for a in assignments]
    tm_ids = list(set(a.team_member_id for a in assignments))

    work_items = []
    if wi_ids:
        wi_result = await db.execute(
            select(WorkItem).where(WorkItem.id.in_(wi_ids))
        )
        work_items = list(wi_result.scalars().all())

    team_members = []
    if tm_ids:
        tm_result = await db.execute(
            select(TeamMember).where(TeamMember.id.in_(tm_ids))
        )
        team_members = list(tm_result.scalars().all())

    # Load iteration
    iter_result = await db.execute(
        select(Iteration).where(Iteration.id == plan.iteration_id)
    )
    iteration = iter_result.scalar_one_or_none()

    # Calculate per-sprint details (date ranges, SP, item counts) — skip empty sprints
    sprint_details = []
    if iteration and plan.estimated_sprints:
        start = iteration.start_date
        if hasattr(start, 'tzinfo') and start.tzinfo:
            start = start.replace(tzinfo=None)
        sprint_days = max(1, (iteration.end_date.replace(tzinfo=None) - start).days) if iteration.end_date else 14
        for sn in range(1, (plan.estimated_sprints or 1) + 1):
            sn_assignments = [a for a in assignments if (a.sprint_number or 1) == sn]
            if not sn_assignments:
                continue  # Skip empty sprints
            sn_start = start + timedelta(days=sprint_days * (sn - 1))
            sn_end = start + timedelta(days=sprint_days * sn)
            sprint_details.append({
                "sprintNumber": sn,
                "startDate": sn_start.isoformat(),
                "endDate": sn_end.isoformat(),
                "totalSP": sum(a.story_points or 0 for a in sn_assignments),
                "itemCount": len(sn_assignments),
            })

    # Normalize confidence scores (old seed data may store as %)
    plan_cs = plan.confidence_score
    if plan_cs is not None and plan_cs > 1.0:
        plan_cs = plan_cs / 100.0

    def _norm_cs(val: float) -> float:
        return val / 100.0 if val > 1.0 else val

    return {
        "plan": {
            "id": plan.id,
            "organizationId": plan.organization_id,
            "projectId": plan.project_id,
            "iterationId": plan.iteration_id,
            "iterationName": iteration.name if iteration else None,
            "status": plan.status,
            "confidenceScore": plan_cs,
            "riskSummary": plan.risk_summary,
            "overallRationale": plan.overall_rationale,
            "goalAttainmentConfidence": plan.goal_attainment_confidence,
            "totalStoryPoints": plan.total_story_points,
            "unplannedItems": plan.unplanned_items,
            "aiModelUsed": plan.ai_model_used,
            "tool": plan.tool,
            "humanEdits": plan.human_edits,
            "rejectionFeedback": plan.rejection_feedback,
            "approvedById": plan.approved_by_id,
            "approvedAt": plan.approved_at.isoformat() if plan.approved_at else None,
            "syncedAt": plan.synced_at.isoformat() if plan.synced_at else None,
            "undoAvailableUntil": plan.undo_available_until.isoformat() if plan.undo_available_until else None,
            "createdAt": plan.created_at.isoformat() if plan.created_at else None,
            "estimatedSprints": plan.estimated_sprints,
            "estimatedEndDate": plan.estimated_end_date.isoformat() if plan.estimated_end_date else None,
            "successProbability": plan.success_probability,
            "spilloverRiskSP": plan.spillover_risk_sp,
            "forecastUpdatedAt": plan.forecast_updated_at.isoformat() if plan.forecast_updated_at else None,
            "estimatedWeeksTotal": plan.estimated_weeks_total,
            "projectCompletionSummary": plan.project_completion_summary,
            "capacityRecommendations": plan.capacity_recommendations,
        },
        "assignments": [
            {
                "id": a.id,
                "sprintPlanId": a.sprint_plan_id,
                "workItemId": a.work_item_id,
                "teamMemberId": a.team_member_id,
                "storyPoints": a.story_points,
                "confidenceScore": _norm_cs(a.confidence_score),
                "rationale": a.rationale,
                "riskFlags": a.risk_flags or [],
                "skillMatch": a.skill_match,
                "isHumanEdited": a.is_human_edited,
                "sprintNumber": a.sprint_number or 1,
                "suggestedPriority": a.suggested_priority,
            }
            for a in assignments
        ],
        "workItems": [
            {
                "id": wi.id,
                "externalId": wi.external_id,
                "title": wi.title,
                "status": wi.status,
                "storyPoints": wi.story_points,
                "priority": wi.priority,
                "type": wi.type,
                "labels": wi.labels or [],
            }
            for wi in work_items
        ],
        "teamMembers": [
            {
                "id": tm.id,
                "displayName": tm.display_name,
                "email": tm.email,
                "avatarUrl": tm.avatar_url,
                "skillTags": tm.skill_tags or [],
                "defaultCapacity": tm.default_capacity,
            }
            for tm in team_members
        ],
        "sprintDetails": sprint_details,
    }


# ---------------------------------------------------------------------------
# POST /api/sprints — Generate (optimize) sprint plan
# ---------------------------------------------------------------------------

@router.post("/sprints")
async def generate_sprint_plan_endpoint(
    body: dict | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a new AI sprint plan for the selected project.

    Pipeline:
      1. Refresh data from ADO (fetch iterations, work items, team members)
      2. Calculate velocity profiles
      3. Generate plan via Claude AI (falls back to deterministic optimizer)

    Body:
    {
        "projectId": "cuid-of-project",
        "iterationId": "optional-iteration-id",
        "feedback": "optional-rejection-feedback-for-regen"
    }
    """
    org_id = current_user.get("organization_id", "demo-org")
    body = body or {}

    project_id = body.get("projectId")
    iteration_id = body.get("iterationId")
    feedback = body.get("feedback")

    # Append timestamp to feedback to ensure AI produces a fresh plan on each regeneration
    if feedback:
        feedback = f"{feedback}\n[Regeneration requested at {datetime.now(timezone.utc).isoformat()}]"
    logger.info(f"Sprint generation requested for project={project_id}, has_feedback={bool(feedback)}")

    if not project_id:
        raise HTTPException(status_code=400, detail="projectId is required")

    # Step 1: Refresh data from source tool before planning
    from ..models.imported_project import ImportedProject as IP
    proj_result = await db.execute(
        select(IP).where(IP.id == project_id, IP.organization_id == org_id)
    )
    project_record = proj_result.scalar_one_or_none()
    source_tool = (project_record.source_tool or "ado").lower() if project_record else "ado"

    if source_tool == "ado":
        try:
            from ..services.ado_fetch import fetch_sprint_context
            logger.info(f"Refreshing ADO data for project {project_id} before plan generation")
            sprint_ctx = await fetch_sprint_context(db, org_id, project_id)
            logger.info(
                f"ADO refresh complete: {len(sprint_ctx.team_members)} members, "
                f"{len(sprint_ctx.current_sprint_items)} sprint items, "
                f"{len(sprint_ctx.backlog_items)} backlog items"
            )
        except Exception as e:
            logger.warning(f"ADO data refresh failed (proceeding with DB data): {e}")
    else:
        logger.info(f"Skipping ADO fetch for {source_tool} project {project_id} — using synced DB data")

    # Step 2: Generate plan via AI (falls back to deterministic if no API key)
    from ..services.ai_sprint_generator import generate_sprint_plan_ai

    try:
        result = await generate_sprint_plan_ai(
            db=db,
            org_id=org_id,
            project_id=project_id,
            iteration_id=iteration_id,
            feedback=feedback,
        )
    except Exception as e:
        logger.exception(f"Sprint generation crashed for project {project_id}")
        raise HTTPException(status_code=500, detail=f"Sprint generation failed: {str(e)[:300]}")

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Broadcast plan generation event (non-fatal)
    try:
        await ws_manager.broadcast(org_id, {
            "type": "sprint_plan_generated",
            "data": {
                "planId": result["planId"],
                "iterationName": result.get("iterationName"),
                "assignmentCount": result.get("assignmentCount", 0),
                "totalStoryPoints": result.get("totalStoryPoints", 0),
                "confidenceScore": result.get("confidenceScore", 0),
            },
        })
    except Exception as e:
        logger.warning(f"WS broadcast failed (non-fatal): {e}")

    # Ensure all values are JSON-serializable
    safe_result = {}
    for k, v in result.items():
        if hasattr(v, 'isoformat'):
            safe_result[k] = v.isoformat()
        else:
            safe_result[k] = v

    return {
        "ok": True,
        **safe_result,
    }


# ---------------------------------------------------------------------------
# GET /api/sprints/forecast — Sprint forecast data
# ---------------------------------------------------------------------------

@router.get("/sprints/forecast")
async def get_sprint_forecast(
    projectId: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return success probability, spillover risk items, and rebalancing signal."""
    org_id = current_user.get("organization_id", "demo-org")

    from ..services.sprint_forecast import refresh_forecast

    result = await refresh_forecast(db, org_id, projectId or "")
    await db.commit()

    # Determine if rebalancing is recommended
    success_prob = result.get("successProbability")
    spillover_sp = result.get("totalSpilloverSP", 0)
    total_sp = result.get("totalSP", 0)
    spillover_items = result.get("spilloverItems", [])

    rebalancing_recommended = False
    rebalancing_reasons: list[str] = []

    if success_prob is not None and success_prob < 65:
        rebalancing_recommended = True
        rebalancing_reasons.append(f"Success probability is {success_prob}% (below 65% threshold)")

    critical_items = [i for i in spillover_items if i.get("spilloverRisk") == "critical"]
    if critical_items:
        rebalancing_recommended = True
        rebalancing_reasons.append(f"{len(critical_items)} ticket(s) at critical spillover risk")

    if total_sp > 0 and spillover_sp > total_sp * 0.2:
        rebalancing_recommended = True
        rebalancing_reasons.append(f"{spillover_sp} SP at risk (>{round(total_sp*0.2)} SP threshold)")

    return {
        **result,
        "rebalancingRecommended": rebalancing_recommended,
        "rebalancingReasons": rebalancing_reasons,
    }


# ---------------------------------------------------------------------------
# POST /api/sprints/forecast/refresh — Force refresh forecast
# ---------------------------------------------------------------------------

@router.post("/sprints/forecast/refresh")
async def refresh_sprint_forecast(
    body: dict | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Force refresh forecast calculations."""
    org_id = current_user.get("organization_id", "demo-org")
    body = body or {}
    project_id = body.get("projectId", "")

    from ..services.sprint_forecast import refresh_forecast

    result = await refresh_forecast(db, org_id, project_id)
    await db.commit()

    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# PATCH /api/sprints — Update sprint plan (approve / reject)
# ---------------------------------------------------------------------------

@router.patch("/sprints")
async def update_sprint_plan(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan_id = body.get("planId")
    org_id = current_user.get("organization_id", "demo-org")
    user_id = current_user.get("sub", current_user.get("id", "unknown"))

    if not plan_id:
        raise HTTPException(status_code=400, detail="planId is required")

    plan_query = select(SprintPlan).where(SprintPlan.id == plan_id)
    result = await db.execute(plan_query)
    plan = result.scalar_one_or_none()

    if not plan:
        raise HTTPException(status_code=404, detail="Sprint plan not found")

    old_status = plan.status
    new_status = body.get("status")

    if new_status:
        plan.status = new_status

    if "rejectionFeedback" in body:
        plan.rejection_feedback = body["rejectionFeedback"]

    # Set approval fields
    if new_status == "APPROVED":
        plan.approved_by_id = user_id
        plan.approved_at = datetime.now(timezone.utc)
        plan.undo_available_until = datetime.now(timezone.utc) + timedelta(minutes=60)

    await db.commit()

    # ── Trigger batch write-back on approval ──
    # Detects tool type (from plan or connection) and calls the right service.
    # Writes back ALL assignments — no item-count limit.
    if new_status == "APPROVED":
        try:
            # Determine tool type from the plan or the active connection
            tool = (plan.tool or "").lower()
            if not tool:
                # Fallback: check which tool connection exists for this org
                from ..models.tool_connection import ToolConnection
                tc_result = await db.execute(
                    select(ToolConnection)
                    .where(ToolConnection.organization_id == org_id)
                    .where(ToolConnection.source_tool.in_(["ADO", "JIRA"]))
                    .order_by(ToolConnection.created_at.desc())
                    .limit(1)
                )
                tc = tc_result.scalar_one_or_none()
                if tc:
                    tool = tc.source_tool.lower()

            if tool == "jira":
                from ..services.jira_writeback import execute_batch_writeback
            else:
                from ..services.ado_writeback import execute_batch_writeback

            logger.info(f"Triggering {tool or 'ado'} batch write-back for approved plan {plan_id}")
            wb_result = await execute_batch_writeback(db, plan_id, org_id, user_id)
            logger.info(
                f"Write-back result ({tool or 'ado'}): {wb_result.get('synced', 0)} synced, "
                f"{wb_result.get('failed', 0)} failed"
            )

            # Broadcast writeback result
            await ws_manager.broadcast(org_id, {
                "type": "writeback_success",
                "data": {
                    "planId": plan_id,
                    "tool": tool or "ado",
                    "synced": wb_result.get("synced", 0),
                    "failed": wb_result.get("failed", 0),
                },
            })
        except Exception as e:
            logger.error(f"Write-back failed for plan {plan_id}: {e}")
            await ws_manager.broadcast(org_id, {
                "type": "writeback_failed",
                "data": {"planId": plan_id, "error": str(e)[:200]},
            })

    # ── Notification trigger ──
    if new_status == "PENDING_REVIEW" and old_status != "PENDING_REVIEW":
        try:
            from ..services.delivery_queue import enqueue_notification
            from ..services import card_builders
            from .notifications import get_po_email

            iter_name = "Sprint"
            if plan.iteration_id:
                iter_q = select(Iteration).where(Iteration.id == plan.iteration_id)
                iter_r = await db.execute(iter_q)
                iteration = iter_r.scalar_one_or_none()
                if iteration:
                    iter_name = iteration.name or "Sprint"

            po_email = await get_po_email(db, org_id)
            if po_email:
                await enqueue_notification(
                    org_id=org_id,
                    recipient_email=po_email,
                    notification_type="sprint_approval",
                    slack_payload=card_builders.slack_sprint_approval(
                        sprint_name=iter_name,
                        total_points=plan.total_story_points or 0,
                        ticket_count=0,
                        plan_id=plan_id,
                        org_id=org_id,
                    ),
                    teams_payload=card_builders.teams_sprint_approval(
                        sprint_name=iter_name,
                        total_points=plan.total_story_points or 0,
                        ticket_count=0,
                    ),
                )
        except Exception as e:
            logger.warning(f"Notification trigger error: {e}")

    # Broadcast status change
    await ws_manager.broadcast(org_id, {
        "type": "sprint_plan_updated",
        "data": {
            "planId": plan_id,
            "oldStatus": old_status,
            "newStatus": new_status or plan.status,
        },
    })

    return {"success": True, "message": "Sprint plan updated", "planId": plan_id}


# ---------------------------------------------------------------------------
# POST /api/sprints/complete — Force-complete a sprint (for testing/demo)
# ---------------------------------------------------------------------------

@router.post("/sprints/complete")
async def complete_sprint(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Force-complete a sprint regardless of end date.
    Used for testing and demo purposes — in production, sprints are
    auto-completed when the end date passes (date-based detection).
    """
    org_id = current_user.get("organization_id", "demo-org")
    project_id = body.get("projectId")
    iteration_id = body.get("iterationId")

    if not project_id or not iteration_id:
        raise HTTPException(
            status_code=400,
            detail="projectId and iterationId are required",
        )

    from ..services.sprint_completion import force_complete_sprint

    result = await force_complete_sprint(
        db=db,
        org_id=org_id,
        project_id=project_id,
        iteration_id=iteration_id,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# PATCH /api/sprints/team-member — Exclude/include a developer from planning
# ---------------------------------------------------------------------------

@router.patch("/sprints/team-member")
async def update_team_member_role(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Exclude or re-include a team member from sprint planning.

    Body:
    {
        "memberId": "cuid",
        "action": "exclude" | "include"
    }
    """
    org_id = current_user.get("organization_id", "demo-org")
    member_id = body.get("memberId")
    action = body.get("action", "exclude")

    if not member_id:
        raise HTTPException(status_code=400, detail="memberId is required")

    result = await db.execute(
        select(TeamMember).where(
            TeamMember.id == member_id,
            TeamMember.organization_id == org_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found")

    if action == "exclude":
        member.role = "excluded"
    elif action == "include":
        member.role = "developer"
    else:
        raise HTTPException(status_code=400, detail="action must be 'exclude' or 'include'")

    await db.commit()

    return {
        "ok": True,
        "memberId": member_id,
        "displayName": member.display_name,
        "role": member.role,
    }


# ---------------------------------------------------------------------------
# GET /api/sprints/excluded-members — List excluded team members for a project
# ---------------------------------------------------------------------------

@router.get("/sprints/excluded-members")
async def get_excluded_members(
    projectId: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return team members with role='excluded' for the given project."""
    org_id = current_user.get("organization_id", "demo-org")

    filters = [
        TeamMember.organization_id == org_id,
        TeamMember.role == "excluded",
    ]
    if projectId:
        filters.append(TeamMember.imported_project_id == projectId)

    result = await db.execute(select(TeamMember).where(*filters))
    members = result.scalars().all()

    return {
        "members": [
            {
                "id": m.id,
                "displayName": m.display_name,
                "email": m.email,
                "defaultCapacity": m.default_capacity,
            }
            for m in members
        ],
    }

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
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..auth.supabase import get_current_user, require_po
from ..database import get_db
from ..models import Iteration, SprintPlan, WorkItem, TeamMember
from ..models.sprint_plan import PlanAssignment, SprintPlan
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

    # Hotfix 90 — project-access guard. Non-PO callers must actually be
    # on the project's team (or have an explicit assignment) before
    # we'll return its sprint data, even if they're in the same org.
    if projectId:
        from ..services.project_access import assert_project_access
        await assert_project_access(db, projectId, current_user)

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

    # Get sprint plans for this scope. Hotfix 32 — Step B.
    # We split plans into two buckets:
    #   * "ready"     — plans the user actually wants to see data from
    #                   (PENDING_REVIEW / APPROVED / SYNCED / SYNCED_PARTIAL /
    #                    UNDONE / EXPIRED / SUPERSEDED — anything that has
    #                    real assignments persisted)
    #   * "inflight"  — plans currently being generated or that just failed
    #                   (GENERATING / FAILED). These hold no useful data
    #                   for the dashboard yet.
    # If a regen has just been kicked off, the GENERATING stub used to
    # win the "latest" lottery and blank out the user's display. Now we
    # surface the ready plan as ``plan`` (so all data + rebalance flags
    # stay visible) and put the in-flight stub on a sibling field
    # ``inflight`` (so the frontend can still render the generating
    # badge and poll for completion).
    READY_STATUSES = (
        "PENDING_REVIEW", "APPROVED", "SYNCED",
        "SYNCED_PARTIAL", "UNDONE", "EXPIRED", "SUPERSEDED",
    )
    INFLIGHT_STATUSES = ("GENERATING", "FAILED")

    base_query = select(SprintPlan).where(SprintPlan.organization_id == org_id)
    if projectId:
        base_query = base_query.where(SprintPlan.project_id == projectId)
    else:
        base_query = base_query.where(SprintPlan.iteration_id == iteration.id)

    ready_q = (
        base_query
        .where(SprintPlan.status.in_(READY_STATUSES))
        .order_by(SprintPlan.created_at.desc())
        .limit(1)
    )
    inflight_q = (
        base_query
        .where(SprintPlan.status.in_(INFLIGHT_STATUSES))
        .order_by(SprintPlan.created_at.desc())
        .limit(1)
    )
    plan = (await db.execute(ready_q)).scalar_one_or_none()
    inflight_plan = (await db.execute(inflight_q)).scalar_one_or_none()

    # Only surface the in-flight stub if it's STRICTLY NEWER than the
    # ready plan. If the most recent activity is a successful approval
    # (ready plan newer), there's no relevant in-flight work to show.
    inflight_data = None
    if inflight_plan and (plan is None or inflight_plan.created_at > plan.created_at):
        inflight_data = {
            "id": inflight_plan.id,
            "status": inflight_plan.status,
            "riskSummary": inflight_plan.risk_summary,
            "createdAt": inflight_plan.created_at.isoformat() if inflight_plan.created_at else None,
        }

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
            "isRebalanced": plan.is_rebalanced,
            "rebalanceSourceId": plan.rebalance_source_id,
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
        "inflight": inflight_data,
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

    # Hotfix 32 — Step B: when no specific planId is requested, return
    # the latest READY plan for the project (so dashboard data persists
    # during regeneration), and surface any newer GENERATING/FAILED stub
    # on a sibling ``inflight`` field. When planId IS supplied (e.g. the
    # frontend polling loop after POST /api/sprints), return whatever
    # that exact id holds — including GENERATING — because that's how
    # the polling state machine sees the transition.
    READY_STATUSES = (
        "PENDING_REVIEW", "APPROVED", "SYNCED",
        "SYNCED_PARTIAL", "UNDONE", "EXPIRED", "SUPERSEDED",
    )
    INFLIGHT_STATUSES = ("GENERATING", "FAILED")

    inflight_data: dict | None = None

    if planId:
        plan_q = select(SprintPlan).where(
            SprintPlan.id == planId,
            SprintPlan.organization_id == org_id,
        )
        plan_result = await db.execute(plan_q)
        plan = plan_result.scalar_one_or_none()
    else:
        scope_filter = [SprintPlan.organization_id == org_id]
        if projectId:
            scope_filter.append(SprintPlan.project_id == projectId)

        ready_q = (
            select(SprintPlan)
            .where(*scope_filter, SprintPlan.status.in_(READY_STATUSES))
            .order_by(SprintPlan.created_at.desc())
            .limit(1)
        )
        plan = (await db.execute(ready_q)).scalar_one_or_none()

        inflight_q = (
            select(SprintPlan)
            .where(*scope_filter, SprintPlan.status.in_(INFLIGHT_STATUSES))
            .order_by(SprintPlan.created_at.desc())
            .limit(1)
        )
        inflight_plan = (await db.execute(inflight_q)).scalar_one_or_none()
        if inflight_plan and (plan is None or inflight_plan.created_at > plan.created_at):
            inflight_data = {
                "id": inflight_plan.id,
                "status": inflight_plan.status,
                "riskSummary": inflight_plan.risk_summary,
                "createdAt": inflight_plan.created_at.isoformat() if inflight_plan.created_at else None,
            }

    if not plan:
        return {
            "plan": None,
            "inflight": inflight_data,
            "assignments": [],
            "workItems": [],
            "teamMembers": [],
        }

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

    # Hotfix 33f — return ALL project team_members (not just those with
    # plan assignments). When the PO clicks "+ Include" to add a new
    # developer, that dev has zero assignments in the current plan but
    # MUST still appear in the Team Capacity card with 0 SP. Previously
    # we only returned ids referenced by assignments, so the freshly
    # added dev was missing on the next refetch and the UI silently
    # erased them. Now we union the assignment-referenced ids with all
    # non-excluded team_members of the plan's project.
    tm_id_union: set[str] = set(tm_ids)
    if plan.project_id:
        proj_tm_q = await db.execute(
            select(TeamMember.id).where(
                TeamMember.organization_id == org_id,
                TeamMember.imported_project_id == plan.project_id,
                TeamMember.role != "excluded",
            )
        )
        for (mid,) in proj_tm_q.all():
            tm_id_union.add(mid)

    team_members = []
    if tm_id_union:
        tm_result = await db.execute(
            select(TeamMember).where(TeamMember.id.in_(list(tm_id_union)))
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
            "isRebalanced": plan.is_rebalanced,
            "rebalanceSourceId": plan.rebalance_source_id,
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
        "inflight": inflight_data,
    }


# ---------------------------------------------------------------------------
# POST /api/sprints — Generate (optimize) sprint plan
# ---------------------------------------------------------------------------

async def _run_sprint_generation_in_background(
    org_id: str,
    project_id: str,
    iteration_id: str | None,
    feedback: str | None,
    source_tool: str,
    existing_plan_id: str | None = None,
):
    """Hotfix 24 — background runner for sprint plan generation.

    Why this exists
    ---------------
    The previous synchronous endpoint awaited the full pipeline inline:
    ADO refresh → velocity calc → Grok call (up to 180s) → result
    persistence. Intermediate proxies (Container Apps front door, the
    browser, occasionally Cloudflare-class infra) drop HTTP connections
    around 30-60s, so the user saw "Internal Server Error" while the
    backend was still happily generating. The plan would land in DB
    and appear on refresh, but the UX was broken.

    Now the endpoint creates a fresh DB session inside the task (the
    request session has been closed by the time this fires), runs the
    same pipeline, and lets the SprintPlan record's ``status`` field
    drive the frontend polling state machine
    (GENERATING → PENDING_REVIEW / FAILED).

    Wraps the whole body in try/except so a failure marks the latest
    plan record as FAILED rather than leaving it in GENERATING forever.
    """
    from ..database import AsyncSessionLocal
    from ..services.ai_sprint_generator import generate_sprint_plan_ai
    from ..models.sprint_plan import SprintPlan
    from sqlalchemy import select as _select

    logger.info(
        f"[sprint generate] background task START project={project_id} "
        f"iteration={iteration_id} feedback={'yes' if feedback else 'no'}"
    )
    try:
        async with AsyncSessionLocal() as db:
            # Refresh source data first (mirrors the old sync flow).
            if source_tool == "ado":
                try:
                    from ..services.ado_fetch import fetch_sprint_context
                    sprint_ctx = await fetch_sprint_context(db, org_id, project_id)
                    logger.info(
                        f"[sprint generate] ADO refresh complete: "
                        f"{len(sprint_ctx.team_members)} members, "
                        f"{len(sprint_ctx.current_sprint_items)} sprint items, "
                        f"{len(sprint_ctx.backlog_items)} backlog items"
                    )
                except Exception as e:
                    logger.warning(
                        f"[sprint generate] ADO refresh failed, proceeding "
                        f"with DB data: {e}"
                    )

            # Run the actual generator. It creates the SprintPlan record,
            # calls Grok, and persists assignments + status itself.
            #
            # Hotfix 32 — capture the return value. The generator
            # SILENTLY EARLY-RETURNS with ``{"error": "..."}`` on a
            # missing-data validation failure (no iteration, no
            # developers, no plannable work items) instead of raising.
            # The outer try/except below only catches raised exceptions,
            # so without this check the stub plan would stay in
            # GENERATING forever and the user would see an infinite
            # spinner. We now propagate the error message to the stub's
            # ``risk_summary`` and mark it FAILED so the UI can show an
            # actionable message ("Mark at least one team member as a
            # developer") instead of just hanging.
            result = await generate_sprint_plan_ai(
                db=db,
                org_id=org_id,
                project_id=project_id,
                iteration_id=iteration_id,
                feedback=feedback,
                existing_plan_id=existing_plan_id,
            )
            if isinstance(result, dict) and result.get("error"):
                err_msg = str(result["error"])[:300]
                logger.warning(
                    f"[sprint generate] generator returned error for "
                    f"project={project_id}: {err_msg}"
                )
                # Mark the in-flight stub FAILED with the actionable
                # message — frontend will show it in the toolbar.
                if existing_plan_id:
                    stub = (
                        await db.execute(
                            _select(SprintPlan).where(
                                SprintPlan.id == existing_plan_id
                            )
                        )
                    ).scalar_one_or_none()
                    if stub and stub.status == "GENERATING":
                        stub.status = "FAILED"
                        stub.risk_summary = err_msg
                        await db.commit()
                # Tell the frontend the in-flight job has terminated
                # (failure case). Without this the planning page waits
                # for a websocket event that never arrives.
                try:
                    await ws_manager.broadcast(org_id, {
                        "type": "sprint_plan_updated",
                        "data": {
                            "planId": existing_plan_id,
                            "newStatus": "FAILED",
                            "error": err_msg,
                        },
                    })
                except Exception:
                    logger.exception("[sprint generate] WS broadcast (failure) failed")
            else:
                # Hotfix 33 — broadcast success so the planning page +
                # dashboard refresh immediately. Previously the BG task
                # silently finished and the frontend had no signal that
                # the new plan was ready, so the user kept seeing the
                # in-flight indicator until they manually reloaded. The
                # legacy synchronous handler (now retired) used to
                # broadcast this event; the BG-task path needs to do
                # the same.
                try:
                    await ws_manager.broadcast(org_id, {
                        "type": "sprint_plan_generated",
                        "data": {
                            "planId": (result or {}).get("planId") or existing_plan_id,
                            "iterationName": (result or {}).get("iterationName"),
                            "assignmentCount": (result or {}).get("assignmentCount", 0),
                            "totalStoryPoints": (result or {}).get("totalStoryPoints", 0),
                            "confidenceScore": (result or {}).get("confidenceScore", 0),
                        },
                    })
                except Exception:
                    logger.exception("[sprint generate] WS broadcast (success) failed")
            logger.info(
                f"[sprint generate] background DONE project={project_id}"
            )
    except Exception as e:  # noqa: BLE001
        logger.exception(
            f"[sprint generate] background generation crashed for "
            f"project {project_id}: {e!r}"
        )
        # Best-effort: mark the most recent GENERATING plan for this
        # project as FAILED so the frontend polling sees a terminal
        # state instead of an infinite spinner.
        try:
            async with AsyncSessionLocal() as db:
                stuck = (
                    await db.execute(
                        _select(SprintPlan)
                        .where(
                            SprintPlan.organization_id == org_id,
                            SprintPlan.project_id == project_id,
                            SprintPlan.status == "GENERATING",
                        )
                        .order_by(SprintPlan.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if stuck:
                    stuck.status = "FAILED"
                    stuck.risk_summary = (
                        f"Generation failed: {str(e)[:240]}"
                    )
                    await db.commit()
        except Exception:
            logger.exception(
                "[sprint generate] failed to mark stuck plan as FAILED"
            )


@router.post("/sprints", status_code=202)
async def generate_sprint_plan_endpoint(
    background_tasks: BackgroundTasks,
    body: dict | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a new AI sprint plan for the selected project (Hotfix 24 — async).

    Returns 202 Accepted immediately after scheduling the work. The
    actual generation happens in a FastAPI background task. The
    frontend should poll ``GET /api/sprints/plan?projectId=...`` every
    few seconds until the returned plan's ``status`` flips from
    ``GENERATING`` to ``PENDING_REVIEW`` (success) or ``FAILED``.

    Body:
    {
        "projectId": "cuid-of-project",
        "iterationId": "optional-iteration-id",
        "feedback": "optional-rejection-feedback-for-regen"
    }
    """
    require_po(current_user)  # Hotfix 51 (CRIT-2)
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

    # Cheap project-exists check before we accept the work.
    from ..models.imported_project import ImportedProject as IP
    proj_result = await db.execute(
        select(IP).where(IP.id == project_id, IP.organization_id == org_id)
    )
    project_record = proj_result.scalar_one_or_none()
    if not project_record:
        raise HTTPException(status_code=404, detail="Project not found")
    source_tool = (project_record.source_tool or "ado").lower()

    # Hotfix 27 — create the SprintPlan stub SYNCHRONOUSLY here so the
    # planId is committed to the DB before we return to the frontend.
    # Previously the generator created the plan record deep in its prep
    # work (after several seconds), and the frontend's poll loop would
    # find a stale FAILED plan from a previous attempt and exit
    # immediately, killing the spinner. Now POST returns a fresh
    # planId that the polling can wait for specifically.
    #
    # Hotfix 28b — resolve the iteration HERE because the schema has a
    # NOT NULL constraint on ``iteration_id``. Hotfix 27 had set it to
    # None and let the generator fill it in later, but the INSERT was
    # failing immediately with NotNullViolationError. Now we look up
    # the iteration synchronously (mirroring the generator's logic),
    # which keeps the stub valid AND saves the generator one query.
    from ..models.sprint_plan import SprintPlan
    from ..models.base import generate_cuid
    from ..models.iteration import Iteration

    resolved_iteration_id: str | None = None
    if iteration_id:
        result = await db.execute(
            select(Iteration).where(Iteration.id == iteration_id)
        )
        it = result.scalar_one_or_none()
        if it:
            resolved_iteration_id = it.id
    if not resolved_iteration_id:
        # Pick the most recent iteration for this project — same rule
        # the generator uses internally.
        q = (
            select(Iteration)
            .where(Iteration.organization_id == org_id)
            .where(Iteration.imported_project_id == project_id)
            .order_by(Iteration.start_date.desc())
            .limit(1)
        )
        latest = (await db.execute(q)).scalar_one_or_none()
        if latest:
            resolved_iteration_id = latest.id

    if not resolved_iteration_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Project has no iterations / sprints configured. "
                "Sync from ADO/Jira first or create one before generating a plan."
            ),
        )

    stub_plan = SprintPlan(
        id=generate_cuid(),
        organization_id=org_id,
        project_id=project_id,
        iteration_id=resolved_iteration_id,
        status="GENERATING",
        ai_model_used="grok-4-1-fast-reasoning",
        tool=source_tool,
        rejection_feedback=feedback,
    )
    db.add(stub_plan)
    await db.commit()
    new_plan_id = stub_plan.id

    # Schedule the heavy generation work as a background task. The task
    # mutates the stub we just created (existing_plan_id) instead of
    # making its own row.
    background_tasks.add_task(
        _run_sprint_generation_in_background,
        org_id,
        project_id,
        iteration_id,
        feedback,
        source_tool,
        new_plan_id,
    )

    return {
        "queued": True,
        "projectId": project_id,
        "planId": new_plan_id,
        "status": "GENERATING",
        "message": (
            "Sprint plan generation queued. Poll "
            "/api/sprints?projectId=... until plan.status is no longer GENERATING."
        ),
    }


# ---------------------------------------------------------------------------
# Legacy synchronous sprint generation (kept for any internal callers; new
# clients should use the async endpoint above).
# ---------------------------------------------------------------------------

async def _legacy_sync_generate_unused(
    body: dict | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Old synchronous handler — preserved for reference, no route binding.
    See /sprints (async) endpoint above for the live implementation.
    """
    org_id = current_user.get("organization_id", "demo-org")
    body = body or {}
    project_id = body.get("projectId")
    iteration_id = body.get("iterationId")
    feedback = body.get("feedback")
    if feedback:
        feedback = f"{feedback}\n[Regeneration requested at {datetime.now(timezone.utc).isoformat()}]"
    if not project_id:
        raise HTTPException(status_code=400, detail="projectId is required")
    from ..models.imported_project import ImportedProject as IP
    proj_result = await db.execute(
        select(IP).where(IP.id == project_id, IP.organization_id == org_id)
    )
    project_record = proj_result.scalar_one_or_none()
    source_tool = (project_record.source_tool or "ado").lower() if project_record else "ado"
    if source_tool == "ado":
        try:
            from ..services.ado_fetch import fetch_sprint_context
            await fetch_sprint_context(db, org_id, project_id)
        except Exception as e:
            logger.warning(f"ADO data refresh failed (proceeding with DB data): {e}")
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
    require_po(current_user)  # Hotfix 51 (CRIT-2)
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
    require_po(current_user)  # Hotfix 51 (CRIT-2)
    plan_id = body.get("planId")
    org_id = current_user.get("organization_id", "demo-org")
    user_id = current_user.get("sub", current_user.get("id", "unknown"))

    if not plan_id:
        raise HTTPException(status_code=400, detail="planId is required")

    plan_query = select(SprintPlan).where(
        SprintPlan.id == plan_id,
        SprintPlan.organization_id == org_id,
    )
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

    # ── Timeline sync on plan approval ──────────────────────────────
    # When a plan is APPROVED (first time OR after regeneration), the PO
    # expects the PO dashboard's Target Launch + phase timeline to reflect
    # the new plan's estimated end date. This is the "approve = timeline
    # updates" contract. Overrides any prior MANUAL target edit — the PO's
    # act of approving a new plan is a stronger signal than an older manual
    # override.
    if new_status == "APPROVED" and plan.project_id and plan.estimated_end_date:
        try:
            from ..models.imported_project import ImportedProject
            from ..routers.projects import _rescale_future_phases
            proj_r = await db.execute(
                select(ImportedProject).where(ImportedProject.id == plan.project_id)
            )
            proj = proj_r.scalar_one_or_none()
            if proj is not None:
                proj.target_launch_date = plan.estimated_end_date
                proj.target_launch_source = "AUTO"
                await db.commit()
                await _rescale_future_phases(db, proj, plan.estimated_end_date)
                logger.info(
                    f"Plan {plan_id} approval: target_launch_date set to "
                    f"{plan.estimated_end_date.isoformat()} and timeline rescaled"
                )
        except Exception as e:  # noqa: BLE001 — never fail the approval on a timeline hiccup
            logger.warning(f"Timeline sync on approval failed for plan {plan_id}: {e}")

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
    require_po(current_user)  # Hotfix 51 (CRIT-2)
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
        "projectId": "cuid",   # Hotfix 33c — required for "include" of an
                                # org user who isn't yet a project member.
                                # Optional for plain exclude/include of an
                                # existing TeamMember (back-compat).
        "action": "exclude" | "include"
    }

    Hotfix 33c — root cause fix for "added developers don't appear in
    plan". The PO clicks "+ Include" in the Team Capacity card to bring
    an org user into the current project's plan. Previously this endpoint
    only knew how to TOGGLE existing TeamMember rows — if the candidate
    came from the org-members list (i.e. they had no TeamMember row for
    THIS project yet), the PATCH either 404'd silently or accidentally
    toggled a TeamMember bound to a *different* project. The user then
    saw the AI generate a plan that ignored them.

    Now the flow is:
      1. Try to find a TeamMember row matching ``memberId``. If found,
         toggle its role (back-compat with the previous contract).
      2. Otherwise, if ``action='include'`` AND ``projectId`` is given,
         look the id up as a User and CREATE a new TeamMember bound to
         that project with role='developer'. This is the only path that
         actually grows the project team.
      3. Otherwise return 404 like before.
    """
    # Hotfix 51 (CRIT-5) — only PO/admin/owner can toggle team-member roles.
    require_po(current_user)

    org_id = current_user.get("organization_id", "demo-org")
    member_id = body.get("memberId")
    action = body.get("action", "exclude")
    project_id = body.get("projectId")

    if not member_id:
        raise HTTPException(status_code=400, detail="memberId is required")

    if action not in ("exclude", "include"):
        raise HTTPException(status_code=400, detail="action must be 'exclude' or 'include'")

    # Hotfix 33c (revised). The frontend sends ``memberId`` which can be
    # one of three things, depending on the kind of candidate:
    #   (a) A TeamMember.id for the CURRENT project       → toggle role
    #   (b) A TeamMember.id for a DIFFERENT project       → use its
    #       display_name/email to create a NEW TeamMember bound to the
    #       current project (don't disturb the original row)
    #   (c) A User.id (no TeamMember row anywhere)        → look up the
    #       User and create a new TeamMember bound to the current project
    # We resolve the source first, then take the right action.

    from ..models.user import User
    from ..models.base import generate_cuid as _gen
    from ..models.imported_project import ImportedProject as _IP

    # Try TeamMember lookup first
    tm_q = await db.execute(
        select(TeamMember).where(
            TeamMember.id == member_id,
            TeamMember.organization_id == org_id,
        )
    )
    source_tm = tm_q.scalar_one_or_none()

    # Try User lookup as alternative
    user_q = await db.execute(
        select(User).where(
            User.id == member_id,
            User.organization_id == org_id,
        )
    )
    source_user = user_q.scalar_one_or_none()

    if not source_tm and not source_user:
        raise HTTPException(status_code=404, detail="Team member or user not found")

    # Case (a) — TeamMember already on THIS project: simple toggle.
    if source_tm and source_tm.imported_project_id == project_id:
        if action == "exclude":
            source_tm.role = "excluded"
        else:
            source_tm.role = "developer"
        await db.commit()
        return {
            "ok": True,
            "memberId": source_tm.id,
            "displayName": source_tm.display_name,
            "role": source_tm.role,
            "createdNew": False,
        }

    # Case (a') — TeamMember exists with no project binding (org-wide).
    # Same as (a): just toggle role.
    if source_tm and not source_tm.imported_project_id and not project_id:
        if action == "exclude":
            source_tm.role = "excluded"
        else:
            source_tm.role = "developer"
        await db.commit()
        return {
            "ok": True,
            "memberId": source_tm.id,
            "displayName": source_tm.display_name,
            "role": source_tm.role,
            "createdNew": False,
        }

    # Hotfix 33g — lenient exclude. If we found a TeamMember and the
    # user is asking to exclude it, just flip the role regardless of
    # project_id match. The frontend's exclude flow doesn't pass
    # projectId today (it's removing a row that's already visible in
    # the team capacity card, so the project context is implicit). The
    # earlier 400 broke deletion entirely.
    if source_tm and action == "exclude":
        source_tm.role = "excluded"
        await db.commit()
        return {
            "ok": True,
            "memberId": source_tm.id,
            "displayName": source_tm.display_name,
            "role": source_tm.role,
            "createdNew": False,
        }

    # Cases (b) and (c) — need a projectId to create a new project-bound
    # TeamMember. Without it we can't act.
    if action != "include" or not project_id:
        raise HTTPException(
            status_code=400,
            detail="projectId is required to add this member to the current project",
        )

    # Verify the project belongs to this org.
    proj_chk = await db.execute(
        select(_IP).where(
            _IP.id == project_id,
            _IP.organization_id == org_id,
        )
    )
    if not proj_chk.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    # Pick display_name + email + avatar from whichever source we have.
    if source_tm:
        display_name = source_tm.display_name
        email = source_tm.email
        avatar_url = source_tm.avatar_url
        skill_tags = source_tm.skill_tags or []
        capacity = source_tm.default_capacity or 40.0
    else:
        # source_user
        display_name = source_user.full_name or (source_user.email.split("@")[0] if source_user.email else "Member")
        email = source_user.email
        avatar_url = getattr(source_user, "avatar_url", None)
        skill_tags = []
        capacity = 40.0

    # Don't double-add — if a row already exists for this email + project,
    # just (re-)include it.
    if email:
        existing = await db.execute(
            select(TeamMember).where(
                TeamMember.organization_id == org_id,
                TeamMember.imported_project_id == project_id,
                TeamMember.email.ilike(email),
            )
        )
        existing_member = existing.scalar_one_or_none()
        if existing_member:
            existing_member.role = "developer"
            await db.commit()
            return {
                "ok": True,
                "memberId": existing_member.id,
                "displayName": existing_member.display_name,
                "role": existing_member.role,
                "createdNew": False,
            }

    # Hotfix 33d — ``external_id`` is NOT NULL on team_members and has
    # a unique constraint on (organization_id, external_id). For
    # manually-added members (no upstream tool sync) we synthesise a
    # stable id prefixed with ``manual:`` and qualified by project_id +
    # email so it never collides with ADO/Jira-synced rows or with the
    # same user added to a different project.
    new_member_id = _gen()
    synthetic_ext_id = f"manual:{project_id}:{email or new_member_id}"
    new_member = TeamMember(
        id=new_member_id,
        organization_id=org_id,
        imported_project_id=project_id,
        external_id=synthetic_ext_id,
        display_name=display_name,
        email=email,
        role="developer",
        default_capacity=capacity,
        skill_tags=skill_tags,
        avatar_url=avatar_url,
    )
    db.add(new_member)
    await db.commit()
    await db.refresh(new_member)
    logger.info(
        f"[team-member] created project-bound member {new_member.id} "
        f"({display_name} <{email}>) on project {project_id} "
        f"(source: {'team_member' if source_tm else 'user'})"
    )
    return {
        "ok": True,
        "memberId": new_member.id,
        "displayName": new_member.display_name,
        "role": new_member.role,
        "createdNew": True,
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


# ---------------------------------------------------------------------------
# POST /api/sprints/rebalance — Generate a rebalancing proposal
# ---------------------------------------------------------------------------

@router.post("/sprints/rebalance")
async def generate_rebalance(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an AI-powered rebalancing proposal for an at-risk sprint plan."""
    require_po(current_user)  # Hotfix 51 (CRIT-2)
    import sys, traceback as tb
    print(f"[REBALANCE] Received request: {body}", file=sys.stderr, flush=True)

    from ..services.sprint_rebalancer import generate_rebalance_proposal

    org_id = current_user.get("organization_id", "demo-org")
    plan_id = body.get("planId")
    mode = body.get("mode", "PROTECT_TIMELINE")
    target_date = body.get("targetDate")
    po_guidance = body.get("poGuidance")

    print(f"[REBALANCE] org={org_id}, plan={plan_id}, mode={mode}", file=sys.stderr, flush=True)

    if not plan_id:
        raise HTTPException(status_code=400, detail="planId is required")

    if mode not in ("PROTECT_TIMELINE", "PROTECT_SCOPE", "CUSTOM_DATE"):
        raise HTTPException(status_code=400, detail="mode must be PROTECT_TIMELINE, PROTECT_SCOPE, or CUSTOM_DATE")

    try:
        result = await generate_rebalance_proposal(
            db, org_id, plan_id, mode, target_date, po_guidance
        )
        print(f"[REBALANCE] Result ok={result.get('ok')}", file=sys.stderr, flush=True)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Rebalancing failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"[REBALANCE] EXCEPTION: {tb.format_exc()}", file=sys.stderr, flush=True)
        logger.exception("Rebalance generation failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /api/sprints/rebalance/approve — Approve proposal → new active plan
# ---------------------------------------------------------------------------

@router.post("/sprints/rebalance/approve")
async def approve_rebalance_endpoint(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve a rebalance proposal — creates new plan, supersedes old one."""
    require_po(current_user)  # Hotfix 51 (CRIT-2)
    from ..services.sprint_rebalancer import approve_rebalance

    proposal_id = body.get("proposalId")
    if not proposal_id:
        raise HTTPException(status_code=400, detail="proposalId is required")

    user_id = current_user.get("user_id")

    try:
        result = await approve_rebalance(db, proposal_id, user_id)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Approval failed"))

        # ── Timeline sync on rebalance acceptance ──────────────────────
        # A rebalance acceptance creates a new active plan (result.newPlanId)
        # with a possibly-changed estimated_end_date (e.g. Protect Scope
        # extends the deadline). Push that new end date onto the project's
        # target_launch_date + rescale the future phase window the same way
        # a fresh plan approval does.
        try:
            new_plan_id = result.get("newPlanId")
            if new_plan_id:
                from ..models.imported_project import ImportedProject
                from ..routers.projects import _rescale_future_phases
                plan_r = await db.execute(
                    select(SprintPlan).where(SprintPlan.id == new_plan_id)
                )
                new_plan = plan_r.scalar_one_or_none()
                if (
                    new_plan is not None
                    and new_plan.project_id
                    and new_plan.estimated_end_date is not None
                ):
                    proj_r = await db.execute(
                        select(ImportedProject).where(ImportedProject.id == new_plan.project_id)
                    )
                    proj = proj_r.scalar_one_or_none()
                    if proj is not None:
                        proj.target_launch_date = new_plan.estimated_end_date
                        proj.target_launch_source = "AUTO"
                        await db.commit()
                        await _rescale_future_phases(db, proj, new_plan.estimated_end_date)
                        logger.info(
                            f"Rebalance accepted (plan {new_plan_id}): target + timeline rescaled"
                        )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Timeline sync on rebalance approval failed: {e}")

        # Broadcast rebalance event
        org_id = current_user.get("organization_id", "demo-org")
        await ws_manager.broadcast(org_id, {
            "type": "sprint_rebalanced",
            "data": {
                "newPlanId": result.get("newPlanId"),
                "oldPlanId": result.get("oldPlanId"),
            },
        })

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Rebalance approval failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/sprints/rebalance/latest — Fetch current proposal for a plan
# ---------------------------------------------------------------------------

@router.get("/sprints/rebalance/latest")
async def get_latest_rebalance(
    planId: str = Query(..., description="The sprint plan ID"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the most recent rebalance proposal for a given sprint plan."""
    from ..models.sprint_plan import RebalanceProposal

    org_id = current_user.get("organization_id", "demo-org")

    from sqlalchemy import or_
    result = await db.execute(
        select(RebalanceProposal)
        .where(
            RebalanceProposal.organization_id == org_id,
            or_(
                RebalanceProposal.sprint_plan_id == planId,
                RebalanceProposal.new_plan_id == planId,
            ),
        )
        .order_by(RebalanceProposal.created_at.desc())
        .limit(1)
    )
    proposal = result.scalar_one_or_none()

    if not proposal:
        return {"found": False}

    return {
        "found": True,
        "proposalId": proposal.id,
        "status": proposal.status,
        "mode": proposal.mode,
        "summary": proposal.summary,
        "rationale": proposal.ai_rationale,
        "originalSuccessProbability": proposal.original_success_probability,
        "projectedSuccessProbability": proposal.projected_success_probability,
        "originalEndDate": proposal.original_end_date.isoformat() if proposal.original_end_date else None,
        "projectedEndDate": proposal.projected_end_date.isoformat() if proposal.projected_end_date else None,
        "sprints": proposal.sprint_allocations,
        "changesSummary": proposal.changes_summary,
        "downstreamImpact": proposal.downstream_impact,
        "createdAt": proposal.created_at.isoformat() if proposal.created_at else None,
    }

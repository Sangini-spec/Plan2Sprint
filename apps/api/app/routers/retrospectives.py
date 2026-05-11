"""
GET|POST /api/retrospectives
Retrospective data and sprint failure analysis.

GET  /api/retrospectives              — Latest retrospective for the org
POST /api/retrospectives/analyze      — Trigger failure analysis for a completed sprint
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models.retrospective import Retrospective, RetroActionItem
from ..models.iteration import Iteration
from ..models.sprint_plan import SprintPlan

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/retrospectives")
async def get_latest_retrospective(
    projectId: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the latest retrospective with failure analysis data, optionally scoped to project."""
    org_id = current_user.get("organization_id", "demo-org")

    # Hotfix 90 — project-access guard.
    if projectId:
        from ..services.project_access import assert_project_access
        await assert_project_access(db, projectId, current_user)

    query = (
        select(Retrospective)
        .options(selectinload(Retrospective.action_items))
        .where(Retrospective.organization_id == org_id)
    )

    # If projectId given, only show retrospectives whose iteration belongs to that project
    if projectId:
        query = (
            query
            .join(Iteration, Retrospective.iteration_id == Iteration.id)
            .where(Iteration.imported_project_id == projectId)
        )

    result = await db.execute(
        query.order_by(Retrospective.created_at.desc()).limit(1)
    )
    retro = result.scalar_one_or_none()

    if not retro:
        return {"retrospective": None}

    # Resolve iteration details (name, number, source, dates)
    iter_name = ""
    iter_source_tool = ""
    iter_start_date = None
    iter_end_date = None
    iter_number = None  # Sprint number (ordinal within project)
    iter_state = ""
    if retro.iteration_id:
        iter_result = await db.execute(
            select(Iteration).where(Iteration.id == retro.iteration_id)
        )
        iteration = iter_result.scalar_one_or_none()
        if iteration:
            iter_name = iteration.name or ""
            iter_source_tool = iteration.source_tool or ""
            iter_start_date = iteration.start_date.isoformat() if iteration.start_date else None
            iter_end_date = iteration.end_date.isoformat() if iteration.end_date else None
            iter_state = iteration.state or ""

            # Compute sprint number: count iterations for same project ordered by start_date
            if iteration.imported_project_id:
                num_result = await db.execute(
                    select(func.count())
                    .select_from(Iteration)
                    .where(
                        Iteration.organization_id == org_id,
                        Iteration.imported_project_id == iteration.imported_project_id,
                        Iteration.start_date <= iteration.start_date,
                    )
                )
                iter_number = num_result.scalar() or 1

    # Determine retro source: ADO/Jira sprint end or Plan2Sprint optimized
    retro_source = "ado_sprint"  # default
    if iter_source_tool.upper() == "JIRA":
        retro_source = "jira_sprint"
    evidence = retro.failure_evidence if isinstance(retro.failure_evidence, dict) else {}
    if evidence.get("type") == "success":
        retro_source = f"{iter_source_tool.lower()}_sprint" if iter_source_tool else "platform"

    # Determine completion trigger from failure_evidence or feed_forward
    completion_trigger = evidence.get("trigger", "end_date_passed")

    action_items = []
    for ai in (retro.action_items or []):
        action_items.append({
            "id": ai.id,
            "title": ai.title,
            "status": ai.status,
            "assigneeId": ai.assignee_id,
            "dueDate": ai.due_date.isoformat() if ai.due_date else None,
        })

    return {
        "retrospective": {
            "id": retro.id,
            "iterationName": iter_name,
            "sprintNumber": iter_number,
            "sourceTool": iter_source_tool,
            "retroSource": retro_source,
            "completionTrigger": completion_trigger,
            "iterationStartDate": iter_start_date,
            "iterationEndDate": iter_end_date,
            "iterationState": iter_state,
            "finalizedAt": retro.finalized_at.isoformat() if retro.finalized_at else None,
            "whatWentWell": retro.what_went_well.get("items", []) if isinstance(retro.what_went_well, dict) else retro.what_went_well,
            "whatDidntGoWell": retro.what_didnt_go_well.get("items", []) if isinstance(retro.what_didnt_go_well, dict) else retro.what_didnt_go_well,
            "rootCauseAnalysis": retro.root_cause_analysis.get("items", []) if isinstance(retro.root_cause_analysis, dict) else (retro.root_cause_analysis or []),
            "actionItems": action_items,
            # Failure analysis fields
            "failureClassification": retro.failure_classification,
            "failureEvidence": retro.failure_evidence,
            "patternDetected": retro.pattern_detected,
            "consecutiveFailureCount": retro.consecutive_failure_count,
            "feedForwardSignals": retro.feed_forward_signals,
            "conclusion": retro.conclusion,
            "isArchived": retro.is_archived,
        },
    }


@router.get("/retrospectives/history")
async def get_retrospective_history(
    projectId: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return one-line conclusions for all past (archived) sprints, plus the latest active retro ID."""
    org_id = current_user.get("organization_id", "demo-org")

    query = (
        select(Retrospective)
        .where(
            Retrospective.organization_id == org_id,
            Retrospective.is_archived == True,
        )
    )

    if projectId:
        query = (
            query
            .join(Iteration, Retrospective.iteration_id == Iteration.id)
            .where(Iteration.imported_project_id == projectId)
        )

    result = await db.execute(
        query.order_by(Retrospective.created_at.desc())
    )
    archived = result.scalars().all()

    items = []
    for r in archived:
        # Resolve sprint number and name
        iter_name = ""
        iter_number = None
        iter_start = None
        iter_end = None
        if r.iteration_id:
            it_result = await db.execute(
                select(Iteration).where(Iteration.id == r.iteration_id)
            )
            iteration = it_result.scalar_one_or_none()
            if iteration:
                iter_name = iteration.name or ""
                iter_start = iteration.start_date.isoformat() if iteration.start_date else None
                iter_end = iteration.end_date.isoformat() if iteration.end_date else None
                if iteration.imported_project_id:
                    num_result = await db.execute(
                        select(func.count())
                        .select_from(Iteration)
                        .where(
                            Iteration.organization_id == org_id,
                            Iteration.imported_project_id == iteration.imported_project_id,
                            Iteration.start_date <= iteration.start_date,
                        )
                    )
                    iter_number = num_result.scalar() or 1

        items.append({
            "id": r.id,
            "iterationName": iter_name,
            "sprintNumber": iter_number,
            "startDate": iter_start,
            "endDate": iter_end,
            "conclusion": r.conclusion or "No summary available",
            "failureClassification": r.failure_classification,
            "finalizedAt": r.finalized_at.isoformat() if r.finalized_at else None,
        })

    return {"history": items}


@router.get("/retrospectives/{retro_id}")
async def get_retrospective_by_id(
    retro_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single retrospective by ID with full detail."""
    org_id = current_user.get("organization_id", "demo-org")

    result = await db.execute(
        select(Retrospective)
        .options(selectinload(Retrospective.action_items))
        .where(
            Retrospective.id == retro_id,
            Retrospective.organization_id == org_id,
        )
    )
    retro = result.scalar_one_or_none()
    if not retro:
        raise HTTPException(status_code=404, detail="Retrospective not found")

    # Resolve iteration details
    iter_name = ""
    iter_source_tool = ""
    iter_start_date = None
    iter_end_date = None
    iter_number = None
    iter_state = ""
    if retro.iteration_id:
        iter_result = await db.execute(
            select(Iteration).where(Iteration.id == retro.iteration_id)
        )
        iteration = iter_result.scalar_one_or_none()
        if iteration:
            iter_name = iteration.name or ""
            iter_source_tool = iteration.source_tool or ""
            iter_start_date = iteration.start_date.isoformat() if iteration.start_date else None
            iter_end_date = iteration.end_date.isoformat() if iteration.end_date else None
            iter_state = iteration.state or ""

            if iteration.imported_project_id:
                num_result = await db.execute(
                    select(func.count())
                    .select_from(Iteration)
                    .where(
                        Iteration.organization_id == org_id,
                        Iteration.imported_project_id == iteration.imported_project_id,
                        Iteration.start_date <= iteration.start_date,
                    )
                )
                iter_number = num_result.scalar() or 1

    retro_source = "ado_sprint"
    if iter_source_tool.upper() == "JIRA":
        retro_source = "jira_sprint"
    evidence = retro.failure_evidence if isinstance(retro.failure_evidence, dict) else {}
    if evidence.get("type") == "success":
        retro_source = f"{iter_source_tool.lower()}_sprint" if iter_source_tool else "platform"

    completion_trigger = evidence.get("trigger", "end_date_passed")

    action_items = []
    for ai in (retro.action_items or []):
        action_items.append({
            "id": ai.id,
            "title": ai.title,
            "status": ai.status,
            "assigneeId": ai.assignee_id,
            "dueDate": ai.due_date.isoformat() if ai.due_date else None,
        })

    return {
        "retrospective": {
            "id": retro.id,
            "iterationName": iter_name,
            "sprintNumber": iter_number,
            "sourceTool": iter_source_tool,
            "retroSource": retro_source,
            "completionTrigger": completion_trigger,
            "iterationStartDate": iter_start_date,
            "iterationEndDate": iter_end_date,
            "iterationState": iter_state,
            "finalizedAt": retro.finalized_at.isoformat() if retro.finalized_at else None,
            "whatWentWell": retro.what_went_well.get("items", []) if isinstance(retro.what_went_well, dict) else retro.what_went_well,
            "whatDidntGoWell": retro.what_didnt_go_well.get("items", []) if isinstance(retro.what_didnt_go_well, dict) else retro.what_didnt_go_well,
            "rootCauseAnalysis": retro.root_cause_analysis.get("items", []) if isinstance(retro.root_cause_analysis, dict) else (retro.root_cause_analysis or []),
            "actionItems": action_items,
            "failureClassification": retro.failure_classification,
            "failureEvidence": retro.failure_evidence,
            "patternDetected": retro.pattern_detected,
            "consecutiveFailureCount": retro.consecutive_failure_count,
            "feedForwardSignals": retro.feed_forward_signals,
            "conclusion": retro.conclusion,
            "isArchived": retro.is_archived,
        },
    }


@router.post("/retrospectives/analyze")
async def trigger_failure_analysis(
    body: dict | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger failure analysis for a completed sprint."""
    org_id = current_user.get("organization_id", "demo-org")
    body = body or {}

    project_id = body.get("projectId")
    iteration_id = body.get("iterationId")

    if not project_id or not iteration_id:
        raise HTTPException(status_code=400, detail="projectId and iterationId are required")

    from ..services.failure_analysis import analyze_sprint_failure

    result = await analyze_sprint_failure(db, org_id, project_id, iteration_id)
    await db.commit()

    return {"ok": True, **result}


@router.post("/retrospectives/generate-now")
async def generate_retro_now(
    body: dict | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hotfix 82 — manually fire the full retrospective pipeline for an
    AI Sprint Plan, regardless of whether its ``estimated_end_date`` has
    passed. This is the testing/demo path for the new AI-plan-driven
    trigger so the PO doesn't have to wait for the natural end-date to
    verify it's working.

    Body: { "sprintPlanId": "..." }   (preferred — uses the plan's iteration)
       or { "iterationId": "..." }    (fallback — direct iteration override)

    Calls ``_complete_single_sprint`` with trigger='manual'. The pipeline
    runs failure-vs-success retro selection based on completion rate, so
    a 0%-done sprint produces a failure retro that names the plan a
    failure in detail (which is what you want — Sangini 2026-05-06).
    """
    from ..services.sprint_completion import _complete_single_sprint

    org_id = current_user.get("organization_id", "demo-org")
    body = body or {}

    sprint_plan_id = body.get("sprintPlanId")
    iteration_id = body.get("iterationId")

    iteration: Iteration | None = None
    project_id: str | None = None

    if sprint_plan_id:
        plan_q = await db.execute(
            select(SprintPlan).where(
                SprintPlan.id == sprint_plan_id,
                SprintPlan.organization_id == org_id,
            )
        )
        plan = plan_q.scalar_one_or_none()
        if not plan:
            raise HTTPException(status_code=404, detail="Sprint plan not found")
        if not plan.iteration_id:
            raise HTTPException(status_code=400, detail="Sprint plan has no linked iteration")
        iteration_id = plan.iteration_id
        project_id = plan.project_id

    if not iteration_id:
        raise HTTPException(
            status_code=400,
            detail="sprintPlanId or iterationId is required",
        )

    iter_q = await db.execute(
        select(Iteration).where(
            Iteration.id == iteration_id,
            Iteration.organization_id == org_id,
        )
    )
    iteration = iter_q.scalar_one_or_none()
    if not iteration:
        raise HTTPException(status_code=404, detail="Iteration not found")

    if not project_id:
        project_id = iteration.imported_project_id

    summary = await _complete_single_sprint(
        db=db,
        org_id=org_id,
        project_id=project_id,
        iteration=iteration,
        trigger="manual",
    )
    await db.commit()
    return {"ok": True, **summary}


# ---------------------------------------------------------------------------
# GET /api/retrospectives/project-summary  (Hotfix 83)
# ---------------------------------------------------------------------------
#
# Returns a project-cycle-level summary used by the Retrospective page when
# the project has passed its target launch date. This is the single source
# of truth for both the in-app "Project Cycle Concluded" card AND the email
# alert sent by services/overdue_alert.py — they call back into this same
# data shape (via _build_project_summary below) so the email body and the
# UI card are always in lock-step.
# ---------------------------------------------------------------------------

@router.get("/retrospectives/project-summary")
async def get_project_summary(
    projectId: str = Query(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Project-cycle summary for the retrospective page.

    Returns ``{lifecycleStatus, daysPastTarget, targetLaunchDate,
    completionPct, totals, completedItems, outstandingItems,
    outstandingPhases}``. ``lifecycleStatus`` is the canonical one from
    ``services.project_status.compute_overdue_status``.

    The UI surfaces a "Project Cycle Concluded" card only when
    ``lifecycleStatus != 'on_track'``.
    """
    from ..models.imported_project import ImportedProject
    from ..models.work_item import WorkItem
    from ..models.project_phase import ProjectPhase
    from ..services.project_status import compute_overdue_status

    org_id = current_user.get("organization_id", "demo-org")

    proj = (await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == projectId,
            ImportedProject.organization_id == org_id,
        )
    )).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    return await _build_project_summary(db, proj)


async def _build_project_summary(db: AsyncSession, proj) -> dict:
    """Shared builder used by the API endpoint AND the email sender.

    Returned dict matches the JSON shape clients consume:
      {
        lifecycleStatus, daysPastTarget,
        targetLaunchDate (ISO),
        projectName,
        completionPct,
        totals: {stories, completed, inProgress, notStarted},
        completedItems:   [{title, ticketId}, ...]   # max 50
        outstandingItems: [{title, ticketId, status, phase}, ...]  # max 50
        outstandingPhases: [{slug, name, outstandingCount}, ...]
      }
    """
    from ..models.work_item import WorkItem
    from ..models.project_phase import ProjectPhase
    from ..services.project_status import compute_overdue_status

    # Work-item rollup (story-level, same shape the dashboard uses).
    wi_q = await db.execute(
        select(WorkItem).where(
            WorkItem.imported_project_id == proj.id,
            WorkItem.type.in_(["story", "task", "bug", "user_story"]),
        )
    )
    items = wi_q.scalars().all()

    finished = {"DONE", "CLOSED", "RESOLVED", "REMOVED", "ABANDONED"}
    not_started = {"BACKLOG", "NEW", "TODO", "PROPOSED"}

    completed: list[dict] = []
    outstanding: list[dict] = []
    in_progress = 0
    not_started_count = 0

    # Phase id -> name lookup
    phases_q = await db.execute(
        select(ProjectPhase.id, ProjectPhase.slug, ProjectPhase.name, ProjectPhase.sort_order)
        .where(ProjectPhase.project_id == proj.id)
        .order_by(ProjectPhase.sort_order)
    )
    phase_meta = {pid: {"slug": slug, "name": name, "sortOrder": so}
                  for pid, slug, name, so in phases_q.all()}

    # Outstanding count per phase — for the "outstanding phases" line in
    # the email + UI card.
    phase_outstanding: dict[str, int] = {}

    for wi in items:
        st = (wi.status or "").upper()
        title = wi.title or ""
        ext = wi.external_id or ""

        if st in finished:
            completed.append({"title": title, "ticketId": ext})
        else:
            outstanding.append({
                "title": title,
                "ticketId": ext,
                "status": st,
                "phase": (phase_meta.get(wi.phase_id) or {}).get("name") if wi.phase_id else None,
            })
            if st in not_started:
                not_started_count += 1
            else:
                in_progress += 1

            # Roll up to phase via the work item's own phase_id, or — when
            # missing — via its parent feature's phase_id. Mirrors the
            # timeline engine's descendant-aware logic so phases line up
            # consistently across the UI.
            roll_phase_id = wi.phase_id
            if not roll_phase_id and wi.epic_id:
                parent = await db.execute(
                    select(WorkItem.phase_id).where(WorkItem.id == wi.epic_id)
                )
                roll_phase_id = parent.scalar_one_or_none()
            if roll_phase_id:
                phase_outstanding[roll_phase_id] = phase_outstanding.get(roll_phase_id, 0) + 1

    total = len(items)
    pct = (len(completed) / total * 100) if total else 0
    overdue = compute_overdue_status(
        target_launch_date=proj.target_launch_date,
        completion_pct=pct,
        is_active=bool(proj.is_active),
    )

    outstanding_phases = sorted(
        [
            {
                "slug": phase_meta[pid]["slug"],
                "name": phase_meta[pid]["name"],
                "outstandingCount": cnt,
            }
            for pid, cnt in phase_outstanding.items()
            if pid in phase_meta
        ],
        key=lambda x: -x["outstandingCount"],
    )

    return {
        "projectId": proj.id,
        "projectName": proj.name,
        "lifecycleStatus": overdue.status,
        "daysPastTarget": overdue.days_past,
        "targetLaunchDate": proj.target_launch_date.isoformat() if proj.target_launch_date else None,
        "completionPct": round(pct, 1),
        "totals": {
            "stories": total,
            "completed": len(completed),
            "inProgress": in_progress,
            "notStarted": not_started_count,
        },
        # Cap at 50 each so the email body stays a sensible length even
        # for huge projects. The UI can paginate.
        "completedItems": completed[:50],
        "outstandingItems": outstanding[:50],
        "outstandingPhases": outstanding_phases,
    }

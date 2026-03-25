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

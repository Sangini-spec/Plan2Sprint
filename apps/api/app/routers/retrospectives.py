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
from sqlalchemy import select
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

    # Resolve iteration name
    iter_name = ""
    if retro.iteration_id:
        iter_result = await db.execute(
            select(Iteration).where(Iteration.id == retro.iteration_id)
        )
        iteration = iter_result.scalar_one_or_none()
        if iteration:
            iter_name = iteration.name or ""

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

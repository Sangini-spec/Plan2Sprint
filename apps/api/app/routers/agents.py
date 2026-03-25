"""
Agent API Router — endpoints for triggering and monitoring AI agents.

POST /api/agents/standup/generate   — trigger AI standup generation
POST /api/agents/blockers/scan      — run smart blocker detection
POST /api/agents/health/analyze     — run sprint health coach
POST /api/agents/retro/generate     — generate AI retrospective
GET  /api/agents/status             — check agent service configuration status
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.supabase import get_current_user
from ..database import get_db
from ..services.agent_orchestrator import orchestrator
from ..services.ws_manager import ws_manager
from ..models.in_app_notification import InAppNotification
from ..models.base import generate_cuid

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helper — create in-app notification + broadcast WS event
# ---------------------------------------------------------------------------

async def _create_notification(
    db: AsyncSession,
    org_id: str,
    notification_type: str,
    title: str,
    body: str,
    recipient_email: str | None = None,
) -> None:
    """Create an InAppNotification record and broadcast via WebSocket."""
    # Use a fallback email for demo mode
    email = recipient_email or "demo@plan2sprint.io"

    try:
        notif = InAppNotification(
            id=generate_cuid(),
            organization_id=org_id,
            recipient_email=email,
            notification_type=notification_type,
            title=title,
            body=body,
            read=False,
        )
        db.add(notif)
        await db.commit()

        # Broadcast WS event so the notification bell auto-refreshes
        await ws_manager.broadcast(
            org_id,
            {
                "type": "notification",
                "notification_type": notification_type,
                "title": title,
                "body": body,
            },
        )
    except Exception as e:
        logger.warning(f"Failed to create notification: {e}")


async def _get_user_email(db: AsyncSession, org_id: str, user: dict) -> str:
    """Get the current user's email (or a fallback for demo mode)."""
    email = user.get("email")
    if email:
        return email
    # Demo mode fallback: get PO email
    from .notifications import get_po_email
    po_email = await get_po_email(db, org_id)
    return po_email or "demo@plan2sprint.io"


# ---------------------------------------------------------------------------
# GET /api/agents/status — check if agent service is configured
# ---------------------------------------------------------------------------

@router.get("/agents/status")
async def agent_status(user: dict = Depends(get_current_user)):
    """Check agent service configuration and available agents."""
    available = "available" if orchestrator.is_configured else "needs_config"
    return {
        "configured": orchestrator.is_configured,
        "agents": [
            {
                "name": "standup-generator",
                "description": "Auto-generates daily standup reports from GitHub, Jira/ADO activity",
                "status": available,
                "trigger": "POST /api/agents/standup/generate",
            },
            {
                "name": "blocker-detector",
                "description": "Detects implied blockers from stalled PRs, CI failures, dependency chains",
                "status": available,
                "trigger": "POST /api/agents/blockers/scan",
            },
            {
                "name": "health-coach",
                "description": "Correlates health signals and generates actionable sprint recommendations",
                "status": available,
                "trigger": "POST /api/agents/health/analyze",
            },
            {
                "name": "retro-synthesizer",
                "description": "Synthesizes sprint data into data-backed retrospective insights",
                "status": available,
                "trigger": "POST /api/agents/retro/generate",
            },
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/agents/standup/generate — run AI standup generation
# ---------------------------------------------------------------------------

@router.post("/agents/standup/generate")
async def generate_ai_standups(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate standup reports using the AI Standup Agent.

    The agent pulls data from GitHub, Jira/ADO, and health signals to
    generate rich standup reports with implied blocker detection.

    Falls back to deterministic generation if the agent service is not
    configured or the agent run fails.
    """
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="No organization_id in user context")

    from ..services.agents.standup_agent import run_standup_agent

    try:
        result = await run_standup_agent(db, org_id)
    except Exception as e:
        logger.error(f"Standup agent crashed: {e}", exc_info=True)
        from ..services.standup_generator import generate_all_standups
        result = await generate_all_standups(db, org_id)
        result["agent_used"] = False
        result["agent_error"] = f"Agent crashed: {str(e)[:200]}"

    # Broadcast WebSocket event
    try:
        await ws_manager.broadcast(
            org_id,
            {
                "type": "standup_generated",
                "agent_used": result.get("agent_used", False),
                "generated": result.get("generated", 0),
                "implied_blockers": result.get("implied_blockers", 0),
            },
        )
    except Exception:
        pass

    # Create in-app notification
    generated = result.get("generated", 0)
    if generated > 0:
        email = await _get_user_email(db, org_id, user)
        blockers = result.get("implied_blockers", 0)
        body_text = f"AI generated {generated} standup report(s)."
        if blockers > 0:
            body_text += f" {blockers} implied blocker(s) detected."
        if result.get("agent_used"):
            body_text += " (AI Agent)"

        await _create_notification(
            db, org_id, "agent_standup",
            title="Standup Reports Generated",
            body=body_text,
            recipient_email=email,
        )

    return result


# ---------------------------------------------------------------------------
# POST /api/agents/blockers/scan — run smart blocker detection
# ---------------------------------------------------------------------------

@router.post("/agents/blockers/scan")
async def scan_blockers(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Run the Smart Blocker Detection Agent.

    Scans for implied blockers: stalled work items, PR review bottlenecks,
    CI failures, dependency chains, and overloaded developers.
    Creates BlockerFlag records for newly detected blockers.
    """
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="No organization_id in user context")

    from ..services.agents.blocker_agent import run_blocker_agent

    try:
        result = await run_blocker_agent(db, org_id)
    except Exception as e:
        logger.error(f"Blocker agent crashed: {e}", exc_info=True)
        result = {
            "success": False,
            "error": f"Agent crashed: {str(e)[:200]}",
            "detected_blockers": [],
        }

    # Broadcast WebSocket event
    try:
        if result.get("success") and result.get("new_blockers_found", 0) > 0:
            await ws_manager.broadcast(
                org_id,
                {
                    "type": "blockers_detected",
                    "new_blockers": result.get("new_blockers_found", 0),
                    "severity_breakdown": result.get("severity_breakdown", {}),
                },
            )
    except Exception:
        pass

    # Create in-app notification
    if result.get("success"):
        new_count = result.get("new_blockers_found", 0)
        if new_count > 0:
            email = await _get_user_email(db, org_id, user)
            severity = result.get("severity_breakdown", {})
            high = severity.get("high", 0)
            body_text = f"AI detected {new_count} hidden blocker(s)."
            if high > 0:
                body_text += f" {high} HIGH severity — act now."
            body_text += f" {result.get('summary', '')[:120]}"

            await _create_notification(
                db, org_id, "agent_blocker",
                title=f"Smart Blocker Scan: {new_count} Found",
                body=body_text.strip(),
                recipient_email=email,
            )

    return result


# ---------------------------------------------------------------------------
# POST /api/agents/health/analyze — run sprint health coach
# ---------------------------------------------------------------------------

@router.post("/agents/health/analyze")
async def analyze_sprint_health(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Run the Sprint Health Coach Agent.

    Evaluates sprint pacing, individual developer risks, team-level patterns,
    and generates actionable recommendations with severity-based routing.
    """
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="No organization_id in user context")

    from ..services.agents.health_coach_agent import run_health_coach_agent

    try:
        result = await run_health_coach_agent(db, org_id)
    except Exception as e:
        logger.error(f"Health coach agent crashed: {e}", exc_info=True)
        result = {
            "success": False,
            "error": f"Agent crashed: {str(e)[:200]}",
            "recommendations": [],
        }

    # Broadcast WebSocket event
    try:
        if result.get("success"):
            await ws_manager.broadcast(
                org_id,
                {
                    "type": "health_analysis_complete",
                    "health_score": result.get("sprint_health_score"),
                    "health_label": result.get("sprint_health_label"),
                    "recommendations_count": result.get("total_recommendations", 0),
                },
            )
    except Exception:
        pass

    # Create in-app notification
    if result.get("success"):
        email = await _get_user_email(db, org_id, user)
        score = result.get("sprint_health_score", "?")
        label = result.get("sprint_health_label", "UNKNOWN")
        rec_count = result.get("total_recommendations", 0)
        summary = result.get("summary", "")[:150]

        await _create_notification(
            db, org_id, "agent_health",
            title=f"Sprint Health: {score}/100 ({label})",
            body=f"{rec_count} recommendation(s). {summary}",
            recipient_email=email,
        )

    return result


# ---------------------------------------------------------------------------
# POST /api/agents/retro/generate — generate AI retrospective
# ---------------------------------------------------------------------------

class RetroRequest(BaseModel):
    iteration_id: Optional[str] = None
    project_id: Optional[str] = None


@router.post("/agents/retro/generate")
async def generate_ai_retro(
    body: RetroRequest = RetroRequest(),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Run the AI Retrospective Synthesizer Agent.

    Generates a data-backed retrospective with:
    - What went well (evidence-based)
    - What didn't go well (with root causes)
    - Root cause classification
    - Recurring pattern detection from past retros
    - Specific action items with feed-forward constraints

    Saves the retrospective to the database and creates SprintConstraint
    records for feed-forward action items.
    """
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="No organization_id in user context")

    from ..services.agents.retro_agent import run_retro_agent

    try:
        result = await run_retro_agent(
            db, org_id,
            iteration_id=body.iteration_id,
            project_id=body.project_id,
        )
    except Exception as e:
        logger.error(f"Retro agent crashed: {e}", exc_info=True)
        result = {
            "success": False,
            "error": f"Agent crashed: {str(e)[:200]}",
        }

    # Broadcast WebSocket event
    try:
        if result.get("success"):
            await ws_manager.broadcast(
                org_id,
                {
                    "type": "retro_generated",
                    "retro_id": result.get("retro_id"),
                    "root_cause": result.get("root_cause"),
                    "action_items_count": result.get("action_items_count", 0),
                },
            )
    except Exception:
        pass

    # Create in-app notification
    if result.get("success"):
        email = await _get_user_email(db, org_id, user)
        root = result.get("root_cause", "N/A")
        actions = result.get("action_items_count", 0)
        summary = result.get("summary", "")[:150]

        await _create_notification(
            db, org_id, "agent_retro",
            title=f"AI Retrospective Ready",
            body=f"Root cause: {root}. {actions} action item(s). {summary}",
            recipient_email=email,
        )

    return result

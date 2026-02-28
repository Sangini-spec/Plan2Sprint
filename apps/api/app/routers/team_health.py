"""
GET  /api/team-health            — List active health signals
POST /api/team-health/evaluate   — Trigger signal evaluation for the org
POST /api/team-health/resolve    — Resolve (dismiss) a signal
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models import HealthSignal, TeamMember
from ..services.activity_engine import evaluate_all_signals

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/team-health")
async def get_team_health(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")

    query = (
        select(HealthSignal)
        .where(HealthSignal.organization_id == org_id)
        .where(HealthSignal.resolved_at.is_(None))
        .options(selectinload(HealthSignal.team_member))
        .order_by(HealthSignal.created_at.desc())
        .limit(50)
    )
    result = await db.execute(query)
    signals = result.scalars().all()

    signal_list = []
    for s in signals:
        signal_list.append({
            "id": s.id,
            "type": s.signal_type,
            "severity": s.severity,
            "member": s.team_member.display_name if s.team_member else "Unknown",
            "memberId": s.team_member_id,
            "message": s.message,
            "metadata": s.metadata_ or {},
            "createdAt": s.created_at.isoformat() if s.created_at else None,
        })

    return {"signals": signal_list}


@router.post("/team-health/evaluate")
async def trigger_evaluation(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger health signal evaluation for the org. Call after sync or periodically."""
    org_id = current_user.get("organization_id", "demo-org")

    try:
        signals = await evaluate_all_signals(db, org_id)
        return {
            "ok": True,
            "newSignals": len(signals),
            "signals": [
                {
                    "type": s.signal_type,
                    "severity": s.severity,
                    "message": s.message,
                }
                for s in signals
            ],
        }
    except Exception as e:
        logger.exception("Signal evaluation failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/team-health/resolve")
async def resolve_signal(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resolve (dismiss) a health signal."""
    signal_id = body.get("signalId")
    if not signal_id:
        raise HTTPException(status_code=400, detail="signalId is required")

    org_id = current_user.get("organization_id", "demo-org")
    result = await db.execute(
        select(HealthSignal).where(
            HealthSignal.id == signal_id,
            HealthSignal.organization_id == org_id,
        )
    )
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    signal.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}

"""
GET /api/integrations/audit-log
Returns audit log entries from the database for integration activity.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ...auth.supabase import get_current_user
from ...database import get_db
from ...models import AuditLogEntry

router = APIRouter()


@router.get("/audit-log")
async def get_audit_log(
    tool: str | None = Query(None),
    action: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")

    query = (
        select(AuditLogEntry)
        .where(AuditLogEntry.organization_id == org_id)
        .options(selectinload(AuditLogEntry.actor))
        .order_by(AuditLogEntry.created_at.desc())
    )

    if tool:
        query = query.where(AuditLogEntry.resource_type == tool)

    result = await db.execute(query)
    entries = result.scalars().all()

    entry_list = []
    for e in entries:
        entry_data = {
            "id": e.id,
            "eventType": e.event_type,
            "tool": e.resource_type,
            "action": f"{e.event_type}: {e.resource_id}",
            "timestamp": e.created_at.isoformat() if e.created_at else None,
            "actor": e.actor.full_name if e.actor and hasattr(e.actor, 'full_name') else "system",
            "success": e.success,
        }
        if action and action.lower() not in entry_data["action"].lower():
            continue
        entry_list.append(entry_data)

    return {"entries": entry_list[:limit], "total": len(entry_list)}

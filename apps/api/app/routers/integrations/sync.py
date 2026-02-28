"""
GET|POST /api/integrations/sync
Sync status and trigger for external tool data.
Queries ToolConnection table for sync status.

POST /api/integrations/sync/project  — full project sync (normalize + upsert)
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...auth.supabase import get_current_user
from ...database import get_db
from ...models import ToolConnection
from ...models.imported_project import ImportedProject
from ...adapters.sync import sync_project_data
from ...services.ws_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/sync")
async def get_sync_status(
    tool: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")

    query = (
        select(ToolConnection)
        .where(ToolConnection.organization_id == org_id)
    )
    if tool:
        query = query.where(ToolConnection.source_tool == tool.upper())

    result = await db.execute(query)
    connections = result.scalars().all()

    if connections:
        conn = connections[0]
        return {
            "tool": tool or conn.source_tool,
            "inProgress": conn.sync_status == "syncing",
            "lastSyncedAt": conn.last_sync_at.isoformat() if conn.last_sync_at else None,
        }

    return {
        "tool": tool,
        "inProgress": False,
        "lastSyncedAt": None,
    }


@router.post("/sync")
async def trigger_sync(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")
    tool = body.get("tool", "unknown")

    # Update sync status
    query = (
        select(ToolConnection)
        .where(ToolConnection.organization_id == org_id)
        .where(ToolConnection.source_tool == tool.upper())
    )
    result = await db.execute(query)
    conn = result.scalar_one_or_none()

    if conn:
        conn.sync_status = "idle"
        conn.last_sync_at = datetime.now(timezone.utc)
        await db.commit()

    return {"tool": tool, "status": "completed", "itemsSynced": 0}


@router.post("/sync/project")
async def sync_project(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Full project sync — normalize raw API data and upsert into the database.

    Body:
    {
        "projectId": "internal-cuid",     // imported_projects.id
        "sourceTool": "ADO" | "JIRA",
        "iterations": [...],               // raw API response arrays
        "members": [...],
        "workItems": [...]
    }
    """
    org_id = current_user.get("organization_id", "demo-org")
    project_id = body.get("projectId")
    source_tool = body.get("sourceTool", "ADO")

    if not project_id:
        raise HTTPException(status_code=400, detail="projectId is required")

    # Verify project belongs to this org
    result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == project_id,
            ImportedProject.organization_id == org_id,
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Mark sync in progress
    result = await db.execute(
        select(ToolConnection)
        .where(ToolConnection.organization_id == org_id)
        .where(ToolConnection.source_tool == source_tool.upper())
    )
    conn = result.scalar_one_or_none()
    if conn:
        conn.sync_status = "syncing"
        await db.flush()

    try:
        counts = await sync_project_data(
            db=db,
            org_id=org_id,
            project_id=project_id,
            source_tool=source_tool,
            raw_iterations=body.get("iterations"),
            raw_members=body.get("members"),
            raw_work_items=body.get("workItems"),
        )

        # Mark sync complete
        if conn:
            conn.sync_status = "idle"
            conn.last_sync_at = datetime.now(timezone.utc)
            await db.commit()

        # Trigger health signal evaluation after sync (fire-and-forget)
        try:
            from ...services.activity_engine import evaluate_all_signals
            await evaluate_all_signals(db, org_id)
        except Exception:
            logger.warning("Signal evaluation after sync failed (non-fatal)")

        # Broadcast sync_complete to all connected clients
        await ws_manager.broadcast(org_id, {
            "type": "sync_complete",
            "data": {
                "projectId": project_id,
                "sourceTool": source_tool,
                "synced": counts,
            },
        })

        return {
            "ok": True,
            "projectId": project_id,
            "sourceTool": source_tool,
            "synced": counts,
        }

    except Exception as e:
        logger.exception(f"Sync failed for project {project_id}")
        # Mark sync as failed
        if conn:
            conn.sync_status = "error"
            await db.commit()
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

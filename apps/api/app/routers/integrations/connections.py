"""
CRUD /api/integrations/connections
Manage tool connections (Jira, ADO, GitHub).
Queries real data from ToolConnection table.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...auth.supabase import get_current_user
from ...database import get_db
from ...config import settings
from ...models import ToolConnection

router = APIRouter()


@router.get("/connections")
async def list_connections(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")

    query = (
        select(ToolConnection)
        .where(ToolConnection.organization_id == org_id)
        .order_by(ToolConnection.created_at.desc())
    )
    result = await db.execute(query)
    connections = result.scalars().all()

    conn_list = []
    for c in connections:
        conn_list.append({
            "id": c.id,
            "tool": c.source_tool,
            "status": c.sync_status or "connected",
            "lastSyncAt": c.last_sync_at.isoformat() if c.last_sync_at else None,
            "connectedAt": c.created_at.isoformat() if c.created_at else None,
            "config": c.config or {},
        })

    return {"connections": conn_list}


@router.post("/connections", status_code=201)
async def create_connection(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tool = body.get("tool")
    config = body.get("config", {})
    org_id = current_user.get("organization_id", "demo-org")

    if tool == "ado":
        # ADO now uses OAuth 2.0 (Azure AD) — connections are created via
        # /api/integrations/ado/connect → /callback flow.
        # This endpoint is no longer used for ADO.
        raise HTTPException(
            status_code=400,
            detail="ADO uses OAuth flow via /api/integrations/ado/connect",
        )

    elif tool == "jira":
        # Jira now uses OAuth 2.0 (3LO) — connections are created via
        # /api/integrations/jira/connect → /callback flow.
        # This endpoint is no longer used for Jira.
        raise HTTPException(
            status_code=400,
            detail="Jira uses OAuth flow via /api/integrations/jira/connect",
        )

    elif tool == "github":
        if settings.is_demo_mode:
            return {
                "connection": {
                    "id": "conn-github-demo",
                    "tool": "github",
                    "status": "connected",
                    "connectedAt": "2026-02-21T00:00:00Z",
                }
            }
        raise HTTPException(
            status_code=400,
            detail="GitHub uses OAuth flow via /api/integrations/github/auth",
        )

    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


@router.get("/connections/{connection_id}")
async def get_connection(
    connection_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ToolConnection).where(ToolConnection.id == connection_id)
    result = await db.execute(query)
    conn = result.scalar_one_or_none()

    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    return {
        "id": conn.id,
        "tool": conn.source_tool,
        "status": conn.sync_status or "connected",
        "lastSyncAt": conn.last_sync_at.isoformat() if conn.last_sync_at else None,
        "connectedAt": conn.created_at.isoformat() if conn.created_at else None,
        "config": conn.config or {},
    }


@router.patch("/connections/{connection_id}")
async def update_connection(
    connection_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ToolConnection).where(ToolConnection.id == connection_id)
    result = await db.execute(query)
    conn = result.scalar_one_or_none()

    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    if "syncStatus" in body:
        conn.sync_status = body["syncStatus"]
    if "config" in body:
        conn.config = body["config"]
    await db.commit()

    return {"id": conn.id, "updated": True}


@router.delete("/connections/{connection_id}")
async def delete_connection(
    connection_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ToolConnection).where(ToolConnection.id == connection_id)
    result = await db.execute(query)
    conn = result.scalar_one_or_none()

    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    await db.delete(conn)
    await db.commit()

    return {"id": connection_id, "deleted": True}

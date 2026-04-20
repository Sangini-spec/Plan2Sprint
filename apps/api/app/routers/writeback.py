"""
POST /api/writeback       — Write back field changes to Jira or ADO
POST /api/writeback/undo  — Undo a write-back (within 60-min window)
GET  /api/writeback/log   — Recent write-back audit entries

Validates fields against frozen allowlists, records before/after state for
undo, and delegates to the tool-specific APIs (Jira REST / ADO PATCH).
"""

import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models.audit_log import AuditLogEntry
from ..models.tool_connection import ToolConnection
from ..services.writeback import validate_writeback_fields, build_writeback_payload
from ..services.ws_manager import ws_manager
from ..config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

UNDO_WINDOW_MINUTES = 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_connection(db: AsyncSession, org_id: str, tool: str) -> ToolConnection | None:
    result = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == tool.upper(),
        )
    )
    return result.scalar_one_or_none()


async def _execute_ado_writeback(
    conn: ToolConnection, item_id: str, fields: dict
) -> dict:
    """Call ADO REST API to patch a work item."""
    import httpx

    access_token = conn.access_token
    config = conn.config or {}
    org_url = config.get("orgUrl", config.get("base_url", ""))

    if not org_url:
        return {"success": False, "error": "No ADO organization URL configured"}

    patch_doc = [
        {"op": "replace", "path": f"/fields/{field}", "value": value}
        for field, value in fields.items()
    ]

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{org_url}/_apis/wit/workitems/{item_id}?api-version=7.0",
            json=patch_doc,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json-patch+json",
            },
            timeout=15,
        )
        if resp.status_code < 300:
            return {"success": True, "status": resp.status_code}
        return {"success": False, "status": resp.status_code, "error": resp.text[:200]}


async def _execute_jira_writeback(
    conn: ToolConnection, item_id: str, fields: dict
) -> dict:
    """Call Jira REST API to update an issue."""
    import httpx

    access_token = conn.access_token
    config = conn.config or {}
    cloud_id = config.get("cloudId", config.get("cloud_id", ""))
    base_url = f"https://api.atlassian.com/ex/jira/{cloud_id}" if cloud_id else ""

    if not base_url:
        return {"success": False, "error": "No Jira cloud ID configured"}

    # Map Plan2Sprint field names → Jira API field names
    jira_fields: dict = {}
    for field, value in fields.items():
        if field == "assignee":
            jira_fields["assignee"] = {"accountId": value}
        elif field == "story_points":
            jira_fields["customfield_10016"] = value
        elif field == "sprint_id":
            # Sprint assignment via Agile API (not regular issue update)
            pass  # Handled separately if needed
        else:
            jira_fields[field] = value

    if not jira_fields:
        return {"success": True, "status": 200, "message": "No fields to update"}

    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{base_url}/rest/api/3/issue/{item_id}",
            json={"fields": jira_fields},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if resp.status_code < 300:
            return {"success": True, "status": resp.status_code}
        return {"success": False, "status": resp.status_code, "error": resp.text[:200]}


# ---------------------------------------------------------------------------
# POST /api/writeback — Execute a write-back
# ---------------------------------------------------------------------------

@router.post("/writeback")
async def execute_writeback(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Write back field changes to an external tool.

    Body:
    {
        "tool": "jira" | "ado",
        "itemId": "PROJ-123" or "12345",
        "itemTitle": "Optional title for display",
        "fields": { "assignee": "user-id", "story_points": 5 },
        "previousValues": { "assignee": "old-user-id", "story_points": 3 }
    }
    """
    org_id = current_user.get("organization_id", "demo-org")
    user_id = current_user.get("id", "demo-user")
    user_role = current_user.get("role", "developer")

    tool = body.get("tool", "").lower()
    item_id = body.get("itemId", "")
    item_title = body.get("itemTitle", item_id)
    fields = body.get("fields", {})
    previous_values = body.get("previousValues", {})

    if tool not in ("jira", "ado"):
        raise HTTPException(status_code=400, detail="Tool must be 'jira' or 'ado'")

    if not item_id:
        raise HTTPException(status_code=400, detail="itemId is required")

    if not fields:
        raise HTTPException(status_code=400, detail="fields cannot be empty")

    # Validate fields against allowlist
    is_valid, disallowed = validate_writeback_fields(tool, fields)
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"Disallowed fields for {tool}: {', '.join(disallowed)}",
        )

    # Build audit payload
    payload = build_writeback_payload(tool, item_id, fields, previous_values)

    # Create audit log entry (before execution)
    audit_entry = AuditLogEntry(
        organization_id=org_id,
        actor_id=user_id,
        actor_role=user_role,
        event_type="writeback",
        resource_type=f"{tool}_work_item",
        resource_id=item_id,
        before_state=previous_values,
        after_state=fields,
        source_channel="api",
        success=False,  # Will be updated on success
        metadata_={
            "tool": tool,
            "itemTitle": item_title,
            "changes": payload["changes"],
            "undoable": True,
            "undoExpires": (datetime.now(timezone.utc) + timedelta(minutes=UNDO_WINDOW_MINUTES)).isoformat(),
        },
    )
    db.add(audit_entry)
    await db.flush()

    # Execute write-back
    result: dict = {"success": True}

    if settings.is_demo_mode:
        # Demo mode: simulate success
        result = {"success": True, "status": 200, "demo": True}
    else:
        conn = await _get_connection(db, org_id, tool)
        if not conn:
            raise HTTPException(
                status_code=404,
                detail=f"No {tool.upper()} connection found. Connect {tool.upper()} first.",
            )

        if tool == "ado":
            result = await _execute_ado_writeback(conn, item_id, fields)
        else:
            result = await _execute_jira_writeback(conn, item_id, fields)

    # Update audit entry
    audit_entry.success = result.get("success", False)
    if not result.get("success"):
        audit_entry.event_type = "writeback_failed"
        if audit_entry.metadata_:
            audit_entry.metadata_["error"] = result.get("error", "Unknown error")

    await db.commit()
    await db.refresh(audit_entry)

    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=f"Write-back failed: {result.get('error', 'Unknown error')}",
        )

    # Broadcast writeback success to all connected clients
    await ws_manager.broadcast(org_id, {
        "type": "writeback_success",
        "data": {
            "auditEntryId": audit_entry.id,
            "tool": tool,
            "itemId": item_id,
            "itemTitle": item_title,
            "changes": payload["changes"],
        },
    })

    return {
        "ok": True,
        "auditEntryId": audit_entry.id,
        "tool": tool,
        "itemId": item_id,
        "changes": payload["changes"],
        "undoAvailableUntil": (datetime.now(timezone.utc) + timedelta(minutes=UNDO_WINDOW_MINUTES)).isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /api/writeback/undo — Undo a write-back
# ---------------------------------------------------------------------------

@router.post("/writeback/undo")
async def undo_writeback(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Undo is no longer available — sprint plan sync now posts comments only,
    which are append-only and cannot be undone.
    """
    raise HTTPException(
        status_code=410,
        detail="Undo is not available for comment-based sync. "
               "AI recommendation comments are append-only and cannot be removed.",
    )


# ---------------------------------------------------------------------------
# GET /api/writeback/log — Recent write-back entries
# ---------------------------------------------------------------------------

@router.get("/writeback/log")
async def get_writeback_log(
    limit: int = 20,
    projectId: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return recent write-back audit log entries, optionally scoped to a project."""
    org_id = current_user.get("organization_id", "demo-org")

    filters = [
        AuditLogEntry.organization_id == org_id,
        AuditLogEntry.event_type.in_([
            "writeback", "writeback_failed", "writeback_undo", "writeback_undo_failed",
            "comment_posted", "comment_failed",
        ]),
    ]

    # Try project-scoped first, fall back to org-wide if no results
    if projectId:
        from ..models.work_item import WorkItem
        project_filters = [
            *filters,
            AuditLogEntry.resource_id.in_(
                select(WorkItem.id).where(WorkItem.imported_project_id == projectId).scalar_subquery()
            ),
        ]
        result = await db.execute(
            select(AuditLogEntry)
            .where(*project_filters)
            .order_by(AuditLogEntry.created_at.desc())
            .limit(limit)
        )
        entries = result.scalars().all()
        # If project filter returns nothing, show org-wide entries
        if not entries:
            result = await db.execute(
                select(AuditLogEntry)
                .where(*filters)
                .order_by(AuditLogEntry.created_at.desc())
                .limit(limit)
            )
            entries = result.scalars().all()
    else:
        result = await db.execute(
            select(AuditLogEntry)
            .where(*filters)
            .order_by(AuditLogEntry.created_at.desc())
            .limit(limit)
        )
        entries = result.scalars().all()

    return {
        "entries": [
            {
                "id": e.id,
                "eventType": e.event_type,
                "resourceType": e.resource_type,
                "resourceId": e.resource_id,
                "beforeState": e.before_state,
                "afterState": e.after_state,
                "success": e.success,
                "metadata": e.metadata_,
                "createdAt": e.created_at.isoformat() if e.created_at else None,
                "undoable": False,  # Comment-based sync is non-destructive, no undo needed
            }
            for e in entries
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/board/writeback — Write back board status changes to ADO/Jira
# ---------------------------------------------------------------------------

@router.post("/board/writeback")
async def board_writeback(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Write back board status changes to the connected external tool (ADO/Jira).

    Body:
    {
        "changes": [
            {
                "workItemId": "internal-p2s-id",
                "externalId": "12345" or "PROJ-123",
                "fromStatus": "TODO",
                "toStatus": "IN_PROGRESS",
                "title": "Item title for display"
            },
            ...
        ]
    }

    Detects the connected tool type and dispatches to the appropriate writeback.
    Only writes items that actually changed columns (caller filters unchanged items).
    """
    org_id = current_user.get("organization_id", "demo-org")

    changes = body.get("changes", [])
    if not changes:
        raise HTTPException(status_code=400, detail="No changes provided")

    # Detect which tool is connected
    conn = await _get_connection(db, org_id, "ado")
    tool = "ado" if conn else None

    if not tool:
        conn = await _get_connection(db, org_id, "jira")
        tool = "jira" if conn else None

    if not tool:
        raise HTTPException(
            status_code=404,
            detail="No ADO or Jira connection found. Connect a project management tool first.",
        )

    # Demo mode
    if settings.is_demo_mode:
        demo_results = [
            {"externalId": c.get("externalId", ""), "ok": True, "demo": True}
            for c in changes
        ]
        return {
            "ok": True,
            "tool": tool,
            "synced": len(changes),
            "failed": 0,
            "results": demo_results,
        }

    # Dispatch to tool-specific writeback
    if tool == "ado":
        from ..services.ado_writeback import writeback_board_statuses as ado_wb
        result = await ado_wb(db, org_id, changes, approver_id=current_user.get("id", "system"))
    else:
        from ..services.jira_writeback import writeback_board_statuses as jira_wb
        result = await jira_wb(db, org_id, changes, approver_id=current_user.get("id", "system"))

    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])

    # Broadcast success to all connected clients
    await ws_manager.broadcast(org_id, {
        "type": "board_writeback_success",
        "data": {
            "tool": tool,
            "synced": result.get("synced", 0),
            "failed": result.get("failed", 0),
            "changes": [
                {"externalId": c.get("externalId"), "from": c.get("fromStatus"), "to": c.get("toStatus")}
                for c in changes
            ],
        },
    })

    return {
        "ok": True,
        "tool": tool,
        "synced": result.get("synced", 0),
        "failed": result.get("failed", 0),
        "errors": result.get("errors", []),
        "results": result.get("results", []),
    }

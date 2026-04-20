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

        # Auto-complete expired sprints (date-based detection)
        try:
            from ...services.sprint_completion import check_and_complete_sprints
            completed = await check_and_complete_sprints(db, org_id, project_id)
            if completed:
                logger.info(
                    f"Auto-completed {len(completed)} sprint(s) after sync: "
                    + ", ".join(c["iterationName"] for c in completed)
                )
        except Exception:
            logger.warning("Sprint auto-completion after sync failed (non-fatal)")

        # Refresh sprint forecast after sync
        try:
            from ...services.sprint_forecast import refresh_forecast
            await refresh_forecast(db, org_id, project_id)
        except Exception:
            logger.warning("Forecast refresh after sync failed (non-fatal)")

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


@router.post("/sync/auto")
async def auto_sync_project(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Server-side auto-sync — calls existing ADO/Jira fetch functions internally
    using stored credentials (OAuth or PAT). No raw data needed from frontend.

    Body: { "projectId": "internal-cuid" }
    """
    org_id = current_user.get("organization_id", "demo-org")
    project_id = body.get("projectId")

    if not project_id:
        raise HTTPException(status_code=400, detail="projectId is required")

    # Get the project
    result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == project_id,
            ImportedProject.organization_id == org_id,
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    source_tool = (project.source_tool or "ado").upper()
    project_name = project.name
    # ADO: prefer external_id (GUID) for API calls — more reliable than name
    project_ado_ref = project.external_id or project_name
    project_key = getattr(project, "key", None) or project_name

    try:
        raw_iterations = []
        raw_members = []
        raw_work_items = []

        if source_tool == "ADO":
            # Reuse existing ADO fetch functions
            from .ado import (
                _get_ado_connection, _get_ado_auth_info,
                _get_valid_access_token, _ado_api,
            )

            conn = await _get_ado_connection(db, org_id)
            if not conn:
                raise HTTPException(status_code=400, detail="ADO not connected. Use Connect Tools first.")

            org_url, auth_header = _get_ado_auth_info(conn)
            config = conn.config or {}
            auth_method = config.get("auth_method", "oauth2")
            access_token = ""
            if auth_method == "oauth2":
                access_token = await _get_valid_access_token(db, conn)

            # Fetch iterations (use GUID ref for reliability)
            try:
                iter_data = await _ado_api(
                    "GET",
                    f"{org_url}/{project_ado_ref}/_apis/work/teamsettings/iterations?api-version=7.0",
                    access_token, auth_header=auth_header,
                )
                raw_iterations = iter_data.get("value", [])
            except Exception as e:
                logger.warning(f"Failed to fetch iterations: {e}")

            # Fetch team members
            try:
                teams_data = await _ado_api(
                    "GET",
                    f"{org_url}/_apis/projects/{project_ado_ref}/teams?api-version=7.0",
                    access_token, auth_header=auth_header,
                )
                teams = teams_data.get("value", [])
                if teams:
                    members_data = await _ado_api(
                        "GET",
                        f"{org_url}/_apis/projects/{project_ado_ref}/teams/{teams[0]['id']}/members?api-version=7.0",
                        access_token, auth_header=auth_header,
                    )
                    raw_members = members_data.get("value", [])
            except Exception as e:
                logger.warning(f"Failed to fetch team members: {e}")

            # Fetch work items via WIQL (use project name in WHERE clause — ADO requires it)
            try:
                wiql_data = await _ado_api(
                    "POST",
                    f"{org_url}/{project_ado_ref}/_apis/wit/wiql?api-version=7.0",
                    access_token,
                    json_body={
                        "query": (
                            f"SELECT [System.Id], [System.Title], [System.State], "
                            f"[System.WorkItemType], [System.AssignedTo], "
                            f"[Microsoft.VSTS.Scheduling.StoryPoints] "
                            f"FROM WorkItems "
                            f"WHERE [System.TeamProject] = '{project_name}' "
                            f"ORDER BY [System.WorkItemType] ASC, [System.Id] ASC"
                        ),
                    },
                    auth_header=auth_header,
                )
                wi_ids = [wi["id"] for wi in wiql_data.get("workItems", [])]

                # Fetch details in batches of 200
                for i in range(0, len(wi_ids), 200):
                    batch = wi_ids[i:i+200]
                    ids_str = ",".join(str(x) for x in batch)
                    details_data = await _ado_api(
                        "GET",
                        f"{org_url}/_apis/wit/workitems?ids={ids_str}&$expand=relations&api-version=7.0",
                        access_token, auth_header=auth_header,
                    )
                    raw_work_items.extend(details_data.get("value", []))
            except Exception as e:
                logger.warning(f"Failed to fetch work items: {e}")

        elif source_tool == "JIRA":
            # Reuse existing Jira fetch functions
            from .jira import _get_jira_connection, _get_valid_access_token as _get_valid_jira_token
            import httpx

            conn = await _get_jira_connection(db, org_id)
            if not conn:
                raise HTTPException(status_code=400, detail="Jira not connected. Use Connect Tools first.")

            access_token = await _get_valid_jira_token(db, conn)
            config = conn.config or {}
            cloud_id = config.get("cloud_id", "")

            if not cloud_id:
                raise HTTPException(status_code=400, detail="Jira cloud_id not configured")

            jira_headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }
            base_url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"

            async with httpx.AsyncClient(timeout=30.0) as client:
                # Fetch issues
                start_at = 0
                while True:
                    search_res = await client.get(
                        f"{base_url}/search",
                        headers=jira_headers,
                        params={
                            "jql": f"project={project_key} ORDER BY created ASC",
                            "maxResults": 100,
                            "startAt": start_at,
                            "fields": "summary,status,issuetype,assignee,priority,created,updated,customfield_10016,parent,sprint,labels,description"
                        }
                    )
                    if search_res.is_success:
                        data = search_res.json()
                        raw_work_items.extend(data.get("issues", []))
                        if start_at + 100 >= data.get("total", 0):
                            break
                        start_at += 100
                    else:
                        break

                # Fetch sprints from board
                agile_base = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/agile/1.0"
                boards_res = await client.get(
                    f"{agile_base}/board",
                    headers=jira_headers,
                    params={"projectKeyOrId": project_key}
                )
                if boards_res.is_success:
                    boards = boards_res.json().get("values", [])
                    for board in boards[:1]:
                        sprints_res = await client.get(
                            f"{agile_base}/board/{board['id']}/sprint",
                            headers=jira_headers
                        )
                        if sprints_res.is_success:
                            raw_iterations = sprints_res.json().get("values", [])

        logger.info(f"Auto-sync fetched: {len(raw_iterations)} iterations, {len(raw_members)} members, {len(raw_work_items)} work items for {project_name}")

        if not raw_work_items:
            return {"ok": True, "synced": {"workItems": 0, "iterations": 0, "members": 0}, "message": "No work items found from API"}

        # Run the standard sync pipeline
        counts = await sync_project_data(
            db=db,
            org_id=org_id,
            project_id=project_id,
            source_tool=source_tool.lower(),
            raw_iterations=raw_iterations,
            raw_members=raw_members,
            raw_work_items=raw_work_items,
        )

        # Update sync timestamp on tool connection
        conn_result = await db.execute(
            select(ToolConnection).where(
                ToolConnection.organization_id == org_id,
                ToolConnection.source_tool == source_tool,
            )
        )
        tool_conn = conn_result.scalar_one_or_none()
        if tool_conn:
            tool_conn.sync_status = "idle"
            tool_conn.last_sync_at = datetime.now(timezone.utc)
            await db.commit()

        await ws_manager.broadcast(org_id, {
            "type": "sync_complete",
            "data": {"projectId": project_id, "sourceTool": source_tool, "synced": counts},
        })

        return {"ok": True, "synced": counts}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Auto-sync failed for {project_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

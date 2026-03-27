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
    Server-side auto-sync — fetches data from ADO/Jira using stored credentials
    and imports into the database. No raw data needed from frontend.

    Body: { "projectId": "internal-cuid" }
    """
    import httpx

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

    # Get the tool connection with credentials
    conn_result = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == source_tool,
        )
    )
    tool_conn = conn_result.scalar_one_or_none()
    if not tool_conn or not tool_conn.access_token:
        raise HTTPException(status_code=400, detail=f"No {source_tool} connection found. Connect tools first.")

    config = tool_conn.config or {}
    raw_iterations = []
    raw_members = []
    raw_work_items = []

    try:
        if source_tool == "ADO":
            org_url = config.get("org_url", "")
            pat = tool_conn.access_token
            project_name = project.name
            import base64
            auth_header = "Basic " + base64.b64encode(f":{pat}".encode()).decode()
            headers = {"Authorization": auth_header, "Accept": "application/json"}

            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
                # Fetch iterations
                iter_res = await client.get(
                    f"{org_url}/{project_name}/_apis/work/teamsettings/iterations",
                    headers=headers, params={"api-version": "7.0"}
                )
                if iter_res.is_success:
                    raw_iterations = iter_res.json().get("value", [])

                # Fetch team members
                teams_res = await client.get(
                    f"{org_url}/_apis/projects/{project_name}/teams",
                    headers=headers, params={"api-version": "7.0"}
                )
                if teams_res.is_success:
                    teams = teams_res.json().get("value", [])
                    for team in teams[:1]:  # First team
                        members_res = await client.get(
                            f"{org_url}/_apis/projects/{project_name}/teams/{team['id']}/members",
                            headers=headers, params={"api-version": "7.0"}
                        )
                        if members_res.is_success:
                            raw_members = members_res.json().get("value", [])

                # Fetch work items via WIQL
                wiql_body = {
                    "query": f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{project_name}' ORDER BY [System.Id] ASC"
                }
                wiql_res = await client.post(
                    f"{org_url}/{project_name}/_apis/wit/wiql",
                    headers={**headers, "Content-Type": "application/json"},
                    json=wiql_body, params={"api-version": "7.0"}
                )
                if wiql_res.is_success:
                    wi_ids = [item["id"] for item in wiql_res.json().get("workItems", [])]
                    # Fetch details in batches of 200
                    for i in range(0, len(wi_ids), 200):
                        batch = wi_ids[i:i+200]
                        ids_str = ",".join(str(x) for x in batch)
                        detail_res = await client.get(
                            f"{org_url}/_apis/wit/workitems",
                            headers=headers,
                            params={
                                "ids": ids_str,
                                "api-version": "7.0",
                                "$expand": "relations",
                                "fields": "System.Id,System.Title,System.State,System.WorkItemType,System.AssignedTo,System.IterationPath,Microsoft.VSTS.Scheduling.StoryPoints,System.Description,System.CreatedDate,System.ChangedDate,System.Parent"
                            }
                        )
                        if detail_res.is_success:
                            raw_work_items.extend(detail_res.json().get("value", []))

        elif source_tool == "JIRA":
            # For Jira, use the stored OAuth token
            access_token = tool_conn.access_token
            cloud_id = config.get("cloud_id", "")
            if not cloud_id:
                raise HTTPException(status_code=400, detail="Jira cloud_id not configured")

            jira_headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }
            base_url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"
            project_key = project.key or project.name

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

        logger.info(f"Auto-sync fetched: {len(raw_iterations)} iterations, {len(raw_members)} members, {len(raw_work_items)} work items")

        if not raw_work_items:
            return {"ok": True, "synced": {"workItems": 0, "iterations": 0, "members": 0}, "message": "No work items found"}

        # Now run the standard sync pipeline
        counts = await sync_project_data(
            db=db,
            org_id=org_id,
            project_id=project_id,
            source_tool=source_tool.lower(),
            raw_iterations=raw_iterations,
            raw_members=raw_members,
            raw_work_items=raw_work_items,
        )

        # Update sync timestamp
        if tool_conn:
            tool_conn.sync_status = "idle"
            tool_conn.last_sync_at = datetime.now(timezone.utc)
            await db.commit()

        await ws_manager.broadcast(org_id, {
            "type": "sync_complete",
            "data": {"projectId": project_id, "sourceTool": source_tool, "synced": counts},
        })

        return {"ok": True, "synced": counts}

    except httpx.RequestError as e:
        logger.exception(f"Auto-sync HTTP error: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to reach {source_tool} API: {str(e)}")
    except Exception as e:
        logger.exception(f"Auto-sync failed: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

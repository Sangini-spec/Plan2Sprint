"""
ADO Data Fetch Service — refresh data from Azure DevOps before sprint generation.

Fetches the current iteration, work items, backlog items, and team members
for the selected project, normalizes them, and upserts into the database.

Returns a SprintContext object used by the sprint generation pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.imported_project import ImportedProject
from ..models.tool_connection import ToolConnection
from ..models.iteration import Iteration
from ..models.work_item import WorkItem
from ..models.team_member import TeamMember
from ..models.analytics import VelocityProfile
from ..adapters.normalizers import (
    normalize_ado_iteration,
    normalize_ado_team_member,
    normalize_ado_work_item,
)
from ..adapters.sync import upsert_team_members, upsert_iterations, upsert_work_items
from ..services.encryption import decrypt_token

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SprintContext dataclass — returned to the sprint generation pipeline
# ---------------------------------------------------------------------------

@dataclass
class SprintContext:
    iteration: dict | None = None
    iteration_db: Iteration | None = None
    backlog_items: list[WorkItem] = field(default_factory=list)
    current_sprint_items: list[WorkItem] = field(default_factory=list)
    team_members: list[TeamMember] = field(default_factory=list)
    velocity_profiles: list[VelocityProfile] = field(default_factory=list)
    project: ImportedProject | None = None
    source_tool: str = "ado"


# ---------------------------------------------------------------------------
# ADO API helpers (reused from router but service-level)
# ---------------------------------------------------------------------------

async def _get_ado_connection(db: AsyncSession, org_id: str) -> ToolConnection | None:
    result = await db.execute(
        select(ToolConnection)
        .where(ToolConnection.organization_id == org_id)
        .where(ToolConnection.source_tool == "ADO")
        .order_by(ToolConnection.created_at.desc())
    )
    return result.scalar_one_or_none()


def _get_auth_info(conn: ToolConnection) -> tuple[str, str | None]:
    """Return (org_url, auth_header_override)."""
    import base64
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")
    org_url = config.get("org_url", "")

    if auth_method == "pat":
        pat = decrypt_token(conn.access_token)
        auth_str = base64.b64encode(f":{pat}".encode()).decode()
        return org_url, f"Basic {auth_str}"
    return org_url, None


async def _refresh_access_token(db: AsyncSession, conn: ToolConnection) -> str:
    """Get valid access token, refreshing if needed."""
    from ..config import settings

    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "pat":
        return decrypt_token(conn.access_token)

    refresh_token = config.get("refresh_token")
    access_token = decrypt_token(conn.access_token)

    # Check token age
    token_age = None
    if config.get("token_updated_at"):
        try:
            updated = datetime.fromisoformat(config["token_updated_at"])
            token_age = (datetime.now(timezone.utc) - updated).total_seconds()
        except (ValueError, TypeError):
            pass

    if token_age and token_age > 3000 and refresh_token:
        ADO_RESOURCE_ID = "499b84ac-1321-427f-aa17-267ca6975798"
        ADO_SCOPE = f"{ADO_RESOURCE_ID}/.default offline_access"
        tenant_id = settings.ado_tenant_id or "common"
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    token_url,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": settings.ado_client_id,
                        "client_secret": settings.ado_client_secret,
                        "refresh_token": refresh_token,
                        "scope": ADO_SCOPE,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if res.status_code == 200:
                    from ..services.encryption import encrypt_token
                    tokens = res.json()
                    new_access = tokens["access_token"]
                    new_refresh = tokens.get("refresh_token", refresh_token)

                    conn.access_token = encrypt_token(new_access)
                    config["refresh_token"] = new_refresh
                    config["token_updated_at"] = datetime.now(timezone.utc).isoformat()
                    conn.config = config
                    await db.flush()
                    return new_access
        except Exception as e:
            logger.warning(f"Token refresh failed: {e}")

    return access_token


async def _ado_get(url: str, access_token: str, auth_header: str | None = None) -> dict:
    """Make authenticated GET request to ADO API."""
    headers = {
        "Authorization": auth_header or f"Bearer {access_token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.get(url, headers=headers)
        if res.is_error:
            logger.error(f"ADO GET {url} failed: {res.status_code} {res.text[:200]}")
            return {}
        return res.json()


async def _ado_post(url: str, access_token: str, body: dict, auth_header: str | None = None) -> dict:
    """Make authenticated POST request to ADO API."""
    headers = {
        "Authorization": auth_header or f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(url, headers=headers, json=body)
        if res.is_error:
            logger.error(f"ADO POST {url} failed: {res.status_code} {res.text[:200]}")
            return {}
        return res.json()


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT: fetch_sprint_context
# ---------------------------------------------------------------------------

async def fetch_sprint_context(
    db: AsyncSession,
    org_id: str,
    project_id: str,
) -> SprintContext:
    """
    Fetch all sprint-relevant data from ADO for the given project,
    normalize it, upsert into the database, and return a SprintContext.

    Steps:
      1. Get ADO connection and project metadata
      2. Fetch current iteration (sprint)
      3. Fetch work items in current iteration + backlog
      4. Fetch team members
      5. Normalize and upsert into DB
      6. Load velocity profiles from DB
      7. Return SprintContext
    """

    ctx = SprintContext()

    # 1. Get project and connection
    proj_result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == project_id,
            ImportedProject.organization_id == org_id,
        )
    )
    project = proj_result.scalar_one_or_none()
    if not project:
        logger.warning(f"Project {project_id} not found for org {org_id}")
        return ctx
    ctx.project = project

    conn = await _get_ado_connection(db, org_id)
    if not conn:
        logger.warning(f"No ADO connection for org {org_id}")
        return ctx

    org_url, auth_header = _get_auth_info(conn)
    if not org_url:
        logger.warning("No ADO org URL configured")
        return ctx

    access_token = await _refresh_access_token(db, conn)
    project_name = project.name

    logger.info(f"Fetching ADO sprint context for project '{project_name}' ({project_id})")

    # -----------------------------------------------------------------------
    # 2. Fetch current iteration
    # -----------------------------------------------------------------------
    try:
        iter_data = await _ado_get(
            f"{org_url}/{project_name}/_apis/work/teamsettings/iterations?$timeframe=current&api-version=7.1",
            access_token,
            auth_header,
        )
        raw_iterations = iter_data.get("value", [])

        if not raw_iterations:
            # Fallback: get all iterations and pick the current one
            all_iter_data = await _ado_get(
                f"{org_url}/{project_name}/_apis/work/teamsettings/iterations?api-version=7.1",
                access_token,
                auth_header,
            )
            raw_iterations = all_iter_data.get("value", [])

        if raw_iterations:
            # Normalize and upsert iterations
            normed_iters = [normalize_ado_iteration(it, org_id) for it in raw_iterations]
            iter_map = await upsert_iterations(db, normed_iters, org_id, project_id)

            # Find the current/active one
            current_iter = None
            for raw_it in raw_iterations:
                attrs = raw_it.get("attributes") or {}
                if attrs.get("timeFrame", "").lower() == "current":
                    current_iter = raw_it
                    break
            if not current_iter and raw_iterations:
                current_iter = raw_iterations[-1]  # latest

            if current_iter:
                ext_id = str(current_iter.get("id", ""))
                internal_iter_id = iter_map.get(ext_id)
                if internal_iter_id:
                    iter_db = await db.execute(
                        select(Iteration).where(Iteration.id == internal_iter_id)
                    )
                    ctx.iteration_db = iter_db.scalar_one_or_none()

                ctx.iteration = {
                    "id": ext_id,
                    "name": current_iter.get("name", ""),
                    "path": current_iter.get("path", ""),
                    "startDate": (current_iter.get("attributes") or {}).get("startDate"),
                    "finishDate": (current_iter.get("attributes") or {}).get("finishDate"),
                }
    except Exception as e:
        logger.error(f"Failed to fetch iterations: {e}")

    # -----------------------------------------------------------------------
    # 3. Fetch work items (current sprint + backlog)
    # -----------------------------------------------------------------------
    iteration_path = ctx.iteration.get("path", "") if ctx.iteration else ""
    raw_work_items: list[dict] = []

    try:
        # 3a. Work items in current sprint
        if iteration_path:
            wiql_sprint = await _ado_post(
                f"{org_url}/{project_name}/_apis/wit/wiql?api-version=7.1",
                access_token,
                {
                    "query": (
                        f"SELECT [System.Id] FROM WorkItems "
                        f"WHERE [System.TeamProject] = '{project_name}' "
                        f"AND [System.IterationPath] = '{iteration_path}' "
                        f"AND [System.WorkItemType] IN ('User Story','Bug','Task','Feature') "
                        f"AND [System.State] <> 'Removed' "
                        f"ORDER BY [Microsoft.VSTS.Common.Priority] ASC"
                    ),
                },
                auth_header,
            )
            sprint_ids = [wi["id"] for wi in wiql_sprint.get("workItems", [])][:200]

            if sprint_ids:
                details = await _ado_get(
                    f"{org_url}/_apis/wit/workitems?ids={','.join(str(i) for i in sprint_ids)}"
                    f"&fields=System.Id,System.Title,System.AssignedTo,System.State,"
                    f"System.WorkItemType,Microsoft.VSTS.Scheduling.StoryPoints,"
                    f"System.IterationPath,System.Description,System.Tags,"
                    f"Microsoft.VSTS.Common.Priority,Microsoft.VSTS.Common.AcceptanceCriteria,"
                    f"System.Parent,Microsoft.VSTS.Scheduling.StartDate,"
                    f"Microsoft.VSTS.Scheduling.TargetDate"
                    f"&api-version=7.1",
                    access_token,
                    auth_header,
                )
                raw_work_items.extend(details.get("value", []))

        # 3b. Backlog items (not in any sprint)
        wiql_backlog = await _ado_post(
            f"{org_url}/{project_name}/_apis/wit/wiql?api-version=7.1",
            access_token,
            {
                "query": (
                    f"SELECT [System.Id] FROM WorkItems "
                    f"WHERE [System.TeamProject] = '{project_name}' "
                    f"AND [System.IterationPath] = '{project_name}' "
                    f"AND [System.WorkItemType] IN ('User Story','Bug','Task','Feature') "
                    f"AND [System.State] NOT IN ('Closed','Resolved','Removed','Done') "
                    f"ORDER BY [Microsoft.VSTS.Common.Priority] ASC"
                ),
            },
            auth_header,
        )
        backlog_ids = [wi["id"] for wi in wiql_backlog.get("workItems", [])][:200]

        # Filter out IDs already fetched in sprint
        sprint_id_set = {wi.get("id") for wi in raw_work_items}
        backlog_ids = [i for i in backlog_ids if i not in sprint_id_set]

        if backlog_ids:
            backlog_details = await _ado_get(
                f"{org_url}/_apis/wit/workitems?ids={','.join(str(i) for i in backlog_ids)}"
                f"&fields=System.Id,System.Title,System.AssignedTo,System.State,"
                f"System.WorkItemType,Microsoft.VSTS.Scheduling.StoryPoints,"
                f"System.IterationPath,System.Description,System.Tags,"
                f"Microsoft.VSTS.Common.Priority,Microsoft.VSTS.Common.AcceptanceCriteria,"
                f"System.Parent,Microsoft.VSTS.Scheduling.StartDate,"
                f"Microsoft.VSTS.Scheduling.TargetDate"
                f"&api-version=7.1",
                access_token,
                auth_header,
            )
            raw_work_items.extend(backlog_details.get("value", []))

    except Exception as e:
        logger.error(f"Failed to fetch work items: {e}")

    # -----------------------------------------------------------------------
    # 4. Fetch team members
    # -----------------------------------------------------------------------
    raw_members: list[dict] = []
    try:
        teams_data = await _ado_get(
            f"{org_url}/_apis/projects/{project_name}/teams?api-version=7.1",
            access_token,
            auth_header,
        )
        teams = teams_data.get("value", [])
        seen_member_ids: set[str] = set()

        for team in teams[:5]:
            members_data = await _ado_get(
                f"{org_url}/_apis/projects/{project_name}/teams/{team['id']}/members?api-version=7.1",
                access_token,
                auth_header,
            )
            for m in members_data.get("value", []):
                identity = m.get("identity") or m
                mid = identity.get("id", "")
                if mid not in seen_member_ids:
                    seen_member_ids.add(mid)
                    raw_members.append(m)
    except Exception as e:
        logger.error(f"Failed to fetch team members: {e}")

    # -----------------------------------------------------------------------
    # 5. Normalize and upsert into DB
    # -----------------------------------------------------------------------
    try:
        # Team members
        normed_members = [normalize_ado_team_member(m, org_id) for m in raw_members]
        member_map = await upsert_team_members(db, normed_members, org_id)

        # We already upserted iterations above; get the iteration map
        iter_map: dict[str, str] = {}
        if ctx.iteration_db:
            iter_map[ctx.iteration_db.external_id] = ctx.iteration_db.id

        # Work items
        normed_items = [normalize_ado_work_item(wi, org_id) for wi in raw_work_items]
        await upsert_work_items(db, normed_items, org_id, member_map, iter_map, project_id)

        # Update ImportedProject synced_at
        project.synced_at = datetime.now(timezone.utc)
        await db.commit()

        logger.info(
            f"ADO sync: {len(normed_members)} members, "
            f"{len(normed_items)} work items upserted for project '{project_name}'"
        )
    except Exception as e:
        logger.error(f"Failed to sync ADO data: {e}")
        await db.rollback()

    # -----------------------------------------------------------------------
    # 6. Load data from DB for return
    # -----------------------------------------------------------------------
    # Team members
    tm_result = await db.execute(
        select(TeamMember).where(TeamMember.organization_id == org_id)
    )
    ctx.team_members = list(tm_result.scalars().all())

    # Work items split into current sprint vs backlog
    if ctx.iteration_db:
        sprint_items_result = await db.execute(
            select(WorkItem).where(
                WorkItem.organization_id == org_id,
                WorkItem.imported_project_id == project_id,
                WorkItem.iteration_id == ctx.iteration_db.id,
                WorkItem.status != "DONE",
                WorkItem.status != "CANCELLED",
            )
        )
        ctx.current_sprint_items = list(sprint_items_result.scalars().all())

    backlog_result = await db.execute(
        select(WorkItem).where(
            WorkItem.organization_id == org_id,
            WorkItem.imported_project_id == project_id,
            WorkItem.status.in_(["BACKLOG", "TODO"]),
        )
    )
    ctx.backlog_items = list(backlog_result.scalars().all())

    # Velocity profiles
    if ctx.team_members:
        tm_ids = [m.id for m in ctx.team_members]
        vp_result = await db.execute(
            select(VelocityProfile).where(
                VelocityProfile.team_member_id.in_(tm_ids)
            )
        )
        ctx.velocity_profiles = list(vp_result.scalars().all())

    ctx.source_tool = "ado"
    return ctx

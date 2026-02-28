"""
Jira integration router — OAuth 2.0 (3LO) flow.

Endpoints (all prefixed with /api/integrations/jira by main.py):
  GET  /connect        - Initiate Jira OAuth 2.0 3LO redirect
  GET  /callback       - Handle OAuth callback, exchange code for tokens, store in DB
  GET  /status         - Check Jira connection status for current org
  POST /disconnect     - Disconnect Jira (remove stored tokens)
  GET  /projects       - Fetch projects using stored OAuth token
  POST /projects       - Fetch projects (backward compat, uses stored token)
  POST /issues         - Fetch issues for a project
  POST /members        - Fetch assignable members for a project
  GET  /sprints        - List sprints for a board
  GET  /work-items     - List work items for a sprint
  POST /work-items     - Write-back fields to a Jira issue
  POST /webhooks       - Receive Jira webhook events
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.supabase import get_current_user
from ...config import settings
from ...database import get_db
from ...models.tool_connection import ToolConnection
from ...services.encryption import encrypt_token, decrypt_token
import httpx

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ATLASSIAN_AUTH_URL = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_API_BASE = "https://api.atlassian.com"

JIRA_SCOPES = "read:jira-work read:jira-user write:jira-work offline_access"

# In-memory CSRF state store (in production, use Redis or DB)
_oauth_states: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Write-back allowlist (frozen) -- mirrors writeback.ts
# ---------------------------------------------------------------------------
JIRA_WRITEBACK_ALLOWLIST: frozenset[str] = frozenset(
    ["assignee", "sprint_id", "story_points"]
)

# ---------------------------------------------------------------------------
# Mock data (for demo mode)
# ---------------------------------------------------------------------------
MOCK_JIRA_PROJECTS = [
    {"id": "jp-1", "key": "PROJ", "name": "Main Product", "projectType": "scrum", "avatarUrl": None},
    {"id": "jp-2", "key": "INFRA", "name": "Infrastructure", "projectType": "kanban", "avatarUrl": None},
    {"id": "jp-3", "key": "MOBILE", "name": "Mobile App", "projectType": "scrum", "avatarUrl": None},
    {"id": "jp-4", "key": "DESIGN", "name": "Design System", "projectType": "scrum", "avatarUrl": None},
]

MOCK_JIRA_SPRINTS = [
    {"id": "js-1", "name": "Sprint 24", "state": "active", "startDate": "2026-02-09T00:00:00Z", "endDate": "2026-02-23T00:00:00Z", "boardId": "board-1"},
    {"id": "js-2", "name": "Sprint 25", "state": "future", "startDate": "2026-02-23T00:00:00Z", "endDate": "2026-03-09T00:00:00Z", "boardId": "board-1"},
    {"id": "js-3", "name": "Sprint 23", "state": "closed", "startDate": "2026-01-26T00:00:00Z", "endDate": "2026-02-09T00:00:00Z", "boardId": "board-1"},
]

MOCK_JIRA_MEMBERS = [
    {"accountId": "1", "displayName": "Alex Kim", "emailAddress": "alex@demo.com"},
    {"accountId": "2", "displayName": "Sarah Chen", "emailAddress": "sarah@demo.com"},
    {"accountId": "3", "displayName": "Priya Patel", "emailAddress": "priya@demo.com"},
]

MOCK_JIRA_ISSUES = [
    {"id": "wi-1", "key": "PROJ-201", "summary": "Checkout flow step navigation", "status": "IN_PROGRESS", "issueType": "Story", "assignee": "Alex Chen", "storyPoints": 8},
    {"id": "wi-2", "key": "PROJ-202", "summary": "Payment gateway integration", "status": "IN_PROGRESS", "issueType": "Story", "assignee": "Sarah Kim", "storyPoints": 13},
    {"id": "wi-3", "key": "PROJ-203", "summary": "Cart summary component", "status": "TODO", "issueType": "Story", "assignee": "Marcus Johnson", "storyPoints": 5},
    {"id": "wi-4", "key": "PROJ-204", "summary": "Order confirmation email", "status": "TODO", "issueType": "Story", "assignee": "Emma Davis", "storyPoints": 5},
    {"id": "wi-5", "key": "PROJ-205", "summary": "Mobile responsive checkout", "status": "DONE", "issueType": "Bug", "assignee": "Alex Chen", "storyPoints": 3},
    {"id": "wi-6", "key": "PROJ-206", "summary": "Webhook signature verification", "status": "IN_PROGRESS", "issueType": "Story", "assignee": "Sarah Kim", "storyPoints": 5},
    {"id": "wi-7", "key": "PROJ-207", "summary": "Load balancer configuration", "status": "IN_PROGRESS", "issueType": "Task", "assignee": "Priya Patel", "storyPoints": 8},
    {"id": "wi-8", "key": "PROJ-208", "summary": "Address autocomplete", "status": "TODO", "issueType": "Story", "assignee": "James Wilson", "storyPoints": 5},
]

MOCK_WORK_ITEMS = [
    {"id": "jira-wi-1", "organizationId": "org-1", "externalId": "PROJ-201", "sourceTool": "JIRA", "title": "Checkout flow step navigation", "status": "IN_PROGRESS", "storyPoints": 8, "priority": 2, "type": "story", "labels": [], "iterationId": "iter-1"},
    {"id": "jira-wi-2", "organizationId": "org-1", "externalId": "PROJ-202", "sourceTool": "JIRA", "title": "Payment gateway integration", "status": "IN_PROGRESS", "storyPoints": 13, "priority": 1, "type": "story", "labels": [], "iterationId": "iter-1"},
    {"id": "jira-wi-3", "organizationId": "org-1", "externalId": "PROJ-203", "sourceTool": "JIRA", "title": "Cart summary component", "status": "TODO", "storyPoints": 5, "priority": 2, "type": "story", "labels": [], "iterationId": "iter-1"},
    {"id": "jira-wi-4", "organizationId": "org-1", "externalId": "PROJ-204", "sourceTool": "JIRA", "title": "Order confirmation email", "status": "TODO", "storyPoints": 5, "priority": 3, "type": "story", "labels": [], "iterationId": "iter-1"},
    {"id": "jira-wi-5", "organizationId": "org-1", "externalId": "PROJ-205", "sourceTool": "JIRA", "title": "Mobile responsive checkout", "status": "DONE", "storyPoints": 3, "priority": 2, "type": "bug", "labels": [], "iterationId": "iter-1"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_writeback(fields: dict) -> list[str]:
    """Return list of disallowed field names (empty if all valid)."""
    return [f for f in fields if f not in JIRA_WRITEBACK_ALLOWLIST]


async def _get_jira_connection(db: AsyncSession, org_id: str) -> ToolConnection | None:
    """Get the active Jira connection for an org."""
    query = (
        select(ToolConnection)
        .where(ToolConnection.organization_id == org_id)
        .where(ToolConnection.source_tool == "JIRA")
        .order_by(ToolConnection.created_at.desc())
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


def _get_auth_info(conn: ToolConnection) -> tuple[str, str | None, str]:
    """
    Return (base_url, auth_header_override, access_token) for a connection.
    - OAuth connections: base_url = api.atlassian.com/ex/jira/{cloud_id}, Bearer token
    - API token connections: base_url = site_url, Basic auth header
    """
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "api_token":
        site_url = config.get("site_url", "")
        email = config.get("email", "")
        api_token = decrypt_token(conn.access_token)
        auth_str = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        return site_url, f"Basic {auth_str}", api_token
    else:
        cloud_id = config.get("cloud_id", "")
        return f"{ATLASSIAN_API_BASE}/ex/jira/{cloud_id}", None, ""


async def _get_valid_access_token(db: AsyncSession, conn: ToolConnection) -> str:
    """
    Get a valid access token, refreshing if needed.
    Atlassian access tokens expire in 1 hour.
    """
    config = conn.config or {}
    refresh_token = config.get("refresh_token")

    # Try to use existing access token (check if we have expiry info)
    access_token = decrypt_token(conn.access_token)

    # If we have a refresh token, proactively refresh
    # (Atlassian tokens expire in 3600s; we refresh if it's been stored > 50 min)
    token_age = None
    if config.get("token_updated_at"):
        try:
            updated = datetime.fromisoformat(config["token_updated_at"])
            token_age = (datetime.now(timezone.utc) - updated).total_seconds()
        except (ValueError, TypeError):
            pass

    if token_age and token_age > 3000 and refresh_token:
        # Refresh the token
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    ATLASSIAN_TOKEN_URL,
                    json={
                        "grant_type": "refresh_token",
                        "client_id": settings.jira_client_id,
                        "client_secret": settings.jira_client_secret,
                        "refresh_token": refresh_token,
                    },
                )
                if res.status_code == 200:
                    tokens = res.json()
                    new_access = tokens["access_token"]
                    new_refresh = tokens.get("refresh_token", refresh_token)

                    # Update DB
                    conn.access_token = encrypt_token(new_access)
                    config["refresh_token"] = new_refresh
                    config["token_updated_at"] = datetime.now(timezone.utc).isoformat()
                    conn.config = config
                    await db.commit()

                    return new_access
        except Exception:
            pass  # Fall through to use existing token

    return access_token


async def _jira_api(
    method: str,
    url: str,
    access_token: str,
    json_body: dict | None = None,
    params: dict | None = None,
    auth_header: str | None = None,
) -> dict:
    """Make an authenticated Jira Cloud API request."""
    headers = {
        "Authorization": auth_header or f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        if method.upper() == "GET":
            res = await client.get(url, headers=headers, params=params)
        elif method.upper() == "POST":
            res = await client.post(url, headers=headers, json=json_body, params=params)
        elif method.upper() == "PUT":
            res = await client.put(url, headers=headers, json=json_body)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        if res.status_code == 401:
            raise HTTPException(status_code=401, detail="Jira token expired or invalid")
        if res.is_error:
            raise HTTPException(
                status_code=res.status_code,
                detail=f"Jira API error: {res.status_code} - {res.text[:200]}",
            )

        if res.status_code == 204:
            return {}
        return res.json()


# ===================================================================
# OAUTH 2.0 (3LO) FLOW
# ===================================================================

@router.get("/connect")
async def initiate_jira_oauth(
    current_user: dict = Depends(get_current_user),
):
    """
    GET /connect
    Redirect user to Atlassian OAuth consent screen.
    """
    if settings.is_demo_mode:
        return RedirectResponse(url=f"{settings.frontend_url}/po/notifications?jira=demo")

    client_id = settings.jira_client_id
    redirect_uri = settings.jira_redirect_uri

    if not client_id:
        raise HTTPException(status_code=500, detail="Jira OAuth not configured (missing client_id)")

    # Generate CSRF state
    state = str(uuid.uuid4())
    org_id = current_user.get("organization_id", "demo-org")
    user_id = current_user.get("id", "")
    _oauth_states[state] = {
        "user_id": user_id,
        "org_id": org_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    params = {
        "audience": "api.atlassian.com",
        "client_id": client_id,
        "scope": JIRA_SCOPES,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }

    authorize_url = f"{ATLASSIAN_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url=authorize_url)


@router.get("/callback")
async def jira_oauth_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /callback
    Handle Atlassian OAuth 2.0 callback.
    Exchange authorization code for access + refresh tokens, fetch cloud ID,
    store encrypted in DB, redirect to frontend.
    """
    # Handle errors
    if error:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?jira_error={error}"
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?jira_error=missing_params"
        )

    # Validate CSRF state
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?jira_error=invalid_state"
        )

    org_id = state_data["org_id"]

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Step 1: Exchange code for tokens
        try:
            token_res = await client.post(
                ATLASSIAN_TOKEN_URL,
                json={
                    "grant_type": "authorization_code",
                    "client_id": settings.jira_client_id,
                    "client_secret": settings.jira_client_secret,
                    "code": code,
                    "redirect_uri": settings.jira_redirect_uri,
                },
            )
            if token_res.is_error:
                error_detail = token_res.text[:200]
                return RedirectResponse(
                    url=f"{settings.frontend_url}/po/notifications?jira_error=token_exchange_failed"
                )
            tokens = token_res.json()
        except httpx.RequestError:
            return RedirectResponse(
                url=f"{settings.frontend_url}/po/notifications?jira_error=network_error"
            )

        access_token = tokens["access_token"]
        refresh_token = tokens.get("refresh_token", "")
        expires_in = tokens.get("expires_in", 3600)

        # Step 2: Get accessible resources (cloud IDs / sites)
        try:
            resources_res = await client.get(
                f"{ATLASSIAN_API_BASE}/oauth/token/accessible-resources",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resources_res.is_error:
                return RedirectResponse(
                    url=f"{settings.frontend_url}/po/notifications?jira_error=no_accessible_sites"
                )
            resources = resources_res.json()
        except httpx.RequestError:
            return RedirectResponse(
                url=f"{settings.frontend_url}/po/notifications?jira_error=network_error"
            )

    if not resources:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?jira_error=no_sites"
        )

    # Use the first accessible site
    site = resources[0]
    cloud_id = site.get("id", "")
    site_name = site.get("name", "Jira")
    site_url = site.get("url", "")

    # Step 3: Remove any existing Jira connection for this org
    existing = await _get_jira_connection(db, org_id)
    if existing:
        await db.delete(existing)
        await db.flush()

    # Step 4: Store connection with encrypted tokens
    conn = ToolConnection(
        organization_id=org_id,
        source_tool="JIRA",
        access_token=encrypt_token(access_token),
        sync_status="connected",
        config={
            "cloud_id": cloud_id,
            "site_name": site_name,
            "site_url": site_url,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "token_updated_at": datetime.now(timezone.utc).isoformat(),
            "auth_method": "oauth2",
        },
    )
    db.add(conn)
    await db.commit()

    # Redirect back to frontend
    return RedirectResponse(
        url=f"{settings.frontend_url}/po/notifications?jira=connected"
    )


# ===================================================================
# API TOKEN CONNECT (for shared / external Jira sites)
# ===================================================================

@router.post("/connect-token")
async def connect_with_api_token(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /connect-token
    Connect to a Jira site using email + API token (Basic Auth).
    Use this when connecting to a shared/external Jira site that the user
    doesn't own but has been given access to.

    Body: { "site_url": "https://company.atlassian.net", "email": "user@example.com", "api_token": "..." }
    """
    site_url = (body.get("site_url") or "").rstrip("/")
    email = body.get("email", "")
    api_token = body.get("api_token", "")

    if not site_url or not email or not api_token:
        raise HTTPException(
            status_code=400,
            detail="site_url, email, and api_token are required",
        )

    # Validate credentials by calling Jira API
    auth_str = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_str}",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            # Test connection — fetch server info
            res = await client.get(
                f"{site_url}/rest/api/3/myself",
                headers=headers,
            )
            if res.status_code in (401, 403):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid email or API token. Check your credentials and try again.",
                )
            if res.is_error:
                raise HTTPException(
                    status_code=400,
                    detail=f"Jira API error: {res.status_code}",
                )
            user_info = res.json()
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Could not reach Jira site: {str(e)}",
            )

    org_id = current_user.get("organization_id", "demo-org")

    # Extract site name from URL (e.g., "company" from "https://company.atlassian.net")
    site_name = site_url.replace("https://", "").replace(".atlassian.net", "").split(".")[0]

    # Discover cloud ID from site URL
    cloud_id = ""
    try:
        # For Atlassian Cloud, extract from server info
        server_res = await httpx.AsyncClient(timeout=10.0).__aenter__()
        try:
            info_res = await server_res.get(
                f"{site_url}/rest/api/3/serverInfo",
                headers=headers,
            )
            if info_res.status_code == 200:
                cloud_id = info_res.json().get("cloudId", "")
        finally:
            await server_res.aclose()
    except Exception:
        pass

    # Remove existing connection
    existing = await _get_jira_connection(db, org_id)
    if existing:
        await db.delete(existing)
        await db.flush()

    # Store connection with encrypted API token
    conn = ToolConnection(
        organization_id=org_id,
        source_tool="JIRA",
        access_token=encrypt_token(api_token),
        sync_status="connected",
        config={
            "cloud_id": cloud_id,
            "site_name": site_name,
            "site_url": site_url,
            "email": email,
            "display_name": user_info.get("displayName", ""),
            "auth_method": "api_token",
        },
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)

    return {
        "connected": True,
        "site_name": site_name,
        "site_url": site_url,
        "display_name": user_info.get("displayName", ""),
    }


# ===================================================================
# STATUS & DISCONNECT
# ===================================================================

@router.get("/status")
async def jira_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /status — Check if Jira is connected for the current org."""
    if settings.is_demo_mode:
        return {"connected": False, "demo": True}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)

    if not conn:
        return {"connected": False}

    config = conn.config or {}
    return {
        "connected": True,
        "site_name": config.get("site_name", "Jira"),
        "site_url": config.get("site_url", ""),
        "cloud_id": config.get("cloud_id", ""),
        "auth_method": config.get("auth_method", "basic"),
        "connected_at": conn.created_at.isoformat() if conn.created_at else None,
    }


@router.post("/disconnect")
async def disconnect_jira(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /disconnect — Remove Jira connection."""
    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)

    if not conn:
        return {"disconnected": True, "message": "No connection found"}

    await db.delete(conn)
    await db.commit()

    return {"disconnected": True}


# ===================================================================
# PROJECTS
# ===================================================================

@router.get("/projects")
async def list_projects(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /projects — Fetch Jira projects using stored credentials (OAuth or API token)."""
    if settings.is_demo_mode:
        return {"projects": MOCK_JIRA_PROJECTS}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Jira not connected")

    base_url, auth_header, _ = _get_auth_info(conn)
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    data = await _jira_api(
        "GET",
        f"{base_url}/rest/api/3/project/search",
        access_token,
        auth_header=auth_header,
    )

    projects = [
        {
            "id": str(p.get("id")),
            "key": str(p.get("key")),
            "name": str(p.get("name")),
            "projectType": str(p.get("projectTypeKey", "")),
            "avatarUrl": (p.get("avatarUrls") or {}).get("48x48"),
        }
        for p in data.get("values", [])
    ]
    return {"projects": projects}


@router.post("/projects")
async def fetch_projects(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /projects — backward-compatible, uses stored credentials."""
    if settings.is_demo_mode:
        return {"projects": MOCK_JIRA_PROJECTS}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Jira not connected")

    base_url, auth_header, _ = _get_auth_info(conn)
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    data = await _jira_api(
        "GET",
        f"{base_url}/rest/api/3/project/search",
        access_token,
        auth_header=auth_header,
    )

    projects = [
        {
            "id": str(p.get("id")),
            "key": str(p.get("key")),
            "name": str(p.get("name")),
            "projectType": str(p.get("projectTypeKey", "")),
            "avatarUrl": (p.get("avatarUrls") or {}).get("48x48"),
        }
        for p in data.get("values", [])
    ]
    return {"projects": projects}


# ===================================================================
# ISSUES
# ===================================================================

@router.post("/issues")
async def fetch_issues(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /issues — fetch issues for a Jira project using stored OAuth token."""
    project_key = body.get("projectKey")

    if settings.is_demo_mode:
        return {"issues": MOCK_JIRA_ISSUES}

    if not project_key:
        raise HTTPException(status_code=400, detail="projectKey is required")

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Jira not connected")

    base_url, auth_header, _ = _get_auth_info(conn)
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    jql = f'project = "{project_key}" ORDER BY updated DESC'

    # Jira deprecated /rest/api/3/search (410 Gone) — use new /search/jql endpoint (POST with JSON body)
    data = await _jira_api(
        "POST",
        f"{base_url}/rest/api/3/search/jql",
        access_token,
        json_body={
            "jql": jql,
            "maxResults": 200,
            "fields": [
                "summary", "status", "issuetype", "assignee",
                "priority", "customfield_10016", "sprint",
                "created", "updated", "labels",
            ],
        },
        auth_header=auth_header,
    )

    issues = [
        {
            "id": str(issue.get("id")),
            "key": str(issue.get("key")),
            "summary": (issue.get("fields") or {}).get("summary", ""),
            "status": ((issue.get("fields") or {}).get("status") or {}).get("name", ""),
            "issueType": ((issue.get("fields") or {}).get("issuetype") or {}).get("name", ""),
            "assignee": ((issue.get("fields") or {}).get("assignee") or {}).get("displayName"),
            "priority": ((issue.get("fields") or {}).get("priority") or {}).get("name"),
            "storyPoints": (issue.get("fields") or {}).get("customfield_10016"),
            "sprint": ((issue.get("fields") or {}).get("sprint") or {}).get("name"),
            "created": (issue.get("fields") or {}).get("created"),
            "updated": (issue.get("fields") or {}).get("updated"),
            "labels": (issue.get("fields") or {}).get("labels", []),
        }
        for issue in data.get("issues", [])
    ]
    return {"issues": issues}


# ===================================================================
# MEMBERS
# ===================================================================

@router.post("/members")
async def fetch_members(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /members — fetch assignable members for a Jira project."""
    project_key = body.get("projectKey")

    if settings.is_demo_mode:
        return {"members": MOCK_JIRA_MEMBERS}

    if not project_key:
        raise HTTPException(status_code=400, detail="projectKey is required")

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Jira not connected")

    base_url, auth_header, _ = _get_auth_info(conn)
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    try:
        data = await _jira_api(
            "GET",
            f"{base_url}/rest/api/3/user/assignable/search",
            access_token,
            params={"project": project_key, "maxResults": 200},
            auth_header=auth_header,
        )
    except HTTPException:
        return {"members": []}

    members = [
        {
            "accountId": u.get("accountId", ""),
            "displayName": u.get("displayName", ""),
            "emailAddress": u.get("emailAddress"),
            "avatarUrl": (u.get("avatarUrls") or {}).get("48x48"),
        }
        for u in (data if isinstance(data, list) else [])
    ]
    return {"members": members}


# ===================================================================
# SPRINTS
# ===================================================================

@router.get("/sprints")
async def list_sprints(
    boardId: str = Query("board-1"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /sprints?boardId=... — list sprints for a Jira board."""
    if settings.is_demo_mode:
        return {"sprints": MOCK_JIRA_SPRINTS}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)

    if not conn:
        return {"sprints": MOCK_JIRA_SPRINTS}

    # TODO: Implement real sprint fetch via Jira Agile API
    return {"sprints": MOCK_JIRA_SPRINTS}


# ===================================================================
# WORK ITEMS
# ===================================================================

@router.get("/work-items")
async def list_work_items(
    sprintId: str = Query("iter-1"),
    current_user: dict = Depends(get_current_user),
):
    """GET /work-items?sprintId=... — list Jira issues for a sprint."""
    if settings.is_demo_mode:
        return {"workItems": MOCK_WORK_ITEMS}
    return {"workItems": MOCK_WORK_ITEMS}


@router.post("/work-items")
async def writeback_work_item(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /work-items
    Write-back fields to a Jira issue.
    Only allowed fields: assignee, sprint_id, story_points
    """
    item_id = body.get("itemId")
    fields = body.get("fields")

    if not item_id or not fields or not isinstance(fields, dict):
        raise HTTPException(status_code=400, detail="Missing itemId or fields")

    # Validate against allowlist
    disallowed = _validate_writeback(fields)
    if disallowed:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Write-back denied: disallowed fields",
                "disallowedFields": disallowed,
                "allowedFields": list(JIRA_WRITEBACK_ALLOWLIST),
            },
        )

    if settings.is_demo_mode:
        return {"success": True, "itemId": item_id, "fields": fields}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Jira not connected")

    base_url, auth_header, _ = _get_auth_info(conn)
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    # Map our field names to Jira API field names
    jira_fields: dict = {}
    if "assignee" in fields:
        jira_fields["assignee"] = {"accountId": fields["assignee"]}
    if "story_points" in fields:
        jira_fields["customfield_10016"] = fields["story_points"]
    # sprint_id requires Jira Agile API — omit for now

    if jira_fields:
        await _jira_api(
            "PUT",
            f"{base_url}/rest/api/3/issue/{item_id}",
            access_token,
            json_body={"fields": jira_fields},
            auth_header=auth_header,
        )

    return {"success": True, "itemId": item_id, "fields": fields}


# ===================================================================
# WEBHOOKS
# ===================================================================

@router.post("/webhooks")
async def receive_webhook(request: Request):
    """
    POST /webhooks
    Receive Jira webhook events.
    """
    try:
        body_bytes = await request.body()
        body_text = body_bytes.decode("utf-8")

        import json
        payload = json.loads(body_text)
        event_type = payload.get("webhookEvent") or payload.get("event_type") or "unknown"

        if event_type == "jira:issue_updated":
            pass  # TODO: Normalize and update local WorkItem
        elif event_type in ("sprint_started", "sprint_closed"):
            pass  # TODO: Update local Iteration

        return {
            "received": True,
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        raise HTTPException(status_code=500, detail="Webhook processing failed")

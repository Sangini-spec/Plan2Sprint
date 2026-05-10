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
import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.supabase import get_current_user, require_po
from ...config import settings
from ...database import get_db
from ...models.tool_connection import ToolConnection
from ...services.encryption import encrypt_token, decrypt_token
import httpx

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ATLASSIAN_AUTH_URL = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_API_BASE = "https://api.atlassian.com"

JIRA_SCOPES = "read:jira-work read:jira-user write:jira-work read:board-scope:jira-software read:sprint:jira-software offline_access"

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


async def _get_valid_access_token(
    db: AsyncSession, conn: ToolConnection, *, force_refresh: bool = False,
) -> str:
    """
    Get a valid access token, refreshing if needed.
    Atlassian access tokens expire in 1 hour.
    When *force_refresh* is True the refresh is attempted regardless of age
    (used for retry-on-401).
    """
    config = conn.config or {}
    refresh_token = config.get("refresh_token")

    # Decrypt the currently stored access token
    access_token = decrypt_token(conn.access_token)

    # Determine token age
    token_age: float | None = None
    if config.get("token_updated_at"):
        try:
            updated = datetime.fromisoformat(config["token_updated_at"])
            token_age = (datetime.now(timezone.utc) - updated).total_seconds()
        except (ValueError, TypeError):
            logger.warning("Jira: could not parse token_updated_at=%s", config.get("token_updated_at"))

    should_refresh = force_refresh or (token_age is not None and token_age > 3000)

    if should_refresh and refresh_token:
        logger.info(
            "Jira token refresh: age=%s force=%s client_id_present=%s",
            token_age, force_refresh, bool(settings.jira_client_id),
        )
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

                    # Update DB — use dict copy so SQLAlchemy detects the mutation
                    conn.access_token = encrypt_token(new_access)
                    conn.config = {
                        **config,
                        "refresh_token": new_refresh,
                        "token_updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    await db.commit()

                    logger.info("Jira token refreshed successfully")
                    return new_access
                else:
                    logger.warning(
                        "Jira token refresh failed: status=%s body=%s",
                        res.status_code, res.text[:300],
                    )
        except Exception as exc:
            logger.warning("Jira token refresh error: %s", exc)
    elif should_refresh and not refresh_token:
        logger.warning("Jira token needs refresh but no refresh_token is stored")

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
    auth_type = "override" if auth_header else "Bearer"
    logger.info("Jira API %s %s auth=%s", method, url, auth_type)

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
            logger.warning("Jira API 401: %s %s — %s", method, url, res.text[:200])
            raise HTTPException(status_code=401, detail="Jira token expired or invalid")
        if res.is_error:
            logger.warning("Jira API error: %s %s — %s %s", method, url, res.status_code, res.text[:200])
            raise HTTPException(
                status_code=res.status_code,
                detail=f"Jira API error: {res.status_code} - {res.text[:200]}",
            )

        logger.info("Jira API %s %s → %s", method, url, res.status_code)
        if res.status_code == 204:
            return {}
        return res.json()


async def _jira_request_with_retry(
    db: AsyncSession,
    conn: ToolConnection,
    method: str,
    url: str,
    auth_header: str | None = None,
    json_body: dict | None = None,
    params: dict | None = None,
) -> dict:
    """
    Make a Jira API request.  For OAuth connections, if the first attempt
    returns 401 we force-refresh the token and retry exactly once.
    """
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    try:
        return await _jira_api(
            method, url, access_token,
            json_body=json_body, params=params, auth_header=auth_header,
        )
    except HTTPException as exc:
        if exc.status_code == 401 and auth_method == "oauth2":
            logger.info("Jira 401 — retrying with force-refreshed token")
            access_token = await _get_valid_access_token(
                db, conn, force_refresh=True,
            )
            return await _jira_api(
                method, url, access_token,
                json_body=json_body, params=params, auth_header=auth_header,
            )
        raise


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
    # Hotfix 79 — reverted the require_po gate added in Hotfix 69B.
    # See ado.py /connect for the full note. Devs and POs both can
    # initiate Jira OAuth.
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
        # Hotfix 53 — was ``prompt=consent``. That re-shows the scopes
        # screen but does NOT force the account picker, so users with an
        # existing Atlassian session in the browser silently get
        # connected as whichever email they happened to be logged in as.
        # ``prompt=login`` forces re-authentication so the user explicitly
        # chooses which Atlassian account to authorise — matches the
        # "I have multiple Atlassian accounts and need to pick the right
        # one" UX every PO has run into.
        "prompt": "login",
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
    # Hotfix 79 — reverted the require_po gate (see /connect note).
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

    # Hotfix 80 — see ado.py for the full note. Non-PO get the
    # connected boolean (so the Connect Tools modal updates after
    # they complete OAuth) but no management metadata.
    is_po = (current_user.get("role") or "").lower() in {"product_owner", "admin", "owner"}
    if not is_po:
        return {"connected": conn is not None}

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
        "selectedProjects": config.get("selectedProjects", []),
    }


@router.post("/selected-projects")
async def save_selected_projects_jira(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /selected-projects — Persist user's selected Jira projects in connection config."""
    require_po(current_user)  # Hotfix 68B — write to org connection state
    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Jira not connected")

    config = dict(conn.config or {})
    config["selectedProjects"] = body.get("projects", [])
    conn.config = config
    await db.commit()
    return {"ok": True}


@router.post("/disconnect")
async def disconnect_jira(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /disconnect — Remove Jira connection."""
    require_po(current_user)  # Hotfix 68B — destructive on org connection
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
    # Hotfix 81 — reverted the require_po gate. See ado.py for the
    # full note. Devs OAuth their own Atlassian accounts now, so the
    # stored tokens identify the caller and the project list is
    # appropriately scoped without role-gating.
    if settings.is_demo_mode:
        return {"projects": MOCK_JIRA_PROJECTS}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Jira not connected")

    base_url, auth_header, _ = _get_auth_info(conn)

    data = await _jira_request_with_retry(
        db, conn, "GET",
        f"{base_url}/rest/api/3/project/search",
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

    data = await _jira_request_with_retry(
        db, conn, "GET",
        f"{base_url}/rest/api/3/project/search",
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

    jql = f'project = "{project_key}" ORDER BY updated DESC'

    # Jira deprecated /rest/api/3/search (410 Gone) — use new /search/jql endpoint (POST with JSON body)
    data = await _jira_request_with_retry(
        db, conn, "POST",
        f"{base_url}/rest/api/3/search/jql",
        auth_header=auth_header,
        json_body={
            "jql": jql,
            "maxResults": 200,
            "fields": [
                "summary", "status", "issuetype", "assignee",
                "priority", "customfield_10016", "customfield_10028",
                "customfield_10102", "sprint", "parent",
                "created", "updated", "labels",
            ],
        },
    )

    issues = []
    for issue in data.get("issues", []):
        f = issue.get("fields") or {}
        sprint_obj = f.get("sprint") or {}
        status_obj = f.get("status") or {}
        assignee_obj = f.get("assignee") or {}
        issues.append({
            "id": str(issue.get("id")),
            "key": str(issue.get("key")),
            "summary": f.get("summary", ""),
            "status": status_obj.get("name", ""),
            "statusCategory": (status_obj.get("statusCategory") or {}).get("key", ""),
            "issueType": (f.get("issuetype") or {}).get("name", ""),
            "assignee": assignee_obj.get("displayName"),
            "assigneeAccountId": assignee_obj.get("accountId"),
            "priority": (f.get("priority") or {}).get("name"),
            "storyPoints": f.get("customfield_10016") or f.get("customfield_10028") or f.get("customfield_10102"),
            "sprint": sprint_obj.get("name") if sprint_obj else None,
            "sprintId": sprint_obj.get("id") if sprint_obj else None,
            "created": f.get("created"),
            "updated": f.get("updated"),
            "labels": f.get("labels", []),
            "parentKey": (f.get("parent") or {}).get("key"),
            # Preserve raw fields for normalizer (used by sync)
            "fields": f,
        })
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

    try:
        data = await _jira_request_with_retry(
            db, conn, "GET",
            f"{base_url}/rest/api/3/user/assignable/search",
            auth_header=auth_header,
            params={"project": project_key, "maxResults": 200},
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

@router.post("/sprints")
async def list_sprints_post(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /sprints — list sprints for a Jira project (finds board automatically)."""
    if settings.is_demo_mode:
        return {"sprints": MOCK_JIRA_SPRINTS}

    project_key = body.get("projectKey")
    if not project_key:
        raise HTTPException(status_code=400, detail="projectKey is required")

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Jira not connected")

    base_url, auth_header, _ = _get_auth_info(conn)
    config = conn.config or {}
    cloud_id = config.get("cloud_id", "")
    auth_method = config.get("auth_method", "oauth2")
    site_url = config.get("site_url", "")

    # Agile API requires granular scopes (read:board-scope:jira-software) that
    # must be registered in the Atlassian developer console. As a fallback, use
    # a stored API token with basic auth for direct site URL calls.

    # Build basic auth header from stored agile API token if available
    agile_api_token = config.get("agile_api_token")
    agile_email = config.get("agile_email")
    agile_basic_header = None
    if agile_api_token and agile_email and site_url:
        agile_auth_str = base64.b64encode(f"{agile_email}:{agile_api_token}".encode()).decode()
        agile_basic_header = f"Basic {agile_auth_str}"

    async def _agile_get(path: str, params: dict | None = None) -> dict | None:
        """Try agile API call with multiple auth methods."""
        attempts = []

        if auth_method == "api_token":
            attempts.append((f"{site_url}/rest/agile/1.0{path}", auth_header))
        else:
            # Try OAuth first
            attempts.append((f"{ATLASSIAN_API_BASE}/ex/jira/{cloud_id}/rest/agile/1.0{path}", None))
            # Fallback: use stored API token with basic auth via site URL
            if agile_basic_header and site_url:
                attempts.append((f"{site_url}/rest/agile/1.0{path}", agile_basic_header))

        for url, override_auth in attempts:
            try:
                return await _jira_request_with_retry(
                    db, conn, "GET", url,
                    auth_header=override_auth,
                    params=params,
                )
            except HTTPException as e:
                logger.warning(f"Agile API {path} failed at {url}: {e.status_code}")
                continue
        return None

    # Step 1: Find the board
    boards_data = await _agile_get("/board", params={"projectKeyOrId": project_key, "maxResults": 1})
    if not boards_data or not boards_data.get("values"):
        logger.info(f"No boards found for project {project_key}")
        return {"sprints": []}

    board_id = boards_data["values"][0]["id"]

    # Step 2: Fetch sprints for the board
    sprints_data = await _agile_get(f"/board/{board_id}/sprint", params={"maxResults": 50})
    if not sprints_data:
        logger.warning(f"Failed to fetch sprints for board {board_id}")
        return {"sprints": []}

    sprints = [
        {
            "id": s.get("id"),
            "name": s.get("name", ""),
            "state": s.get("state", "future"),
            "startDate": s.get("startDate"),
            "endDate": s.get("endDate"),
            "completeDate": s.get("completeDate"),
            "goal": s.get("goal"),
        }
        for s in sprints_data.get("values", [])
    ]

    # Also fetch issue-sprint mappings for each sprint so we can associate them
    sprint_issue_map = {}
    for sprint in sprints:
        sid = sprint["id"]
        issues_data = await _agile_get(f"/sprint/{sid}/issue", params={"maxResults": 200, "fields": "key"})
        if issues_data:
            keys = [i.get("key") for i in issues_data.get("issues", []) if i.get("key")]
            sprint_issue_map[str(sid)] = keys

    return {"sprints": sprints, "sprintIssueMap": sprint_issue_map}


@router.get("/sprints")
async def list_sprints_get(
    boardId: str = Query("board-1"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /sprints?boardId=... — list sprints for a Jira board (legacy)."""
    if settings.is_demo_mode:
        return {"sprints": MOCK_JIRA_SPRINTS}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)

    if not conn:
        return {"sprints": MOCK_JIRA_SPRINTS}

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

    # Map our field names to Jira API field names
    jira_fields: dict = {}
    if "assignee" in fields:
        jira_fields["assignee"] = {"accountId": fields["assignee"]}
    if "story_points" in fields:
        jira_fields["customfield_10016"] = fields["story_points"]
    # sprint_id requires Jira Agile API — omit for now

    if jira_fields:
        await _jira_request_with_retry(
            db, conn, "PUT",
            f"{base_url}/rest/api/3/issue/{item_id}",
            auth_header=auth_header,
            json_body={"fields": jira_fields},
        )

    return {"success": True, "itemId": item_id, "fields": fields}


# ===================================================================
# BOARD COLUMNS
# ===================================================================

@router.post("/board-columns")
async def fetch_board_columns(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /board-columns — fetch board column configuration for a Jira board."""
    board_id = body.get("boardId")

    if settings.is_demo_mode:
        return {
            "columns": [
                {"id": "todo", "name": "TO DO", "order": 0, "category": "new", "statuses": []},
                {"id": "inprogress", "name": "IN PROGRESS", "order": 1, "category": "indeterminate", "statuses": []},
                {"id": "done", "name": "DONE", "order": 2, "category": "done", "statuses": []},
            ]
        }

    if not board_id:
        raise HTTPException(status_code=400, detail="boardId is required")

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_jira_connection(db, org_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Jira not connected")

    base_url, auth_header, _ = _get_auth_info(conn)

    try:
        # Jira Agile API: board configuration
        data = await _jira_request_with_retry(
            db, conn, "GET",
            f"{base_url}/rest/agile/1.0/board/{board_id}/configuration",
            auth_header=auth_header,
        )

        column_config = data.get("columnConfig", {})
        raw_columns = column_config.get("columns", [])

        columns = [
            {
                "id": col.get("name", "").lower().replace(" ", "_"),
                "name": col.get("name", ""),
                "order": idx,
                "category": "done" if col.get("name", "").upper() == "DONE" else
                           "new" if col.get("name", "").upper() in ("TO DO", "TODO", "BACKLOG") else
                           "indeterminate",
                "statuses": [s.get("id", "") for s in col.get("statuses", [])],
            }
            for idx, col in enumerate(raw_columns)
        ]
        return {"columns": columns}

    except Exception:
        # Fallback to 3-column default
        return {
            "columns": [
                {"id": "todo", "name": "TO DO", "order": 0, "category": "new", "statuses": []},
                {"id": "inprogress", "name": "IN PROGRESS", "order": 1, "category": "indeterminate", "statuses": []},
                {"id": "done", "name": "DONE", "order": 2, "category": "done", "statuses": []},
            ]
        }


# ===================================================================
# WEBHOOKS
# ===================================================================

@router.post("/webhooks")
async def receive_webhook(request: Request):
    """
    POST /webhooks
    Receive Jira webhook events.

    Hotfix 80 — webhook security hardening:
      - HMAC-SHA256 verification via the X-Atlassian-Webhook-Signature header.
      - Constant-time compare via ``services.webhook_security``.
      - When ``strict_webhook_verification`` is on, requests without a
        configured secret are rejected (parallels GitHub's strict mode).
      - The signature check runs OUTSIDE the broad try/except so the 401
        propagates back to the sender instead of being swallowed as a 500.
    """
    import logging as _logging
    from ...services.webhook_security import (
        verify_hmac_sha256,
        is_strict_mode_enabled,
    )
    _log = _logging.getLogger(__name__)

    body_bytes = await request.body()

    # ---- Signature verification (must NOT be inside the broad try/except) ----
    webhook_secret = getattr(settings, "jira_webhook_secret", "") or ""
    signature = request.headers.get("X-Atlassian-Webhook-Signature", "")
    strict_mode = is_strict_mode_enabled() or settings.strict_webhook_verification

    if webhook_secret:
        if not verify_hmac_sha256(body_bytes, signature, webhook_secret):
            _log.warning("[SECURITY] Jira webhook signature MISMATCH — rejecting")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    elif strict_mode:
        _log.warning(
            "[SECURITY] Jira webhook REJECTED (strict mode) — JIRA_WEBHOOK_SECRET "
            "is not configured."
        )
        raise HTTPException(
            status_code=401, detail="Webhook signing secret not configured"
        )
    else:
        _log.warning(
            "[SECURITY] Jira webhook accepted UNVERIFIED — JIRA_WEBHOOK_SECRET "
            "is not configured. Set it and STRICT_WEBHOOK_VERIFICATION=true to lock down."
        )

    # ---- Payload processing (broader catch for parse / handler errors) ----
    try:
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
    except HTTPException:
        raise
    except Exception:
        _log.exception("Jira webhook processing failed")
        raise HTTPException(status_code=500, detail="Webhook processing failed")

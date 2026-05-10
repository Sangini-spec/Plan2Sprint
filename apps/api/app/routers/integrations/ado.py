"""
Azure DevOps integration router — Azure AD OAuth 2.0 flow.

Endpoints (all prefixed with /api/integrations/ado by main.py):
  GET  /connect        - Initiate Azure AD OAuth redirect
  GET  /callback       - Handle OAuth callback, exchange code, store tokens
  GET  /status         - Check ADO connection status
  POST /disconnect     - Remove ADO connection
  GET  /projects       - Fetch projects using stored OAuth token
  POST /projects       - Fetch projects (backward compat)
  GET  /iterations     - List iterations (demo mock)
  POST /iterations     - Fetch real iterations
  GET  /work-items     - List work items (demo mock)
  POST /work-items     - Fetch by project OR write-back fields
  POST /team-members   - Fetch team members for a project
  POST /webhooks       - Receive ADO service hook events
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


def _detect_pat_failure_reason(response) -> str | None:
    """Inspect ADO's HTML error body to figure out *specifically* why PAT
    auth failed. Returns one of:

      "expired"   — token is past its expiry date
      "scope"     — token is valid but lacks required permissions
      "not_found" — the org URL itself doesn't exist
      None        — body did not contain a recognised signature (caller
                    falls back to a generic message)

    ADO consistently returns an HTML page on auth failures whose <title>
    + body text reveal the cause. Examples seen in the wild:

      Expired:   <title>Access Denied: The Personal Access Token used has expired.</title>
      Wrong org: 404 with title "The resource cannot be found."
      No scope:  401 with phrasing about insufficient permissions

    We lower-case the body and look for stable substrings — Microsoft
    occasionally tweaks the wording but the core phrases stay constant.
    """
    try:
        body = (response.text or "").lower()
    except Exception:
        return None

    if (
        "personal access token used has expired" in body
        or "the token has expired" in body
        or "pat has expired" in body
    ):
        return "expired"
    if (
        "the resource cannot be found" in body
        or "404 - page not found" in body
    ):
        return "not_found"
    if (
        "does not have permission" in body
        or "is not authorized" in body
        or "insufficient permission" in body
    ):
        return "scope"
    return None


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

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Azure DevOps resource ID for OAuth scope
ADO_RESOURCE_ID = "499b84ac-1321-427f-aa17-267ca6975798"
ADO_SCOPE = f"{ADO_RESOURCE_ID}/.default offline_access"

# In-memory CSRF state store (in production, use Redis or DB)
_oauth_states: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Write-back allowlist (frozen) -- mirrors writeback.ts
# ---------------------------------------------------------------------------
ADO_WRITEBACK_ALLOWLIST: frozenset[str] = frozenset([
    "System.AssignedTo",
    "System.IterationPath",
    "Microsoft.VSTS.Scheduling.StoryPoints",
    "Microsoft.VSTS.Scheduling.StartDate",
    "Microsoft.VSTS.Scheduling.TargetDate",
])

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------
MOCK_ADO_PROJECTS = [
    {"id": "ap-1", "name": "Acme Platform", "description": "Main platform project", "state": "wellFormed", "url": "https://dev.azure.com/acme/AcmePlatform"},
    {"id": "ap-2", "name": "Acme Mobile", "description": "Mobile app project", "state": "wellFormed", "url": "https://dev.azure.com/acme/AcmeMobile"},
    {"id": "ap-3", "name": "Acme Internal", "description": "Internal tools", "state": "wellFormed", "url": "https://dev.azure.com/acme/AcmeInternal"},
]

MOCK_ADO_ITERATIONS = [
    {"id": "ai-1", "name": "Sprint 24", "path": "Acme Platform\\Sprint 24", "startDate": "2026-02-09T00:00:00Z", "finishDate": "2026-02-23T00:00:00Z"},
    {"id": "ai-2", "name": "Sprint 25", "path": "Acme Platform\\Sprint 25", "startDate": "2026-02-23T00:00:00Z", "finishDate": "2026-03-09T00:00:00Z"},
    {"id": "ai-3", "name": "Sprint 23", "path": "Acme Platform\\Sprint 23", "startDate": "2026-01-26T00:00:00Z", "finishDate": "2026-02-09T00:00:00Z"},
]

MOCK_ADO_TEAM_MEMBERS = [
    {"id": "1", "displayName": "Alex Kim", "uniqueName": "alex.kim@demo.com"},
    {"id": "2", "displayName": "Sarah Chen", "uniqueName": "sarah.chen@demo.com"},
    {"id": "3", "displayName": "Priya Patel", "uniqueName": "priya.patel@demo.com"},
]

MOCK_ADO_WORK_ITEMS = [
    {"id": "ado-wi-1", "organizationId": "org-1", "externalId": "1001", "sourceTool": "ADO", "title": "Checkout flow step navigation", "status": "IN_PROGRESS", "storyPoints": 8, "priority": 2, "type": "User Story", "labels": [], "iterationId": "ai-1"},
    {"id": "ado-wi-2", "organizationId": "org-1", "externalId": "1002", "sourceTool": "ADO", "title": "Payment gateway integration", "status": "IN_PROGRESS", "storyPoints": 13, "priority": 1, "type": "User Story", "labels": [], "iterationId": "ai-1"},
    {"id": "ado-wi-3", "organizationId": "org-1", "externalId": "1003", "sourceTool": "ADO", "title": "Cart summary component", "status": "New", "storyPoints": 5, "priority": 2, "type": "User Story", "labels": [], "iterationId": "ai-1"},
    {"id": "ado-wi-4", "organizationId": "org-1", "externalId": "1004", "sourceTool": "ADO", "title": "Order confirmation email", "status": "New", "storyPoints": 5, "priority": 3, "type": "User Story", "labels": [], "iterationId": "ai-1"},
    {"id": "ado-wi-5", "organizationId": "org-1", "externalId": "1005", "sourceTool": "ADO", "title": "Mobile responsive checkout", "status": "Closed", "storyPoints": 3, "priority": 2, "type": "Bug", "labels": [], "iterationId": "ai-1"},
]

MOCK_ADO_WORK_ITEMS_DETAILED = [
    {"id": 1001, "title": "Checkout flow step navigation", "state": "Active", "workItemType": "User Story", "assignedTo": "Alex Kim", "storyPoints": 8, "priority": 2},
    {"id": 1002, "title": "Payment gateway integration", "state": "Active", "workItemType": "User Story", "assignedTo": "Sarah Kim", "storyPoints": 13, "priority": 1},
    {"id": 1003, "title": "Cart summary component", "state": "New", "workItemType": "User Story", "assignedTo": "Marcus Johnson", "storyPoints": 5, "priority": 2},
    {"id": 1004, "title": "Order confirmation email", "state": "New", "workItemType": "User Story", "assignedTo": "Emma Davis", "storyPoints": 5, "priority": 3},
    {"id": 1005, "title": "Mobile responsive checkout", "state": "Closed", "workItemType": "Bug", "assignedTo": "Alex Kim", "storyPoints": 3, "priority": 2},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_writeback(fields: dict) -> list[str]:
    """Return list of disallowed field names (empty if all valid)."""
    return [f for f in fields if f not in ADO_WRITEBACK_ALLOWLIST]


async def _get_ado_connection(db: AsyncSession, org_id: str) -> ToolConnection | None:
    """Get the active ADO connection for an org."""
    query = (
        select(ToolConnection)
        .where(ToolConnection.organization_id == org_id)
        .where(ToolConnection.source_tool == "ADO")
        .order_by(ToolConnection.created_at.desc())
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


def _get_ado_auth_info(conn: ToolConnection) -> tuple[str, str | None]:
    """
    Return (org_url, auth_header_override) for a connection.
    - OAuth: Bearer token (auth_header = None, use access_token from _get_valid_access_token)
    - PAT: Basic auth header
    """
    import base64
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")
    org_url = config.get("org_url", "")

    if auth_method == "pat":
        pat = decrypt_token(conn.access_token)
        auth_str = base64.b64encode(f":{pat}".encode()).decode()
        return org_url, f"Basic {auth_str}"
    else:
        return org_url, None


async def _get_valid_access_token(db: AsyncSession, conn: ToolConnection) -> str:
    """
    Get a valid access token, refreshing if needed.
    Azure AD tokens expire in ~1 hour.
    """
    config = conn.config or {}
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
                    tokens = res.json()
                    new_access = tokens["access_token"]
                    new_refresh = tokens.get("refresh_token", refresh_token)

                    conn.access_token = encrypt_token(new_access)
                    config["refresh_token"] = new_refresh
                    config["token_updated_at"] = datetime.now(timezone.utc).isoformat()
                    conn.config = config
                    await db.commit()

                    return new_access
        except Exception:
            pass  # Fall through to existing token

    return access_token


async def _ado_api(
    method: str,
    url: str,
    access_token: str,
    json_body: dict | None = None,
    params: dict | None = None,
    content_type: str = "application/json",
    auth_header: str | None = None,
) -> dict:
    """Make an authenticated Azure DevOps API request."""
    headers = {
        "Authorization": auth_header or f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": content_type,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        if method.upper() == "GET":
            res = await client.get(url, headers=headers, params=params)
        elif method.upper() == "POST":
            res = await client.post(url, headers=headers, json=json_body, params=params)
        elif method.upper() == "PATCH":
            res = await client.patch(url, headers=headers, content=json.dumps(json_body), params=params)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if res.status_code == 401:
            raise HTTPException(status_code=401, detail="ADO token expired or invalid")
        if res.is_error:
            raise HTTPException(
                status_code=res.status_code,
                detail=f"ADO API error: {res.status_code} - {res.text[:200]}",
            )
        if res.status_code == 204:
            return {}
        return res.json()


# ===================================================================
# OAUTH 2.0 FLOW (Azure AD)
# ===================================================================

@router.get("/connect")
async def initiate_ado_oauth(
    current_user: dict = Depends(get_current_user),
):
    """
    GET /connect
    Redirect user to Microsoft OAuth consent screen for Azure DevOps.
    """
    # Hotfix 79 — reverted the require_po gate added in Hotfix 69B.
    # Both PO and dev should be able to initiate OAuth from the
    # Connect Tools modal. The earlier gate was throwing the
    # "This action requires product owner / admin role" 403 to
    # developers. Org-level state visibility (/status,
    # /selected-projects POST, /disconnect) stays gated so non-PO
    # still can't see or modify org connection metadata — they can
    # only kick off a fresh OAuth flow.
    if settings.is_demo_mode:
        return RedirectResponse(url=f"{settings.frontend_url}/po/notifications?ado=demo")

    client_id = settings.ado_client_id
    redirect_uri = settings.ado_redirect_uri
    tenant_id = settings.ado_tenant_id or "common"

    if not client_id:
        raise HTTPException(status_code=500, detail="ADO OAuth not configured (missing client_id)")

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
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": ADO_SCOPE,
        "state": state,
        "prompt": "select_account",
    }

    authorize_url = (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
        f"?{urlencode(params)}"
    )
    return RedirectResponse(url=authorize_url)


@router.get("/callback")
async def ado_oauth_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /callback
    Handle Azure AD OAuth callback.
    Exchange code for tokens, discover ADO orgs, store encrypted in DB.
    """
    if error:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?ado_error={error}"
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?ado_error=missing_params"
        )

    # Validate CSRF state
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?ado_error=invalid_state"
        )

    org_id = state_data["org_id"]
    tenant_id = settings.ado_tenant_id or "common"
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Step 1: Exchange code for tokens
        try:
            token_res = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.ado_client_id,
                    "client_secret": settings.ado_client_secret,
                    "code": code,
                    "redirect_uri": settings.ado_redirect_uri,
                    "scope": ADO_SCOPE,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_res.is_error:
                return RedirectResponse(
                    url=f"{settings.frontend_url}/po/notifications?ado_error=token_exchange_failed"
                )
            tokens = token_res.json()
        except httpx.RequestError:
            return RedirectResponse(
                url=f"{settings.frontend_url}/po/notifications?ado_error=network_error"
            )

        access_token = tokens["access_token"]
        refresh_token = tokens.get("refresh_token", "")

        # Step 2: Get user profile to find their member ID
        try:
            profile_res = await client.get(
                "https://app.vssps.visualstudio.com/_apis/profile/profiles/me?api-version=7.0",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile = profile_res.json() if profile_res.status_code == 200 else {}
        except httpx.RequestError:
            profile = {}

        member_id = profile.get("id", "")
        display_name = profile.get("displayName", "Azure DevOps")
        email = profile.get("emailAddress", "")

        # Step 3: Get accessible organizations
        org_name = ""
        org_url = ""
        try:
            if member_id:
                accounts_res = await client.get(
                    f"https://app.vssps.visualstudio.com/_apis/accounts?memberId={member_id}&api-version=7.0",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if accounts_res.status_code == 200:
                    accounts = accounts_res.json()
                    orgs = accounts.get("value", [])
                    if orgs:
                        # Use the first org
                        org_name = orgs[0].get("accountName", "")
                        org_url = f"https://dev.azure.com/{org_name}"
        except httpx.RequestError:
            pass

    # Step 4: Remove existing ADO connection
    existing = await _get_ado_connection(db, org_id)
    if existing:
        await db.delete(existing)
        await db.flush()

    # Step 5: Store connection with encrypted tokens
    conn = ToolConnection(
        organization_id=org_id,
        source_tool="ADO",
        access_token=encrypt_token(access_token),
        sync_status="connected",
        config={
            "org_name": org_name,
            "org_url": org_url,
            "display_name": display_name,
            "email": email,
            "member_id": member_id,
            "refresh_token": refresh_token,
            "token_updated_at": datetime.now(timezone.utc).isoformat(),
            "auth_method": "oauth2",
        },
    )
    db.add(conn)
    await db.commit()

    return RedirectResponse(
        url=f"{settings.frontend_url}/po/notifications?ado=connected"
    )


# ===================================================================
# PAT CONNECT (for shared / external ADO orgs)
# ===================================================================

@router.post("/connect-token")
async def connect_with_pat(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /connect-token
    Connect to an Azure DevOps organization using a Personal Access Token.
    Use this when connecting to a shared/external ADO org.

    Body: { "org_url": "https://dev.azure.com/orgname", "pat": "..." }
    """
    # Hotfix 79 — reverted the require_po gate (see /connect note).
    import base64

    org_url = (body.get("org_url") or "").rstrip("/")
    pat = body.get("pat", "")

    if not org_url or not pat:
        raise HTTPException(
            status_code=400,
            detail="org_url and pat are required",
        )

    # Auto-fix: normalize the org URL
    from urllib.parse import urlparse
    parsed = urlparse(org_url)
    path_parts = [p for p in parsed.path.split("/") if p]

    # Handle visualstudio.com format: https://orgname.visualstudio.com → https://dev.azure.com/orgname
    hostname = parsed.hostname or ""
    if hostname.endswith(".visualstudio.com"):
        vs_org = hostname.replace(".visualstudio.com", "")
        org_url = f"https://dev.azure.com/{vs_org}"
        logger.info(f"Converted visualstudio.com URL to dev.azure.com: {org_url}")
    elif hostname in ("dev.azure.com", "azure.devops.com") and len(path_parts) > 1:
        # Strip project name if user pasted full project URL
        # e.g. "https://dev.azure.com/OrgName/ProjectName" → "https://dev.azure.com/OrgName"
        org_url = f"{parsed.scheme}://{hostname}/{path_parts[0]}"
        logger.info(f"Auto-stripped project from org URL: {body.get('org_url')} → {org_url}")
    elif hostname in ("dev.azure.com", "azure.devops.com") and len(path_parts) == 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid URL — missing organization name. Use: https://dev.azure.com/YourOrgName",
        )

    # Validate credentials by calling ADO API
    auth_str = base64.b64encode(f":{pat}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_str}",
        "Accept": "application/json",
    }

    logger.info(f"Validating ADO connection to: {org_url}")

    # IMPORTANT: Do NOT follow redirects. ADO returns 302 to sign-in page
    # when auth fails — following it leads to HTML errors.
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        projects_data = None

        # Step 1: Validate org + PAT via _apis/connectiondata
        try:
            conn_res = await client.get(
                f"{org_url}/_apis/connectiondata",
                headers=headers,
            )
            logger.info(f"connectiondata response: {conn_res.status_code}")

            # Hotfix 82 — surface the real reason for PAT failures.
            # ADO returns an HTML error page on 401/403/302/404 whose <title>
            # tells us specifically why ("expired", "not found", etc.). The
            # previous code threw a generic 3-bullet "check these things"
            # message for every failure, which forced the PO to guess. Now we
            # parse the body and show the exact cause when ADO tells us.
            org_parts = [p for p in org_url.rstrip("/").split("/") if p and "." not in p and ":" not in p]
            org_display = org_parts[-1] if org_parts else org_url
            reason = _detect_pat_failure_reason(conn_res)

            if conn_res.status_code == 404 or reason == "not_found":
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"Azure DevOps organization '{org_display}' was not found. "
                        f"Double-check the URL — it should look like https://dev.azure.com/YourOrgName."
                    ),
                )

            if reason == "expired":
                raise HTTPException(
                    status_code=401,
                    detail=(
                        "This Personal Access Token has expired. "
                        "Generate a new one in Azure DevOps (User Settings → Personal Access Tokens → New Token) "
                        "and reconnect."
                    ),
                )

            if reason == "scope":
                raise HTTPException(
                    status_code=401,
                    detail=(
                        "The PAT authenticated but lacks required permissions. "
                        "Regenerate it with at least 'Work Items: Read' and 'Project and Team: Read' scopes."
                    ),
                )

            if conn_res.status_code in (301, 302, 303, 307, 308):
                # Auth failure that didn't match a known body signature — falls
                # through to the generic 3-bullet guidance.
                raise HTTPException(
                    status_code=401,
                    detail=(
                        f"Authentication failed for '{org_display}'. "
                        "Please check: (1) The PAT was created inside the Azure DevOps organization you're connecting to — "
                        "PATs are org-specific. (2) The PAT has not expired. "
                        "(3) The PAT has at least 'Read' scope for Work Items and Project."
                    ),
                )
            if conn_res.status_code in (401, 403):
                raise HTTPException(
                    status_code=401,
                    detail=(
                        f"Authentication failed for '{org_display}'. The PAT was rejected by Azure DevOps. "
                        "Common causes: (1) PAT created in a different org (PATs are org-specific). "
                        "(2) PAT has expired. (3) PAT lacks 'Work Items: Read' / 'Project and Team: Read' scopes."
                    ),
                )
            if conn_res.status_code == 203:
                raise HTTPException(
                    status_code=401,
                    detail="PAT authentication failed. Ensure the token has 'Read' access and was created in this organization.",
                )
            if conn_res.is_error:
                body_text = conn_res.text[:300]
                logger.error(f"ADO connectiondata failed ({conn_res.status_code}): {body_text}")
                raise HTTPException(
                    status_code=400,
                    detail="Could not connect to Azure DevOps. Verify the organization URL and PAT are correct.",
                )

        except httpx.RequestError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Could not reach Azure DevOps: {str(e)[:150]}",
            )

        # Step 2: Fetch projects list
        try:
            res = await client.get(
                f"{org_url}/_apis/projects",
                headers=headers,
                params={"api-version": "7.0", "$top": "1"},
            )
            if res.status_code in (301, 302, 303):
                # Auth worked on connectiondata but not projects — PAT lacks project scope
                projects_data = {"count": 0, "value": []}
            elif res.ok:
                projects_data = res.json()
            else:
                logger.warning(f"Projects list returned {res.status_code}")
                projects_data = {"count": 0, "value": []}
        except Exception as e:
            logger.warning(f"Projects list failed (non-fatal): {e}")
            projects_data = {"count": 0, "value": []}

    org_id = current_user.get("organization_id", "demo-org")

    # Extract org name from URL (e.g., "orgname" from "https://dev.azure.com/orgname")
    org_name = org_url.rstrip("/").split("/")[-1]
    project_count = projects_data.get("count", 0)

    # Remove existing connection
    existing = await _get_ado_connection(db, org_id)
    if existing:
        await db.delete(existing)
        await db.flush()

    # Store connection with encrypted PAT
    conn = ToolConnection(
        organization_id=org_id,
        source_tool="ADO",
        access_token=encrypt_token(pat),
        sync_status="connected",
        config={
            "org_name": org_name,
            "org_url": org_url,
            "auth_method": "pat",
        },
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)

    return {
        "connected": True,
        "org_name": org_name,
        "org_url": org_url,
        "project_count": project_count,
    }


# ===================================================================
# STATUS & DISCONNECT
# ===================================================================

@router.get("/status")
async def ado_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /status — Check if ADO is connected."""
    if settings.is_demo_mode:
        return {"connected": False, "demo": True}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_ado_connection(db, org_id)

    # Hotfix 80 — non-PO callers get the connected boolean reflecting
    # the actual org-level connection state, but no management metadata.
    # Without this they couldn't tell whether the OAuth they just
    # completed had taken effect (Connect Tools modal showed "Not
    # connected" forever). PO callers still get the full payload
    # (org_url, selectedProjects, etc.) which they need to manage the
    # connection.
    is_po = (current_user.get("role") or "").lower() in {"product_owner", "admin", "owner"}
    if not is_po:
        return {"connected": conn is not None}

    if not conn:
        return {"connected": False}

    config = conn.config or {}
    return {
        "connected": True,
        "org_name": config.get("org_name", ""),
        "org_url": config.get("org_url", ""),
        "display_name": config.get("display_name", "Azure DevOps"),
        "email": config.get("email", ""),
        "auth_method": config.get("auth_method", "pat"),
        "connected_at": conn.created_at.isoformat() if conn.created_at else None,
        "selectedProjects": config.get("selectedProjects", []),
    }


@router.post("/selected-projects")
async def save_selected_projects(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /selected-projects — Persist user's selected ADO projects in connection config."""
    require_po(current_user)  # Hotfix 68B — write to org connection state
    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_ado_connection(db, org_id)
    if not conn:
        raise HTTPException(status_code=404, detail="ADO not connected")

    config = dict(conn.config or {})
    config["selectedProjects"] = body.get("projects", [])
    conn.config = config
    await db.commit()
    return {"ok": True}


@router.post("/disconnect")
async def disconnect_ado(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /disconnect — Remove ADO connection."""
    require_po(current_user)  # Hotfix 68B — destructive on org connection
    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_ado_connection(db, org_id)

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
    """GET /projects — Fetch ADO projects using stored credentials (OAuth or PAT)."""
    # Hotfix 81 — reverted the require_po gate added in Hotfix 67A.
    # That gate was put in to stop a silent auto-discover leak that
    # used PO tokens. Now that devs OAuth their OWN Atlassian/ADO
    # accounts (Hotfix 79), the stored tokens belong to whoever last
    # OAuthed, so /projects returns the calling user's projects —
    # which is exactly what the Connect Tools modal needs to render
    # "Select Projects" with real options. Re-gating it would block
    # the explicit import flow.
    if settings.is_demo_mode:
        return {"projects": MOCK_ADO_PROJECTS}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_ado_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="ADO not connected")

    org_url, auth_header = _get_ado_auth_info(conn)
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    if not org_url:
        raise HTTPException(status_code=400, detail="No ADO organization URL found")

    data = await _ado_api(
        "GET",
        f"{org_url}/_apis/projects?api-version=7.0",
        access_token,
        auth_header=auth_header,
    )

    projects = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "description": p.get("description", ""),
            "state": p.get("state", "wellFormed"),
            "url": p.get("url", ""),
        }
        for p in data.get("value", [])
    ]
    return {"projects": projects}


@router.post("/projects")
async def fetch_projects(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /projects — backward compat, uses stored credentials (OAuth or PAT)."""
    if settings.is_demo_mode:
        return {"projects": MOCK_ADO_PROJECTS}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_ado_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="ADO not connected")

    org_url, auth_header = _get_ado_auth_info(conn)
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    if not org_url:
        raise HTTPException(status_code=400, detail="No ADO organization URL found")

    data = await _ado_api(
        "GET",
        f"{org_url}/_apis/projects?api-version=7.0",
        access_token,
        auth_header=auth_header,
    )

    projects = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "description": p.get("description", ""),
            "state": p.get("state", "wellFormed"),
            "url": p.get("url", ""),
        }
        for p in data.get("value", [])
    ]
    return {"projects": projects}


# ===================================================================
# ITERATIONS
# ===================================================================

@router.get("/iterations")
async def list_iterations_demo(
    projectId: str = Query("ap-1"),
    current_user: dict = Depends(get_current_user),
):
    """GET /iterations?projectId=... — demo mock."""
    if settings.is_demo_mode:
        return {"iterations": MOCK_ADO_ITERATIONS}
    return {"iterations": MOCK_ADO_ITERATIONS}


@router.post("/iterations")
async def fetch_iterations(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /iterations — fetch real iterations using stored credentials (OAuth or PAT)."""
    project_name = body.get("projectName")

    if settings.is_demo_mode:
        return {"iterations": MOCK_ADO_ITERATIONS}

    if not project_name:
        raise HTTPException(status_code=400, detail="projectName is required")

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_ado_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="ADO not connected")

    org_url, auth_header = _get_ado_auth_info(conn)
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    data = await _ado_api(
        "GET",
        f"{org_url}/{project_name}/_apis/work/teamsettings/iterations?api-version=7.0",
        access_token,
        auth_header=auth_header,
    )

    iterations = [
        {
            "id": i.get("id", ""),
            "name": i.get("name", ""),
            "path": i.get("path", ""),
            "startDate": (i.get("attributes") or {}).get("startDate"),
            "finishDate": (i.get("attributes") or {}).get("finishDate"),
        }
        for i in data.get("value", [])
    ]
    return {"iterations": iterations}


# ===================================================================
# WORK ITEMS
# ===================================================================

@router.get("/work-items")
async def list_work_items(
    iterationPath: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """GET /work-items — demo mock."""
    if settings.is_demo_mode:
        return {"workItems": MOCK_ADO_WORK_ITEMS}
    return {"workItems": MOCK_ADO_WORK_ITEMS}


@router.post("/work-items")
async def fetch_or_writeback_work_items(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /work-items — two modes:
    1. With projectName: Fetch all work items using stored OAuth token
    2. With itemId + fields: Write-back fields to a work item
    """
    project_name = body.get("projectName")
    item_id = body.get("itemId")
    fields = body.get("fields")

    # ----- Mode 1: Fetch work items by project -----
    if project_name:
        if settings.is_demo_mode:
            return {"workItems": MOCK_ADO_WORK_ITEMS_DETAILED}

        org_id = current_user.get("organization_id", "demo-org")
        conn = await _get_ado_connection(db, org_id)

        if not conn:
            raise HTTPException(status_code=404, detail="ADO not connected")

        org_url, auth_header = _get_ado_auth_info(conn)
        config = conn.config or {}
        auth_method = config.get("auth_method", "oauth2")

        if auth_method == "oauth2":
            access_token = await _get_valid_access_token(db, conn)
        else:
            access_token = ""

        # WIQL query to get work item IDs
        wiql_data = await _ado_api(
            "POST",
            f"{org_url}/{project_name}/_apis/wit/wiql?api-version=7.0",
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

        ids = [wi["id"] for wi in wiql_data.get("workItems", [])][:200]
        if not ids:
            return {"workItems": []}

        # Fetch full details
        details_data = await _ado_api(
            "GET",
            f"{org_url}/_apis/wit/workitems",
            access_token,
            params={
                "ids": ",".join(str(i) for i in ids),
                "$expand": "all",
                "api-version": "7.0",
            },
            auth_header=auth_header,
        )

        work_items = [
            {
                "id": wi.get("id"),
                "title": (wi.get("fields") or {}).get("System.Title", ""),
                "state": (wi.get("fields") or {}).get("System.State", ""),
                "workItemType": (wi.get("fields") or {}).get("System.WorkItemType", ""),
                "assignedTo": ((wi.get("fields") or {}).get("System.AssignedTo") or {}).get("displayName"),
                "areaPath": (wi.get("fields") or {}).get("System.AreaPath"),
                "iterationPath": (wi.get("fields") or {}).get("System.IterationPath"),
                "storyPoints": (wi.get("fields") or {}).get(
                    "Microsoft.VSTS.Scheduling.StoryPoints",
                    (wi.get("fields") or {}).get("Microsoft.VSTS.Scheduling.Effort"),
                ),
                "priority": (wi.get("fields") or {}).get("Microsoft.VSTS.Common.Priority"),
                "tags": (wi.get("fields") or {}).get("System.Tags"),
                "createdDate": (wi.get("fields") or {}).get("System.CreatedDate"),
                "changedDate": (wi.get("fields") or {}).get("System.ChangedDate"),
                "description": (wi.get("fields") or {}).get("System.Description"),
                "parentId": (wi.get("fields") or {}).get("System.Parent"),
                "startDate": (wi.get("fields") or {}).get("Microsoft.VSTS.Scheduling.StartDate"),
                "targetDate": (wi.get("fields") or {}).get("Microsoft.VSTS.Scheduling.TargetDate"),
            }
            for wi in details_data.get("value", [])
        ]
        return {"workItems": work_items}

    # ----- Mode 2: Write-back -----
    if not item_id or not fields or not isinstance(fields, dict):
        if settings.is_demo_mode and not item_id:
            return {"workItems": MOCK_ADO_WORK_ITEMS_DETAILED}
        raise HTTPException(status_code=400, detail="Missing itemId or fields")

    disallowed = _validate_writeback(fields)
    if disallowed:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Write-back denied: disallowed fields",
                "disallowedFields": disallowed,
                "allowedFields": list(ADO_WRITEBACK_ALLOWLIST),
            },
        )

    if settings.is_demo_mode:
        return {"success": True, "itemId": item_id, "fields": fields}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_ado_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="ADO not connected")

    org_url, auth_header = _get_ado_auth_info(conn)
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    patch_document = [
        {"op": "replace", "path": f"/fields/{field}", "value": value}
        for field, value in fields.items()
    ]

    await _ado_api(
        "PATCH",
        f"{org_url}/_apis/wit/workitems/{item_id}?api-version=7.0",
        access_token,
        json_body=patch_document,
        content_type="application/json-patch+json",
        auth_header=auth_header,
    )

    return {"success": True, "itemId": item_id, "fields": fields}


# ===================================================================
# TEAM MEMBERS
# ===================================================================

@router.post("/team-members")
async def fetch_team_members(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /team-members — fetch team members for an ADO project."""
    project_name = body.get("projectName")

    if settings.is_demo_mode:
        return {"members": MOCK_ADO_TEAM_MEMBERS}

    if not project_name:
        raise HTTPException(status_code=400, detail="projectName is required")

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_ado_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="ADO not connected")

    org_url, auth_header = _get_ado_auth_info(conn)
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    try:
        # Get teams for project
        teams_data = await _ado_api(
            "GET",
            f"{org_url}/_apis/projects/{project_name}/teams?api-version=7.0",
            access_token,
            auth_header=auth_header,
        )
    except HTTPException:
        return {"members": []}

    teams = teams_data.get("value", [])
    if not teams:
        return {"members": []}

    all_members: list[dict] = []
    seen_ids: set[str] = set()

    for team in teams[:5]:
        try:
            members_data = await _ado_api(
                "GET",
                f"{org_url}/_apis/projects/{project_name}/teams/{team['id']}/members?api-version=7.0",
                access_token,
                auth_header=auth_header,
            )
            for m in members_data.get("value", []):
                member = m.get("identity") or m
                member_id = member.get("id", "")
                if member_id not in seen_ids:
                    seen_ids.add(member_id)
                    all_members.append({
                        "id": member_id,
                        "displayName": member.get("displayName", ""),
                        "uniqueName": member.get("uniqueName", ""),
                        "imageUrl": member.get("imageUrl"),
                    })
        except HTTPException:
            continue

    return {"members": all_members}


# ===================================================================
# BOARD COLUMNS
# ===================================================================

@router.post("/board-columns")
async def fetch_board_columns(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /board-columns — fetch actual board column configuration from ADO.

    Uses the ADO Boards API (not states/boardcolumns) to get the real board
    columns including stateMappings so items can be slotted correctly.
    """
    project_name = body.get("projectName")
    team_name = body.get("teamName")  # optional

    _SIX_COL_FALLBACK = [
        {"id": "new", "name": "New", "order": 0, "category": "Proposed"},
        {"id": "ready", "name": "Ready", "order": 1, "category": "Proposed"},
        {"id": "in_progress", "name": "In Progress", "order": 2, "category": "InProgress"},
        {"id": "testing", "name": "Testing", "order": 3, "category": "InProgress"},
        {"id": "migrate", "name": "Migrate", "order": 4, "category": "InProgress"},
        {"id": "closed", "name": "Closed", "order": 5, "category": "Completed"},
    ]

    if settings.is_demo_mode:
        return {"columns": _SIX_COL_FALLBACK}

    if not project_name:
        raise HTTPException(status_code=400, detail="projectName is required")

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_ado_connection(db, org_id)
    if not conn:
        raise HTTPException(status_code=404, detail="ADO not connected")

    org_url, auth_header = _get_ado_auth_info(conn)
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    team_path = team_name or f"{project_name} Team"

    # ------------------------------------------------------------------
    # Strategy 1: List boards, pick the first, get its columns
    # ADO API: GET /{project}/{team}/_apis/work/boards?api-version=7.0
    #          GET /{project}/{team}/_apis/work/boards/{boardId}/columns?api-version=7.0
    # ------------------------------------------------------------------
    try:
        boards_data = await _ado_api(
            "GET",
            f"{org_url}/{project_name}/{team_path}/_apis/work/boards?api-version=7.0",
            access_token,
            auth_header=auth_header,
        )
        boards = boards_data.get("value", [])

        # Pick the primary board (usually "Stories" or first board)
        board_name = None
        for b in boards:
            name = b.get("name", "")
            if name.lower() in ("stories", "backlog items", "epics"):
                board_name = name
                break
        if not board_name and boards:
            board_name = boards[0].get("name", "Stories")

        if board_name:
            col_data = await _ado_api(
                "GET",
                f"{org_url}/{project_name}/{team_path}/_apis/work/boards/{board_name}/columns?api-version=7.0",
                access_token,
                auth_header=auth_header,
            )
            raw_columns = col_data.get("value", col_data.get("columns", []))
            if raw_columns:
                columns = [
                    {
                        "id": col.get("id", col.get("name", "").lower().replace(" ", "_")),
                        "name": col.get("name", ""),
                        "order": idx,
                        "category": col.get("columnType", "inProgress"),
                        "stateMappings": col.get("stateMappings", {}),
                    }
                    for idx, col in enumerate(raw_columns)
                ]
                return {"columns": columns}

    except Exception:
        pass  # Fall through to strategy 2

    # ------------------------------------------------------------------
    # Strategy 2: Try the team-default board path directly
    # ------------------------------------------------------------------
    for board_guess in ["Stories", "Backlog items", "Backlog%20items"]:
        try:
            col_data = await _ado_api(
                "GET",
                f"{org_url}/{project_name}/{team_path}/_apis/work/boards/{board_guess}/columns?api-version=7.0",
                access_token,
                auth_header=auth_header,
            )
            raw_columns = col_data.get("value", col_data.get("columns", []))
            if raw_columns:
                columns = [
                    {
                        "id": col.get("id", col.get("name", "").lower().replace(" ", "_")),
                        "name": col.get("name", ""),
                        "order": idx,
                        "category": col.get("columnType", "inProgress"),
                        "stateMappings": col.get("stateMappings", {}),
                    }
                    for idx, col in enumerate(raw_columns)
                ]
                return {"columns": columns}
        except Exception:
            continue

    # ------------------------------------------------------------------
    # Strategy 3: Try with project name as team (ADO default team = project name)
    # ------------------------------------------------------------------
    if team_path != project_name:
        try:
            boards_data = await _ado_api(
                "GET",
                f"{org_url}/{project_name}/{project_name}/_apis/work/boards?api-version=7.0",
                access_token,
                auth_header=auth_header,
            )
            boards = boards_data.get("value", [])
            if boards:
                board_name = boards[0].get("name", "Stories")
                col_data = await _ado_api(
                    "GET",
                    f"{org_url}/{project_name}/{project_name}/_apis/work/boards/{board_name}/columns?api-version=7.0",
                    access_token,
                    auth_header=auth_header,
                )
                raw_columns = col_data.get("value", col_data.get("columns", []))
                if raw_columns:
                    columns = [
                        {
                            "id": col.get("id", col.get("name", "").lower().replace(" ", "_")),
                            "name": col.get("name", ""),
                            "order": idx,
                            "category": col.get("columnType", "inProgress"),
                            "stateMappings": col.get("stateMappings", {}),
                        }
                        for idx, col in enumerate(raw_columns)
                    ]
                    return {"columns": columns}
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Final fallback: 6-column standard board
    # ------------------------------------------------------------------
    return {"columns": _SIX_COL_FALLBACK}


# ===================================================================
# REFRESH BOARD ITEMS — re-fetch titles + states from ADO for all
# work items in a project and update existing DB records
# ===================================================================

@router.post("/refresh-board-items")
async def refresh_board_items(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /refresh-board-items — fetch CURRENT SPRINT items from ADO board.

    Uses @CurrentIteration WIQL macro so the result matches exactly what the
    ADO board shows.  Returns parsed items directly so the frontend can
    render them without a second DB query.
    """
    from ...models.work_item import WorkItem
    from ...models.team_member import TeamMember
    from ...models.imported_project import ImportedProject
    from ...models.base import generate_cuid
    from sqlalchemy import select as sa_select

    project_name = body.get("projectName")
    if not project_name:
        raise HTTPException(status_code=400, detail="projectName is required")

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_ado_connection(db, org_id)
    if not conn:
        raise HTTPException(status_code=404, detail="ADO not connected")

    org_url, auth_header = _get_ado_auth_info(conn)
    config = conn.config or {}
    auth_method = config.get("auth_method", "oauth2")

    if auth_method == "oauth2":
        access_token = await _get_valid_access_token(db, conn)
    else:
        access_token = ""

    # 0. Resolve project_id from ImportedProject table
    proj_result = await db.execute(
        sa_select(ImportedProject).where(
            ImportedProject.organization_id == org_id,
            ImportedProject.name == project_name,
        )
    )
    imported_project = proj_result.scalar_one_or_none()
    project_id = imported_project.id if imported_project else None

    # 1. Detect team name (needed for @CurrentIteration macro)
    team_name = f"{project_name} Team"
    try:
        teams_data = await _ado_api(
            "GET",
            f"{org_url}/_apis/projects/{project_name}/teams?api-version=7.1",
            access_token,
            auth_header=auth_header,
        )
        teams_list = teams_data.get("value", [])
        if teams_list:
            team_name = teams_list[0].get("name", team_name)
    except Exception:
        pass  # Fall back to default team name

    # 2. WIQL — @CurrentIteration scopes to what the ADO board shows
    #    We use the team-scoped WIQL endpoint so the macro resolves correctly
    wiql_current = {
        "query": (
            f"SELECT [System.Id] FROM WorkItems "
            f"WHERE [System.TeamProject] = '{project_name}' "
            f"AND [System.IterationPath] = @CurrentIteration "
            f"AND [System.WorkItemType] IN ('User Story','Bug','Task','Feature') "
            f"AND [System.State] <> 'Removed' "
            f"ORDER BY [System.ChangedDate] DESC"
        )
    }

    wi_ids: list[int] = []
    wiql_mode = "current_iteration"

    try:
        # Team-scoped endpoint resolves @CurrentIteration
        wiql_url = (
            f"{org_url}/{project_name}/{team_name}/_apis/wit/wiql?api-version=7.1"
        )
        wiql_data = await _ado_api(
            "POST", wiql_url, access_token,
            json_body=wiql_current, auth_header=auth_header,
        )
        wi_ids = [wi["id"] for wi in wiql_data.get("workItems", [])][:500]
    except Exception:
        # Fallback: @CurrentIteration not supported or team mismatch
        # Try without the team scope
        try:
            wiql_url_fallback = (
                f"{org_url}/{project_name}/_apis/wit/wiql?api-version=7.1"
            )
            wiql_data = await _ado_api(
                "POST", wiql_url_fallback, access_token,
                json_body=wiql_current, auth_header=auth_header,
            )
            wi_ids = [wi["id"] for wi in wiql_data.get("workItems", [])][:500]
        except Exception:
            pass

    # If @CurrentIteration returned nothing, fall back to ALL non-Removed items
    if not wi_ids:
        wiql_mode = "all_items"
        wiql_all = {
            "query": (
                f"SELECT [System.Id] FROM WorkItems "
                f"WHERE [System.TeamProject] = '{project_name}' "
                f"AND [System.WorkItemType] IN ('User Story','Bug','Task','Feature') "
                f"AND [System.State] <> 'Removed' "
                f"ORDER BY [System.ChangedDate] DESC"
            )
        }
        try:
            wiql_data = await _ado_api(
                "POST",
                f"{org_url}/{project_name}/_apis/wit/wiql?api-version=7.1",
                access_token,
                json_body=wiql_all,
                auth_header=auth_header,
            )
            wi_ids = [wi["id"] for wi in wiql_data.get("workItems", [])][:500]
        except HTTPException:
            return {"items": [], "updated": 0, "created": 0, "error": "WIQL failed"}

    if not wi_ids:
        return {"items": [], "updated": 0, "created": 0}

    # 3. Batch fetch details with BoardColumn + AreaPath
    all_raw_items: list[dict] = []
    for i in range(0, len(wi_ids), 200):
        chunk = wi_ids[i : i + 200]
        ids_str = ",".join(str(x) for x in chunk)
        try:
            detail_data = await _ado_api(
                "GET",
                f"{org_url}/_apis/wit/workitems?ids={ids_str}"
                f"&fields=System.Id,System.Title,System.State,"
                f"System.AssignedTo,System.WorkItemType,"
                f"Microsoft.VSTS.Scheduling.StoryPoints,"
                f"Microsoft.VSTS.Scheduling.Effort,"
                f"Microsoft.VSTS.Common.Priority,System.Tags,"
                f"System.BoardColumn,System.AreaPath,"
                f"System.IterationPath,System.Description,"
                f"Microsoft.VSTS.Common.AcceptanceCriteria,"
                f"System.Parent,Microsoft.VSTS.Scheduling.StartDate,"
                f"Microsoft.VSTS.Scheduling.TargetDate"
                f"&api-version=7.1",
                access_token,
                auth_header=auth_header,
            )
            all_raw_items.extend(detail_data.get("value", []))
        except HTTPException:
            continue

    # 4. Build name→id lookup for assignee resolution
    tm_result = await db.execute(
        sa_select(TeamMember.display_name, TeamMember.id).where(
            TeamMember.organization_id == org_id,
        )
    )
    name_to_id: dict[str, str] = {}
    for row in tm_result.all():
        name_to_id[row[0].lower()] = row[1]

    # 5. Upsert DB + build response items list
    from ...adapters.status_maps import map_ado_status, map_ado_type, map_ado_priority

    updated = 0
    created = 0
    response_items: list[dict] = []

    for raw_item in all_raw_items:
        fields = raw_item.get("fields") or {}
        ext_id = str(raw_item.get("id", ""))
        if not ext_id:
            continue

        # Parse fields
        title = fields.get("System.Title", "") or "Untitled"
        state = fields.get("System.State", "New")
        board_column = fields.get("System.BoardColumn", "")
        area_path = fields.get("System.AreaPath", "")
        wi_type = fields.get("System.WorkItemType", "User Story")
        sp = fields.get("Microsoft.VSTS.Scheduling.StoryPoints") or fields.get(
            "Microsoft.VSTS.Scheduling.Effort"
        )
        priority = fields.get("Microsoft.VSTS.Common.Priority")
        tags_str = fields.get("System.Tags", "") or ""
        assigned_to = fields.get("System.AssignedTo") or {}
        assigned_name = (
            assigned_to.get("displayName")
            if isinstance(assigned_to, dict)
            else assigned_to
        )

        # Build labels — tags + area-path category (e.g. "Frontend" / "Backend")
        labels: list[str] = [t.strip() for t in tags_str.split(";") if t.strip()]
        if area_path:
            segments = area_path.replace("\\", "/").split("/")
            if len(segments) > 1:
                area_cat = segments[-1].strip()
                if area_cat and area_cat.lower() != project_name.lower():
                    if area_cat not in labels:
                        labels.insert(0, area_cat)

        # Determine source_status: prefer BoardColumn (= actual column name)
        source_status = board_column if board_column else state

        # Resolve assignee FK
        assignee_id = None
        if assigned_name and isinstance(assigned_name, str):
            assignee_id = name_to_id.get(assigned_name.lower())

        # Story points
        story_points = None
        if sp is not None:
            try:
                story_points = float(sp)
            except (ValueError, TypeError):
                pass

        # Hotfix 3a — planned dates from ADO Scheduling fields. Without this
        # the Gantt would show "TBD" for every imported feature even when
        # ADO has Start/Target dates set, because the work_items columns
        # stayed NULL on import. ADO returns these as ISO 8601 strings;
        # we parse leniently and silently skip any malformed values.
        from datetime import datetime as _dt, timezone as _tz

        def _parse_ado_date(raw):
            if not raw:
                return None
            try:
                # ADO uses "...Z" suffix; fromisoformat handles "+00:00".
                s = str(raw).replace("Z", "+00:00")
                d = _dt.fromisoformat(s)
                if d.tzinfo is None:
                    d = d.replace(tzinfo=_tz.utc)
                return d
            except (ValueError, TypeError):
                return None

        ado_start = _parse_ado_date(
            fields.get("Microsoft.VSTS.Scheduling.StartDate")
        )
        ado_end = _parse_ado_date(
            fields.get("Microsoft.VSTS.Scheduling.TargetDate")
        )

        # Build response item (returned to frontend directly)
        response_items.append({
            "id": ext_id,
            "externalId": ext_id,
            "title": title,
            "status": map_ado_status(state),
            "sourceStatus": source_status,
            "type": map_ado_type(wi_type),
            "priority": map_ado_priority(priority) if priority else 2,
            "storyPoints": story_points,
            "assignee": assigned_name if isinstance(assigned_name, str) else None,
            "assigneeId": assignee_id,
            "sourceTool": "ADO",
            "labels": labels,
        })

        # DB upsert (keep DB in sync too)
        result = await db.execute(
            sa_select(WorkItem).where(
                WorkItem.organization_id == org_id,
                WorkItem.external_id == ext_id,
                WorkItem.source_tool == "ADO",
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.title = title
            existing.source_status = source_status
            existing.status = map_ado_status(state)
            existing.type = map_ado_type(wi_type)
            existing.labels = labels
            existing.story_points = story_points
            if priority is not None:
                existing.priority = map_ado_priority(priority)
            if assignee_id:
                existing.assignee_id = assignee_id
            if project_id:
                existing.imported_project_id = project_id
            # Only overwrite planned dates when ADO actually has them, so we
            # don't clobber a manual override the PO set via the Gantt edit
            # modal (Sprint D). Treat ADO as the source of truth only when
            # it returns a value.
            if ado_start is not None:
                existing.planned_start = ado_start
            if ado_end is not None:
                existing.planned_end = ado_end
            updated += 1
        else:
            new_item = WorkItem(
                id=generate_cuid(),
                organization_id=org_id,
                external_id=ext_id,
                source_tool="ADO",
                title=title,
                description=fields.get("System.Description"),
                status=map_ado_status(state),
                source_status=source_status,
                story_points=story_points,
                priority=map_ado_priority(priority) if priority else 2,
                type=map_ado_type(wi_type),
                labels=labels,
                acceptance_criteria=fields.get(
                    "Microsoft.VSTS.Common.AcceptanceCriteria"
                ),
                assignee_id=assignee_id,
                imported_project_id=project_id,
                planned_start=ado_start,
                planned_end=ado_end,
            )
            db.add(new_item)
            created += 1

    await db.commit()
    return {
        "items": response_items,
        "updated": updated,
        "created": created,
        "total": len(all_raw_items),
        "wiqlMode": wiql_mode,
    }


# ===================================================================
# WEBHOOKS
# ===================================================================

@router.post("/webhooks")
async def receive_webhook(request: Request):
    """POST /webhooks — Receive Azure DevOps service hook events.

    Hotfix 80 — webhook security hardening:
      - Constant-time compare of the X-Hook-Secret header against the
        configured shared secret (was previously a plain ``!=`` compare,
        which leaks timing info).
      - Strict-mode enforcement parallels GitHub: when ``strict_webhook_verification``
        is on AND no secret is configured, reject 401.
      - The verification block lives OUTSIDE the broad try/except so a
        bad signature returns 401 rather than being swallowed as 500.
    """
    import logging as _logging
    from ...services.webhook_security import (
        verify_shared_secret,
        is_strict_mode_enabled,
    )
    _log = _logging.getLogger(__name__)

    body_bytes = await request.body()

    # ---- Signature verification (outside broad try/except) ----
    webhook_secret = getattr(settings, "ado_webhook_secret", "") or ""
    hook_secret_header = request.headers.get("X-Hook-Secret", "")
    strict_mode = is_strict_mode_enabled() or settings.strict_webhook_verification

    if webhook_secret:
        if not verify_shared_secret(hook_secret_header, webhook_secret):
            _log.warning("[SECURITY] ADO webhook secret MISMATCH — rejecting")
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
    elif strict_mode:
        _log.warning(
            "[SECURITY] ADO webhook REJECTED (strict mode) — ADO_WEBHOOK_SECRET "
            "is not configured."
        )
        raise HTTPException(
            status_code=401, detail="Webhook secret not configured"
        )
    else:
        _log.warning(
            "[SECURITY] ADO webhook accepted UNVERIFIED — ADO_WEBHOOK_SECRET "
            "is not configured. Set it and STRICT_WEBHOOK_VERIFICATION=true to lock down."
        )

    # ---- Payload processing ----
    try:
        body_text = body_bytes.decode("utf-8")

        payload = json.loads(body_text)
        event_type = payload.get("eventType", "unknown")

        if event_type == "workitem.updated":
            pass  # TODO: Normalize and update local WorkItem
        elif event_type == "workitem.created":
            pass  # TODO: Create local WorkItem

        return {
            "received": True,
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception:
        _log.exception("ADO webhook processing failed")
        raise HTTPException(status_code=500, detail="Webhook processing failed")

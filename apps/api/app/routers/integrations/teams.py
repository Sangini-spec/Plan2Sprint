"""
Microsoft Teams integration router.
Handles OAuth 2.0 flow via Microsoft Identity Platform (Azure AD),
user mapping via Graph API, message delivery, and webhook handling.

Endpoints (all prefixed with /api/integrations/teams by main.py):
  GET  /connect       - Initiate Microsoft OAuth 2.0 flow (browser redirect)
  GET  /callback      - Handle OAuth callback, exchange code for tokens
  GET  /status        - Check Teams connection status for current org
  POST /refresh       - Refresh expired access token using refresh_token
  POST /users         - List organization users via MS Graph
  POST /send          - Send a chat message to a Teams user
  POST /test-message  - Send a test message to verify connection
  DELETE /disconnect  - Remove Teams connection
  POST /webhook       - Receive Teams webhook notifications
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Query
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
MS_AUTHORITY = "https://login.microsoftonline.com"
MS_GRAPH_API = "https://graph.microsoft.com/v1.0"

# Permissions: ChannelMessage.Send, Chat.ReadWrite, User.Read.All
TEAMS_SCOPES = "https://graph.microsoft.com/Chat.ReadWrite https://graph.microsoft.com/ChannelMessage.Send https://graph.microsoft.com/User.Read.All offline_access"

# In-memory CSRF state store
_oauth_states: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _get_teams_connection(
    db: AsyncSession, org_id: str
) -> Optional[ToolConnection]:
    """Get the Teams ToolConnection for an organization."""
    result = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == "TEAMS",
        )
    )
    return result.scalar_one_or_none()


async def _refresh_token_if_needed(
    db: AsyncSession, conn: ToolConnection
) -> str:
    """
    Check if Teams access token is expired and refresh if needed.
    Teams tokens expire after 1 hour.
    Returns a valid (decrypted) access token.
    """
    access_token = decrypt_token(conn.access_token)

    # Check if token is expired (with 5-minute buffer)
    if conn.token_expires_at:
        buffer = timedelta(minutes=5)
        if datetime.now(timezone.utc) >= (conn.token_expires_at - buffer):
            # Token expired — refresh it
            if not conn.refresh_token:
                raise HTTPException(
                    status_code=401,
                    detail="Teams token expired and no refresh token available. Please reconnect.",
                )

            refresh_tok = decrypt_token(conn.refresh_token)
            tenant_id = (conn.config or {}).get("tenant_id", settings.teams_tenant_id)

            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    f"{MS_AUTHORITY}/{tenant_id}/oauth2/v2.0/token",
                    data={
                        "client_id": settings.teams_client_id,
                        "client_secret": settings.teams_client_secret,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_tok,
                        "scope": TEAMS_SCOPES,
                    },
                )

                if res.is_error:
                    raise HTTPException(
                        status_code=401,
                        detail="Failed to refresh Teams token. Please reconnect.",
                    )

                token_data = res.json()

            new_access = token_data.get("access_token", "")
            new_refresh = token_data.get("refresh_token", refresh_tok)
            expires_in = token_data.get("expires_in", 3600)

            conn.access_token = encrypt_token(new_access)
            conn.refresh_token = encrypt_token(new_refresh)
            conn.token_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=expires_in
            )
            await db.commit()

            return new_access

    return access_token


async def _graph_api(
    method: str, token: str, endpoint: str, data: dict | None = None
) -> dict:
    """Make an authenticated Microsoft Graph API call."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        if method == "GET":
            res = await client.get(f"{MS_GRAPH_API}{endpoint}", headers=headers)
        elif method == "POST":
            res = await client.post(
                f"{MS_GRAPH_API}{endpoint}", headers=headers, json=data or {}
            )
        else:
            raise ValueError(f"Unsupported method: {method}")

        if res.is_error:
            detail = res.text[:200]
            raise HTTPException(
                status_code=res.status_code,
                detail=f"Graph API error ({endpoint}): {detail}",
            )

        # Some endpoints return 204 No Content
        if res.status_code == 204:
            return {"success": True}

        return res.json()


# ===================================================================
# OAUTH FLOW
# ===================================================================

@router.get("/connect")
async def initiate_teams_oauth(
    current_user: dict = Depends(get_current_user),
):
    """
    GET /connect
    Initiates Microsoft OAuth 2.0 flow by redirecting the browser to
    Microsoft's authorization endpoint.
    """
    if settings.is_demo_mode:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?teams=demo_connected",
            status_code=302,
        )

    client_id = settings.teams_client_id
    redirect_uri = settings.teams_redirect_uri
    tenant_id = settings.teams_tenant_id

    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="Teams OAuth not configured — TEAMS_CLIENT_ID is missing",
        )

    # Generate CSRF state token
    state = str(uuid.uuid4())
    _oauth_states[state] = {
        "user_id": current_user.get("sub", "unknown"),
        "org_id": current_user.get("organization_id", "demo-org"),
        "created_at": time.time(),
    }

    # Clean up expired states
    cutoff = time.time() - 600
    expired = [k for k, v in _oauth_states.items() if v["created_at"] < cutoff]
    for k in expired:
        del _oauth_states[k]

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": TEAMS_SCOPES,
        "state": state,
        "response_mode": "query",
        "prompt": "select_account",
    }

    authorize_url = f"{MS_AUTHORITY}/{tenant_id}/oauth2/v2.0/authorize?{urlencode(params)}"
    return RedirectResponse(url=authorize_url, status_code=302)


@router.get("/callback")
async def teams_oauth_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /callback
    Microsoft redirects here after admin consents.
    Exchanges the authorization code for access + refresh tokens.
    """
    if error:
        detail = error_description or error
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?teams=error&detail={detail}",
            status_code=302,
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?teams=error&detail=missing_code_or_state",
            status_code=302,
        )

    # Verify CSRF state
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?teams=error&detail=invalid_state",
            status_code=302,
        )

    org_id = state_data["org_id"]
    tenant_id = settings.teams_tenant_id

    # Exchange code for tokens
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                f"{MS_AUTHORITY}/{tenant_id}/oauth2/v2.0/token",
                data={
                    "client_id": settings.teams_client_id,
                    "client_secret": settings.teams_client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.teams_redirect_uri,
                    "scope": TEAMS_SCOPES,
                },
            )

            token_data = res.json()

            if "access_token" not in token_data:
                error_msg = token_data.get("error_description", token_data.get("error", "token_exchange_failed"))
                return RedirectResponse(
                    url=f"{settings.frontend_url}/po/notifications?teams=error&detail=token_exchange_failed",
                    status_code=302,
                )
    except httpx.RequestError:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?teams=error&detail=network_error",
            status_code=302,
        )

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)

    # Get organization info from Graph API
    try:
        org_info = await _graph_api("GET", access_token, "/organization")
        org_data = (org_info.get("value") or [{}])[0] if org_info.get("value") else {}
        org_display_name = org_data.get("displayName", "")
        ms_tenant_id = org_data.get("id", tenant_id)
    except Exception:
        org_display_name = ""
        ms_tenant_id = tenant_id

    # Encrypt tokens before storage
    encrypted_access = encrypt_token(access_token)
    encrypted_refresh = encrypt_token(refresh_token) if refresh_token else None

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # Upsert ToolConnection
    existing = await _get_teams_connection(db, org_id)

    connection_config = {
        "tenant_id": ms_tenant_id,
        "tenant_name": org_display_name,
        "scope": TEAMS_SCOPES,
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }

    if existing:
        existing.access_token = encrypted_access
        existing.refresh_token = encrypted_refresh
        existing.token_expires_at = expires_at
        existing.sync_status = "connected"
        existing.config = connection_config
        existing.last_sync_at = datetime.now(timezone.utc)
    else:
        new_conn = ToolConnection(
            organization_id=org_id,
            source_tool="TEAMS",
            access_token=encrypted_access,
            refresh_token=encrypted_refresh,
            token_expires_at=expires_at,
            sync_status="connected",
            config=connection_config,
        )
        db.add(new_conn)

    await db.commit()

    return RedirectResponse(
        url=f"{settings.frontend_url}/po/notifications?teams=connected&org={org_display_name}",
        status_code=302,
    )


# ===================================================================
# STATUS
# ===================================================================

@router.get("/status")
async def teams_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /status — Check if Teams is connected for current org."""
    if settings.is_demo_mode:
        return {"connected": False, "demo": True}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_teams_connection(db, org_id)

    if not conn:
        return {"connected": False}

    config = conn.config or {}
    token_expired = False
    if conn.token_expires_at:
        token_expired = datetime.now(timezone.utc) >= conn.token_expires_at

    return {
        "connected": True,
        "tenant_name": config.get("tenant_name", ""),
        "tenant_id": config.get("tenant_id", ""),
        "connected_at": config.get("connected_at"),
        "sync_status": conn.sync_status,
        "token_expired": token_expired,
    }


# ===================================================================
# TOKEN REFRESH
# ===================================================================

@router.post("/refresh")
async def refresh_teams_token(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /refresh — Force refresh of Teams access token."""
    if settings.is_demo_mode:
        return {"success": True, "demo": True}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_teams_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Teams not connected")

    # Force refresh by setting expiry to past
    conn.token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    # Now refresh
    token = await _refresh_token_if_needed(db, conn)
    return {"success": True, "message": "Token refreshed"}


# ===================================================================
# USER LISTING (Graph API)
# ===================================================================

@router.post("/users")
async def list_teams_users(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /users — List organization users via MS Graph for email mapping."""
    if settings.is_demo_mode:
        return {
            "users": [
                {"id": "T001", "displayName": "Alex Kim", "mail": "alex@demo.com", "userPrincipalName": "alex@demo.onmicrosoft.com"},
                {"id": "T002", "displayName": "Sarah Chen", "mail": "sarah@demo.com", "userPrincipalName": "sarah@demo.onmicrosoft.com"},
                {"id": "T003", "displayName": "Priya Patel", "mail": "priya@demo.com", "userPrincipalName": "priya@demo.onmicrosoft.com"},
            ]
        }

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_teams_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Teams not connected")

    token = await _refresh_token_if_needed(db, conn)

    # Paginate through users
    all_users = []
    endpoint = "/users?$select=id,displayName,mail,userPrincipalName,jobTitle&$top=100"

    while endpoint:
        data = await _graph_api("GET", token, endpoint)

        for user in data.get("value", []):
            all_users.append({
                "id": user.get("id", ""),
                "displayName": user.get("displayName", ""),
                "mail": user.get("mail", ""),
                "userPrincipalName": user.get("userPrincipalName", ""),
                "jobTitle": user.get("jobTitle", ""),
            })

        # Handle pagination
        next_link = data.get("@odata.nextLink", "")
        if next_link and MS_GRAPH_API in next_link:
            endpoint = next_link.replace(MS_GRAPH_API, "")
        else:
            endpoint = None

    return {"users": all_users, "count": len(all_users)}


# ===================================================================
# USER MAPPING
# ===================================================================

@router.post("/map-users")
async def map_teams_users_endpoint(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /map-users
    Match Teams/Graph users to Plan2Sprint team members by email.
    Updates TeamMember.teams_user_id for each match.
    """
    if settings.is_demo_mode:
        return {"success": True, "demo": True, "mapped": 3, "unmapped": 0}

    org_id = current_user.get("organization_id", "demo-org")

    from ...services.user_mapping import map_teams_users
    result = await map_teams_users(db, org_id)

    return {"success": True, **result}


# ===================================================================
# SEND MESSAGE
# ===================================================================

@router.post("/send")
async def send_teams_message(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /send
    Send a 1:1 chat message to a Teams user via Graph API.
    Body: { "user_id": "graph-user-id", "content": "...", "content_type": "html" | "text" }
    """
    user_id = body.get("user_id")
    content = body.get("content", "")
    content_type = body.get("content_type", "html")

    if not user_id:
        raise HTTPException(status_code=400, detail="Missing 'user_id'")

    if settings.is_demo_mode:
        return {"success": True, "demo": True}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_teams_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Teams not connected")

    token = await _refresh_token_if_needed(db, conn)

    # Get the authenticated user's ID (sender) for 1:1 chat
    me = await _graph_api("GET", token, "/me")
    me_id = me.get("id", "")

    # Create or get 1:1 chat — Graph API requires BOTH members
    members = [
        {
            "@odata.type": "#microsoft.graph.aadUserConversationMember",
            "roles": ["owner"],
            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{me_id}')",
        },
        {
            "@odata.type": "#microsoft.graph.aadUserConversationMember",
            "roles": ["owner"],
            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{user_id}')",
        },
    ]

    chat_data = await _graph_api(
        "POST",
        token,
        "/chats",
        {
            "chatType": "oneOnOne",
            "members": members,
        },
    )

    chat_id = chat_data.get("id")
    if not chat_id:
        raise HTTPException(status_code=500, detail="Failed to create Teams chat")

    # Send the message
    message_data = await _graph_api(
        "POST",
        token,
        f"/chats/{chat_id}/messages",
        {
            "body": {
                "contentType": content_type,
                "content": content,
            }
        },
    )

    return {
        "success": True,
        "chat_id": chat_id,
        "message_id": message_data.get("id"),
    }


# ===================================================================
# TEST MESSAGE
# ===================================================================

@router.post("/test-message")
async def send_test_message(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /test-message — Verify Teams connection by making a Graph API call.
    Returns the authenticated user's info to confirm the token works.
    """
    if settings.is_demo_mode:
        return {"success": True, "demo": True}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_teams_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Teams not connected")

    token = await _refresh_token_if_needed(db, conn)

    # Verify connection by calling /me — confirms token is valid
    me = await _graph_api("GET", token, "/me")

    return {
        "success": True,
        "verified": True,
        "user": {
            "displayName": me.get("displayName", ""),
            "mail": me.get("mail", ""),
            "id": me.get("id", ""),
        },
    }


# ===================================================================
# DEEPLINKS — Open Teams directly for chat, meetings, calls
# ===================================================================

@router.post("/deeplink")
async def get_teams_deeplink(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /deeplink
    Generate a Microsoft Teams deep link for chat, meeting, or call.

    Body: {
        "action": "chat" | "meeting" | "call",
        "email": "user@example.com",         (required for chat/call)
        "subject": "Sprint Review",           (optional, for meetings)
        "attendees": ["a@x.com", "b@x.com"]  (optional, for meetings)
    }
    """
    action = body.get("action", "chat")
    email = body.get("email", "")
    subject = body.get("subject", "")
    attendees = body.get("attendees", [])

    if action == "chat":
        if not email:
            raise HTTPException(status_code=400, detail="email is required for chat deeplink")
        deeplink = f"https://teams.microsoft.com/l/chat/0/0?users={email}"

    elif action == "meeting":
        link = "https://teams.microsoft.com/l/meeting/new?"
        params = {}
        if subject:
            params["subject"] = subject
        if attendees:
            params["attendees"] = ",".join(attendees)
        elif email:
            params["attendees"] = email
        deeplink = link + urlencode(params) if params else link

    elif action == "call":
        if not email:
            raise HTTPException(status_code=400, detail="email is required for call deeplink")
        deeplink = f"https://teams.microsoft.com/l/call/0/0?users={email}"

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}. Use 'chat', 'meeting', or 'call'.")

    return {"deeplink": deeplink, "action": action}


# ===================================================================
# DISCONNECT
# ===================================================================

@router.delete("/disconnect")
async def disconnect_teams(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """DELETE /disconnect — Remove Teams connection."""
    if settings.is_demo_mode:
        return {"success": True, "demo": True}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_teams_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Teams not connected")

    await db.delete(conn)
    await db.commit()

    return {"success": True, "message": "Teams disconnected"}


# ===================================================================
# WEBHOOK
# ===================================================================

@router.post("/webhook")
async def teams_webhook(request: Request):
    """
    POST /webhook
    Receive Teams webhook notifications.
    Handles validation token for subscription setup.
    """
    # Handle validation for subscription creation
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=validation_token, status_code=200)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Process notifications
    for notification in body.get("value", []):
        resource = notification.get("resource", "")
        change_type = notification.get("changeType", "")
        print(f"[Teams Webhook] {change_type} on {resource}")

        # TODO: Process specific notifications:
        # - message replies to Plan2Sprint messages
        # - reactions to notifications

    return {"status": "ok"}

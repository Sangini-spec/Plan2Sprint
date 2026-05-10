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
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.supabase import get_current_user, require_po
from ...config import settings
from ...database import get_db
from ...models.tool_connection import ToolConnection
from ...models.user import User
from ...services.encryption import encrypt_token, decrypt_token
import httpx

router = APIRouter()

# Include channel management sub-router (list-teams, select-parent-team, create-channel, post-to-channel, etc.)
from ._teams_channels import router as _teams_channel_router
router.include_router(_teams_channel_router)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MS_AUTHORITY = "https://login.microsoftonline.com"
MS_GRAPH_API = "https://graph.microsoft.com/v1.0"

# Permissions: Chat.ReadWrite, ChannelMessage.Send, User.Read.All, Team.ReadBasic.All, Channel.Create
TEAMS_SCOPES = "https://graph.microsoft.com/Chat.ReadWrite https://graph.microsoft.com/ChannelMessage.Send https://graph.microsoft.com/User.Read.All https://graph.microsoft.com/Team.ReadBasic.All https://graph.microsoft.com/Channel.Create offline_access"

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
    require_po(current_user)  # Hotfix 69B — connecting Teams is a PO-only org action
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


# ===================================================================
# Hotfix 74 — PER-USER TEAMS IDENTITY LINK
#
# Mirror of slack.py's /me/* endpoints. Each developer / stakeholder
# OAuths their personal Microsoft account (User.Read scope only),
# we pull /me from Graph API to get their teams_user_id, and store
# it on their User row. Re-uses the existing ``/callback`` URL —
# distinguished from the org-install flow by the ``me:`` state
# prefix.
# ===================================================================

# Just the minimal scope to identify the calling user. No org-wide
# scopes — those belong to the PO install.
TEAMS_ME_SCOPES = "https://graph.microsoft.com/User.Read offline_access openid profile email"

_me_oauth_states: dict[str, dict] = {}


@router.get("/me/connect")
async def teams_me_connect(
    current_user: dict = Depends(get_current_user),
):
    """Initiate per-user Microsoft OAuth so the caller can link their
    personal Teams identity. Used by developers and stakeholders from
    the Channels page."""
    if settings.is_demo_mode:
        return RedirectResponse(
            url=f"{settings.frontend_url}/dev/notifications?teams=demo_linked",
            status_code=302,
        )

    client_id = settings.teams_client_id
    redirect_uri = settings.teams_redirect_uri
    # NOTE: use ``common`` (or ``organizations``) tenant rather than
    # the org's hard-coded tenant_id — the dev's personal Microsoft
    # account might live in a different tenant. ``common`` lets them
    # sign in with any work/school/personal account.
    tenant_id = "organizations"

    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="Teams OAuth not configured — TEAMS_CLIENT_ID is missing",
        )

    state = "me:" + str(uuid.uuid4())
    _me_oauth_states[state] = {
        "user_id": current_user.get("sub", "unknown"),
        "user_email": (current_user.get("email") or "").lower(),
        "org_id": current_user.get("organization_id", "demo-org"),
        "created_at": time.time(),
    }
    cutoff = time.time() - 600
    for k in [k for k, v in _me_oauth_states.items() if v["created_at"] < cutoff]:
        del _me_oauth_states[k]

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": TEAMS_ME_SCOPES,
        "state": state,
        "response_mode": "query",
        # ``select_account`` so the user is forced to pick which of
        # their multiple Microsoft accounts to link. This is exactly
        # the multi-account UX that's missing without per-user OAuth.
        "prompt": "select_account",
    }

    authorize_url = f"{MS_AUTHORITY}/{tenant_id}/oauth2/v2.0/authorize?{urlencode(params)}"
    return RedirectResponse(url=authorize_url, status_code=302)


async def _teams_me_callback_inner(
    code: str,
    state: str,
    db: AsyncSession,
):
    """Per-user Teams OAuth callback. Called from the unified
    ``/callback`` when ``state`` is prefixed with ``me:``."""
    redirect_base = f"{settings.frontend_url}/dev/notifications"

    state_data = _me_oauth_states.pop(state, None)
    if not state_data:
        return RedirectResponse(
            url=f"{redirect_base}?teams_me=error&detail=invalid_state",
            status_code=302,
        )

    # Use the same ``organizations`` tenant alias for token exchange
    # as we used for /authorize.
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                f"{MS_AUTHORITY}/organizations/oauth2/v2.0/token",
                data={
                    "client_id": settings.teams_client_id,
                    "client_secret": settings.teams_client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.teams_redirect_uri,
                    "scope": TEAMS_ME_SCOPES,
                },
            )
            token_data = res.json()
            if "access_token" not in token_data:
                err = token_data.get("error_description", token_data.get("error", "token_exchange_failed"))
                return RedirectResponse(
                    url=f"{redirect_base}?teams_me=error&detail={err[:80]}",
                    status_code=302,
                )
    except httpx.RequestError:
        return RedirectResponse(
            url=f"{redirect_base}?teams_me=error&detail=network_error",
            status_code=302,
        )

    user_token = token_data.get("access_token", "")

    # Fetch /me from Graph to extract the user's identity
    teams_user_id: str = ""
    teams_upn: Optional[str] = None
    teams_display_name: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            me_res = await client.get(
                f"{MS_GRAPH_API}/me",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            if me_res.status_code == 200:
                me = me_res.json()
                teams_user_id = me.get("id", "") or ""
                teams_upn = me.get("userPrincipalName") or me.get("mail") or None
                teams_display_name = me.get("displayName") or None
    except Exception:
        pass

    if not teams_user_id:
        return RedirectResponse(
            url=f"{redirect_base}?teams_me=error&detail=no_graph_id",
            status_code=302,
        )

    # Persist on the Plan2Sprint User row
    sup_uid = state_data.get("user_id", "")
    user_email = state_data.get("user_email", "")

    user_row: Optional[User] = None
    if sup_uid and sup_uid != "unknown":
        result = await db.execute(
            select(User).where(User.supabase_user_id == sup_uid)
        )
        user_row = result.scalar_one_or_none()
    if not user_row and user_email:
        result = await db.execute(
            select(User).where(User.email == user_email)
        )
        user_row = result.scalar_one_or_none()

    if not user_row:
        return RedirectResponse(
            url=f"{redirect_base}?teams_me=error&detail=user_not_found",
            status_code=302,
        )

    user_row.teams_user_id = teams_user_id
    user_row.teams_user_principal_name = teams_upn
    user_row.teams_display_name = teams_display_name
    await db.commit()

    return RedirectResponse(
        url=f"{redirect_base}?teams_me=linked",
        status_code=302,
    )


@router.get("/me/status")
async def teams_me_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return per-user Teams link state for the current caller."""
    if settings.is_demo_mode:
        return {"linked": False, "demo": True}

    sup_uid = current_user.get("sub", "")
    user_email = (current_user.get("email") or "").lower()
    user_row: Optional[User] = None
    if sup_uid:
        result = await db.execute(
            select(User).where(User.supabase_user_id == sup_uid)
        )
        user_row = result.scalar_one_or_none()
    if not user_row and user_email:
        result = await db.execute(
            select(User).where(User.email == user_email)
        )
        user_row = result.scalar_one_or_none()

    if not user_row or not user_row.teams_user_id:
        return {"linked": False}

    return {
        "linked": True,
        "teams_user_id": user_row.teams_user_id,
        "teams_user_principal_name": user_row.teams_user_principal_name,
        "teams_display_name": user_row.teams_display_name,
    }


@router.post("/me/disconnect")
async def teams_me_disconnect(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear the caller's per-user Teams link."""
    if settings.is_demo_mode:
        return {"ok": True, "demo": True}

    sup_uid = current_user.get("sub", "")
    user_email = (current_user.get("email") or "").lower()
    user_row: Optional[User] = None
    if sup_uid:
        result = await db.execute(
            select(User).where(User.supabase_user_id == sup_uid)
        )
        user_row = result.scalar_one_or_none()
    if not user_row and user_email:
        result = await db.execute(
            select(User).where(User.email == user_email)
        )
        user_row = result.scalar_one_or_none()

    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")

    user_row.teams_user_id = None
    user_row.teams_user_principal_name = None
    user_row.teams_display_name = None
    await db.commit()
    return {"ok": True}


@router.get("/blocker-action", response_class=HTMLResponse)
async def teams_blocker_action(
    blocker_id: str = Query(...),
    action: str = Query(...),
    org_id: str = Query(...),
    t: str = Query(...),
    sig: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Signed-URL endpoint invoked from Teams Adaptive Card buttons.

    Verifies the HMAC signature, updates the blocker status, broadcasts the
    change over WebSocket, and returns a tiny HTML confirmation page.
    """
    from ...models.standup import BlockerFlag
    from ...models.audit_log import AuditLogEntry
    from ...services.teams_action_signer import verify
    from ...services.ws_manager import ws_manager
    from datetime import datetime as _dt, timezone as _tz

    if not verify(blocker_id, action, org_id, t, sig):
        return HTMLResponse(
            "<html><body style='font-family:system-ui;padding:40px;text-align:center'>"
            "<h2>🔒 Invalid or expired link</h2>"
            "<p>This blocker action link couldn't be verified. It may have expired or been tampered with.</p>"
            "</body></html>",
            status_code=403,
        )

    if action not in ("escalate", "resolve"):
        return HTMLResponse("<p>Unknown action.</p>", status_code=400)

    result = await db.execute(select(BlockerFlag).where(BlockerFlag.id == blocker_id))
    blocker = result.scalar_one_or_none()
    if not blocker:
        return HTMLResponse(
            "<html><body style='font-family:system-ui;padding:40px;text-align:center'>"
            "<h2>❓ Blocker not found</h2></body></html>",
            status_code=404,
        )

    new_status = "ESCALATED" if action == "escalate" else "RESOLVED"
    if blocker.status == new_status:
        msg = f"This blocker is already marked as <b>{new_status.lower()}</b>."
    else:
        blocker.status = new_status
        if new_status == "RESOLVED":
            blocker.resolved_at = _dt.now(_tz.utc)
        audit = AuditLogEntry(
            organization_id=org_id,
            actor_id=None,
            actor_role="product_owner",
            event_type=f"blocker.{action}d_via_teams",
            resource_type="blocker_flag",
            resource_id=blocker_id,
            source_channel="TEAMS",
            success=True,
            metadata_={"blocker_id": blocker_id, "action": action},
        )
        db.add(audit)
        await db.commit()

        # Fire WS event so the dev's Plan2Sprint page updates in real time
        try:
            await ws_manager.broadcast(org_id, {
                "type": "blocker_status_changed",
                "data": {"blockerId": blocker_id, "status": new_status},
            })
        except Exception:
            pass

        msg = f"Blocker marked as <b>{new_status.lower()}</b>. You can close this tab."

    color = "#d32f2f" if new_status == "ESCALATED" else "#2e7d32"
    emoji = "🚨" if new_status == "ESCALATED" else "✅"
    return HTMLResponse(
        f"""
        <html><head><title>Plan2Sprint — Blocker Action</title></head>
        <body style='font-family:system-ui;padding:48px;text-align:center;background:#f5f5f5'>
          <div style='max-width:480px;margin:0 auto;padding:32px;background:white;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08)'>
            <div style='font-size:48px'>{emoji}</div>
            <h2 style='color:{color};margin:16px 0'>Done</h2>
            <p style='color:#555;line-height:1.5'>{msg}</p>
            <p style='color:#999;font-size:12px;margin-top:24px'>Plan2Sprint • Teams action</p>
          </div>
        </body></html>
        """
    )


@router.get("/admin-consent")
async def teams_admin_consent():
    """
    GET /admin-consent  — public (no Plan2Sprint auth)

    Redirects to Microsoft's tenant-wide admin consent endpoint.

    Intended to be opened by a Microsoft tenant admin (Global / Application /
    Cloud Application Administrator). After they click "Accept", Microsoft
    grants the requested scopes tenant-wide, so every user in the tenant can
    then OAuth-connect without individual approval requests.

    This endpoint is deliberately unauthenticated: the IT admin may not have
    a Plan2Sprint account, and all this route does is build a redirect URL
    — no secrets are exposed. Microsoft's own auth protects the consent step.
    """
    client_id = settings.teams_client_id
    tenant_id = settings.teams_tenant_id or "common"
    redirect_uri = settings.teams_redirect_uri

    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="Teams OAuth not configured — TEAMS_CLIENT_ID is missing",
        )

    # Opaque state; we don't need to match it back to a user since the admin
    # may be logged-out of Plan2Sprint. The /callback endpoint handles the
    # admin_consent=True path without requiring a matched state.
    state = str(uuid.uuid4())

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    consent_url = f"{MS_AUTHORITY}/{tenant_id}/adminconsent?{urlencode(params)}"
    return RedirectResponse(url=consent_url, status_code=302)


@router.get("/admin-consent-url")
async def teams_admin_consent_url():
    """
    GET /admin-consent-url  — public (no Plan2Sprint auth)

    Returns the raw Microsoft admin-consent URL so the UI can show it for
    copy-paste (e.g. to email / Slack it to the tenant's IT admin directly).
    """
    client_id = settings.teams_client_id
    tenant_id = settings.teams_tenant_id or "common"
    redirect_uri = settings.teams_redirect_uri

    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="Teams OAuth not configured — TEAMS_CLIENT_ID is missing",
        )

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": str(uuid.uuid4()),
    }
    consent_url = f"{MS_AUTHORITY}/{tenant_id}/adminconsent?{urlencode(params)}"
    return {"url": consent_url, "tenant": tenant_id}


@router.get("/callback")
async def teams_oauth_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
    admin_consent: str = Query(None),
    tenant: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /callback
    Microsoft redirects here after a user OR an admin consents.

    Two flows land here:
      • Regular OAuth user flow  → has `code` → exchange for tokens (below).
      • Admin-consent flow       → has `admin_consent=True`, NO `code` → just
                                    redirect the admin back with a success msg.
    """
    if error:
        detail = error_description or error
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?teams=error&detail={detail}",
            status_code=302,
        )

    # --- Admin-consent flow (no code; Microsoft returns admin_consent=True) ---
    if admin_consent and admin_consent.lower() == "true":
        # Clean up the state we stashed (best-effort — not critical)
        if state:
            _oauth_states.pop(state, None)
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?teams=admin_consented",
            status_code=302,
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?teams=error&detail=missing_code_or_state",
            status_code=302,
        )

    # Hotfix 74 — dispatch to per-user Teams identity flow if the
    # state has the ``me:`` prefix. Both flows share this single
    # registered redirect URI on the Microsoft app side.
    if state.startswith("me:"):
        return await _teams_me_callback_inner(code, state, db)

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

    # Hotfix 72 — revert of Hotfix 71. See slack.py for rationale.
    # Per-user Teams OAuth is the correct path; flagging non-PO as
    # "connected" without it just lies about delivery readiness.
    is_po = (current_user.get("role") or "").lower() in {"product_owner", "admin", "owner"}
    if not is_po:
        return {"connected": False}

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
    require_po(current_user)  # Hotfix 69B — destructive on org connection
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
    Receive Microsoft Graph change notifications for Teams resources.

    Hotfix 80 — webhook security hardening:
      Microsoft Graph subscriptions deliver each notification with a
      ``clientState`` field — a shared secret the subscriber set when
      creating the subscription. The subscriber is REQUIRED by Microsoft
      to verify clientState before processing
      (https://learn.microsoft.com/graph/webhooks#processing-the-change-notification).

      We compare ``clientState`` against ``settings.teams_webhook_client_state``
      using constant-time compare. Notifications without a matching
      clientState are rejected with 401.

      Validation handshake (?validationToken=...) is pre-secret since
      Microsoft uses it to verify the endpoint accepts notifications.
    """
    import logging as _logging
    from ...services.webhook_security import (
        verify_shared_secret,
        is_strict_mode_enabled,
    )
    _log = _logging.getLogger(__name__)

    # Subscription validation handshake (no clientState yet, pre-creation).
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=validation_token, status_code=200)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # ---- clientState verification (outside broad try/except) ----
    expected_state = getattr(settings, "teams_webhook_client_state", "") or ""
    strict_mode = is_strict_mode_enabled() or settings.strict_webhook_verification

    notifications = body.get("value", []) or []

    if expected_state:
        # Every notification must carry a matching clientState — even one
        # mismatch fails the entire delivery.
        for n in notifications:
            provided = n.get("clientState", "") or ""
            if not verify_shared_secret(provided, expected_state):
                _log.warning(
                    "[SECURITY] Teams webhook clientState MISMATCH — rejecting"
                )
                raise HTTPException(
                    status_code=401, detail="Invalid clientState"
                )
    elif strict_mode:
        _log.warning(
            "[SECURITY] Teams webhook REJECTED (strict mode) — "
            "TEAMS_WEBHOOK_CLIENT_STATE is not configured."
        )
        raise HTTPException(
            status_code=401, detail="Webhook clientState not configured"
        )
    else:
        _log.warning(
            "[SECURITY] Teams webhook accepted UNVERIFIED — "
            "TEAMS_WEBHOOK_CLIENT_STATE is not configured. "
            "Set it and STRICT_WEBHOOK_VERIFICATION=true to lock down."
        )

    # ---- Payload processing ----
    for notification in notifications:
        resource = notification.get("resource", "")
        change_type = notification.get("changeType", "")
        _log.info(f"[Teams Webhook] {change_type} on {resource}")

        # TODO: Process specific notifications:
        # - message replies to Plan2Sprint messages
        # - reactions to notifications

    return {"status": "ok"}

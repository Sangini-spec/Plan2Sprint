"""
Slack integration router.
Handles OAuth 2.0 flow, user mapping, message delivery, and interaction webhooks.

Endpoints (all prefixed with /api/integrations/slack by main.py):
  GET  /connect       - Initiate Slack OAuth 2.0 V2 flow (browser redirect)
  GET  /callback      - Handle OAuth callback, exchange code for bot token
  GET  /status        - Check Slack connection status for current org
  POST /users         - List workspace users (for email mapping)
  POST /send          - Send a message to a Slack user or channel
  POST /test-message  - Send a test message to verify connection
  POST /events        - Receive Slack events API / interaction payloads
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import RedirectResponse
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

# Include channel management sub-router
from ._slack_channels import router as _channel_router
router.include_router(_channel_router)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SLACK_OAUTH_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_OAUTH_TOKEN_URL = "https://slack.com/api/oauth.v2.access"
SLACK_API_BASE = "https://slack.com/api"

# In-memory CSRF state store (in production, use Redis or DB)
# Maps state -> { user_id, org_id, created_at }
_oauth_states: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _verify_slack_signature(
    signing_secret: str, timestamp: str, body: bytes, signature: str
) -> bool:
    """Verify Slack request signature using HMAC-SHA256."""
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False  # Replay attack prevention: reject requests older than 5 min

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed = (
        "v0="
        + hmac.HMAC(
            signing_secret.encode(), sig_basestring.encode(), hashlib.sha256
        ).hexdigest()
    )
    return hmac.compare_digest(computed, signature)


async def _get_slack_connection(
    db: AsyncSession, org_id: str
) -> Optional[ToolConnection]:
    """Get the Slack ToolConnection for an organization."""
    result = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == "SLACK",
        )
    )
    return result.scalar_one_or_none()


async def _slack_api(
    method: str, token: str, data: dict | None = None
) -> dict:
    """Make an authenticated Slack Web API call."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            f"{SLACK_API_BASE}/{method}",
            headers={"Authorization": f"Bearer {token}"},
            json=data or {},
        )
        result = res.json()
        if not result.get("ok"):
            error = result.get("error", "unknown_error")
            raise HTTPException(
                status_code=400,
                detail=f"Slack API error ({method}): {error}",
            )
        return result


# ===================================================================
# OAUTH FLOW
# ===================================================================

@router.get("/connect")
async def initiate_slack_oauth(
    current_user: dict = Depends(get_current_user),
):
    """
    GET /connect
    Initiates Slack OAuth V2 flow by redirecting the browser to Slack's
    authorization page. The frontend navigates here via window.location.href.
    """
    require_po(current_user)  # Hotfix 69B — connecting Slack is a PO-only org action
    if settings.is_demo_mode:
        # In demo mode, simulate a successful connection
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?slack=demo_connected",
            status_code=302,
        )

    client_id = settings.slack_client_id
    redirect_uri = settings.slack_redirect_uri
    scopes = settings.slack_bot_scopes

    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="Slack OAuth not configured — SLACK_CLIENT_ID is missing",
        )

    # Generate CSRF state token
    state = str(uuid.uuid4())
    _oauth_states[state] = {
        "user_id": current_user.get("sub", "unknown"),
        "org_id": current_user.get("organization_id", "demo-org"),
        "created_at": time.time(),
    }

    # Clean up expired states (older than 10 minutes)
    cutoff = time.time() - 600
    expired = [k for k, v in _oauth_states.items() if v["created_at"] < cutoff]
    for k in expired:
        del _oauth_states[k]

    params = {
        "client_id": client_id,
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
    }

    authorize_url = f"{SLACK_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
    return RedirectResponse(url=authorize_url, status_code=302)


@router.get("/callback")
async def slack_oauth_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /callback
    Slack redirects here after user authorizes the app.
    Exchanges the authorization code for a bot token, stores it encrypted.
    """
    # Handle user-denied or error
    if error:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?slack=error&detail={error}",
            status_code=302,
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?slack=error&detail=missing_code_or_state",
            status_code=302,
        )

    # Hotfix 73 — dispatch to per-user identity flow if state has the
    # ``me:`` prefix. Both flows share this redirect URI so the Slack
    # app config only needs the one whitelisted callback.
    if state.startswith("me:"):
        return await _slack_me_callback_inner(code, state, db)

    # Verify CSRF state
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?slack=error&detail=invalid_state",
            status_code=302,
        )

    org_id = state_data["org_id"]

    # Exchange code for token
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                SLACK_OAUTH_TOKEN_URL,
                data={
                    "client_id": settings.slack_client_id,
                    "client_secret": settings.slack_client_secret,
                    "code": code,
                    "redirect_uri": settings.slack_redirect_uri,
                },
            )

            token_data = res.json()

            if not token_data.get("ok"):
                error_msg = token_data.get("error", "token_exchange_failed")
                return RedirectResponse(
                    url=f"{settings.frontend_url}/po/notifications?slack=error&detail={error_msg}",
                    status_code=302,
                )
    except httpx.RequestError as e:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?slack=error&detail=network_error",
            status_code=302,
        )

    # Extract tokens and metadata
    bot_token = token_data.get("access_token", "")
    team_id = token_data.get("team", {}).get("id", "")
    team_name = token_data.get("team", {}).get("name", "")
    bot_user_id = token_data.get("bot_user_id", "")
    authed_user = token_data.get("authed_user", {})
    scope = token_data.get("scope", "")

    if not bot_token:
        return RedirectResponse(
            url=f"{settings.frontend_url}/po/notifications?slack=error&detail=no_bot_token",
            status_code=302,
        )

    # Encrypt the bot token before storage
    encrypted_token = encrypt_token(bot_token)

    # Upsert ToolConnection for this org
    existing = await _get_slack_connection(db, org_id)

    connection_config = {
        "team_id": team_id,
        "team_name": team_name,
        "bot_user_id": bot_user_id,
        "authed_user_id": authed_user.get("id", ""),
        "scope": scope,
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }

    if existing:
        existing.access_token = encrypted_token
        existing.refresh_token = None  # Slack bot tokens don't expire
        existing.token_expires_at = None
        existing.sync_status = "connected"
        existing.config = connection_config
        existing.last_sync_at = datetime.now(timezone.utc)
    else:
        new_conn = ToolConnection(
            organization_id=org_id,
            source_tool="SLACK",
            access_token=encrypted_token,
            refresh_token=None,
            token_expires_at=None,
            sync_status="connected",
            config=connection_config,
        )
        db.add(new_conn)

    await db.commit()

    # Redirect back to notifications page with success
    return RedirectResponse(
        url=f"{settings.frontend_url}/po/notifications?slack=connected&team={team_name}",
        status_code=302,
    )


# ===================================================================
# STATUS
# ===================================================================

@router.get("/status")
async def slack_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /status
    Check if the current org has Slack connected and return metadata.
    """
    if settings.is_demo_mode:
        return {
            "connected": False,
            "demo": True,
        }

    # Hotfix 72 — revert of Hotfix 71. ``/status`` is the source-of-
    # truth for the *card UI* which shows "Connected" / "Connect" based
    # on whether THIS user's account is linked. Returning ``connected:
    # true`` to non-PO based on org-level state was misleading because
    # the bot doesn't actually know the dev's personal Slack/Teams
    # identity yet — the card was claiming "Connected" with no
    # per-user OAuth ever having happened, so messages would be
    # delivered to the wrong account (or not at all).
    #
    # Org-level visibility ("your workspace has Slack set up at all")
    # belongs on a separate ``/org-status`` endpoint that the dev
    # Channels-page UI can use to render the correct guidance — a
    # design TBD with the product owner.
    is_po = (current_user.get("role") or "").lower() in {"product_owner", "admin", "owner"}
    if not is_po:
        return {"connected": False}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_slack_connection(db, org_id)

    if not conn:
        return {"connected": False}

    config = conn.config or {}
    return {
        "connected": True,
        "team_name": config.get("team_name", ""),
        "team_id": config.get("team_id", ""),
        "scope": config.get("scope", ""),
        "connected_at": config.get("connected_at"),
        "sync_status": conn.sync_status,
    }


# ===================================================================
# Hotfix 73 — PER-USER SLACK IDENTITY LINK
#
# When a developer or stakeholder lands on /dev/notifications and
# clicks "Connect my Slack account", we run a *user* OAuth (with
# user_scope=users.profile:read) that authenticates THEM and returns
# their Slack user_id. We persist it on the User row so the message
# router can DM them. PO-level org connection (the bot install) is
# unrelated — that lives in /connect, /callback above.
# ===================================================================

# In-memory CSRF state for /me/connect — separate from _oauth_states
# so the org install flow and the per-user identity flow can't trip
# over each other.
_me_oauth_states: dict[str, dict] = {}


@router.get("/me/connect")
async def slack_me_connect(
    current_user: dict = Depends(get_current_user),
):
    """Initiate per-user Slack OAuth so the caller can link their
    personal Slack identity. Used by developers and stakeholders from
    the Channels page.

    NOTE: re-uses the existing ``/callback`` redirect URI (already
    whitelisted in the Slack app config). The two flows are
    distinguished by a ``me:`` prefix on the state token — the
    callback handler dispatches accordingly. This avoids requiring
    you to register a separate redirect URL on the Slack app side.
    """
    if settings.is_demo_mode:
        return RedirectResponse(
            url=f"{settings.frontend_url}/dev/notifications?slack=demo_linked",
            status_code=302,
        )

    client_id = settings.slack_client_id
    redirect_uri = settings.slack_redirect_uri  # same as PO install flow

    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="Slack OAuth not configured — SLACK_CLIENT_ID is missing",
        )

    # State prefixed with ``me:`` so the unified ``/callback`` knows
    # to run the per-user flow instead of the org install flow.
    state = "me:" + str(uuid.uuid4())
    _me_oauth_states[state] = {
        "user_id": current_user.get("sub", "unknown"),
        "user_email": (current_user.get("email") or "").lower(),
        "org_id": current_user.get("organization_id", "demo-org"),
        "created_at": time.time(),
    }
    # Cleanup expired states
    cutoff = time.time() - 600
    for k in [k for k, v in _me_oauth_states.items() if v["created_at"] < cutoff]:
        del _me_oauth_states[k]

    params = {
        "client_id": client_id,
        # IMPORTANT: ``user_scope`` (NOT ``scope``) — this puts the
        # OAuth flow in user-token mode. With ``scope`` it would re-
        # install the bot, which is wrong for per-user identity.
        "user_scope": "users.profile:read",
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
    }
    authorize_url = f"{SLACK_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
    return RedirectResponse(url=authorize_url, status_code=302)


async def _slack_me_callback_inner(
    code: str,
    state: str,
    db: AsyncSession,
):
    """Handle the per-user identity OAuth callback. Called from the
    unified ``/callback`` when ``state`` has the ``me:`` prefix."""
    redirect_base = f"{settings.frontend_url}/dev/notifications"

    state_data = _me_oauth_states.pop(state, None)
    if not state_data:
        return RedirectResponse(
            url=f"{redirect_base}?slack_me=error&detail=invalid_state",
            status_code=302,
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                SLACK_OAUTH_TOKEN_URL,
                data={
                    "client_id": settings.slack_client_id,
                    "client_secret": settings.slack_client_secret,
                    "code": code,
                    "redirect_uri": settings.slack_redirect_uri,
                },
            )
            token_data = res.json()
            if not token_data.get("ok"):
                err = token_data.get("error", "token_exchange_failed")
                return RedirectResponse(
                    url=f"{redirect_base}?slack_me=error&detail={err}",
                    status_code=302,
                )
    except httpx.RequestError:
        return RedirectResponse(
            url=f"{redirect_base}?slack_me=error&detail=network_error",
            status_code=302,
        )

    authed_user = token_data.get("authed_user", {}) or {}
    slack_user_id = authed_user.get("id", "")
    user_token = authed_user.get("access_token", "")
    team = token_data.get("team", {}) or {}
    slack_team_id = team.get("id", "")
    slack_team_name = team.get("name", "")

    if not slack_user_id:
        return RedirectResponse(
            url=f"{redirect_base}?slack_me=error&detail=no_user_id",
            status_code=302,
        )

    # Try to fetch the user's display name / handle for friendlier UI.
    # Best-effort — the token from authed_user.access_token has
    # users.profile:read scope so users.profile.get works for self.
    slack_handle: Optional[str] = None
    try:
        if user_token:
            async with httpx.AsyncClient(timeout=8.0) as client:
                profile_res = await client.get(
                    f"{SLACK_API_BASE}/users.profile.get",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
                pdata = profile_res.json()
                if pdata.get("ok"):
                    profile = pdata.get("profile", {}) or {}
                    slack_handle = (
                        profile.get("display_name")
                        or profile.get("real_name")
                        or None
                    )
    except Exception:
        pass

    # Persist on the Plan2Sprint User row by Supabase UID
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
            url=f"{redirect_base}?slack_me=error&detail=user_not_found",
            status_code=302,
        )

    user_row.slack_user_id = slack_user_id
    user_row.slack_team_id = slack_team_id or None
    user_row.slack_team_name = slack_team_name or None
    user_row.slack_handle = slack_handle
    await db.commit()

    return RedirectResponse(
        url=f"{redirect_base}?slack_me=linked",
        status_code=302,
    )


@router.get("/me/status")
async def slack_me_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return per-user Slack link state for the current caller."""
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

    if not user_row or not user_row.slack_user_id:
        return {"linked": False}

    return {
        "linked": True,
        "slack_user_id": user_row.slack_user_id,
        "slack_team_name": user_row.slack_team_name,
        "slack_handle": user_row.slack_handle,
    }


@router.post("/me/disconnect")
async def slack_me_disconnect(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear the caller's per-user Slack link."""
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

    user_row.slack_user_id = None
    user_row.slack_team_id = None
    user_row.slack_team_name = None
    user_row.slack_handle = None
    await db.commit()
    return {"ok": True}


# ===================================================================
# USER LISTING (for email mapping)
# ===================================================================

@router.post("/users")
async def list_slack_users(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /users
    List all workspace users with their email addresses.
    Used for matching Slack users to Plan2Sprint accounts.
    """
    if settings.is_demo_mode:
        return {
            "users": [
                {"id": "U001", "name": "alex.kim", "email": "alex@demo.com", "real_name": "Alex Kim"},
                {"id": "U002", "name": "sarah.chen", "email": "sarah@demo.com", "real_name": "Sarah Chen"},
                {"id": "U003", "name": "priya.patel", "email": "priya@demo.com", "real_name": "Priya Patel"},
            ]
        }

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_slack_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Slack not connected for this organization")

    bot_token = decrypt_token(conn.access_token)

    # Paginate through users.list
    all_users = []
    cursor = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: dict = {"limit": 200}
            if cursor:
                params["cursor"] = cursor

            res = await client.get(
                f"{SLACK_API_BASE}/users.list",
                headers={"Authorization": f"Bearer {bot_token}"},
                params=params,
            )
            data = res.json()

            if not data.get("ok"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Slack users.list error: {data.get('error', 'unknown')}",
                )

            for member in data.get("members", []):
                # Skip bots, deleted users, and Slackbot
                if member.get("is_bot") or member.get("deleted") or member.get("id") == "USLACKBOT":
                    continue

                profile = member.get("profile", {})
                all_users.append({
                    "id": member.get("id", ""),
                    "name": member.get("name", ""),
                    "email": profile.get("email", ""),
                    "real_name": profile.get("real_name", member.get("real_name", "")),
                    "display_name": profile.get("display_name", ""),
                    "avatar": profile.get("image_72", ""),
                })

            # Check for pagination
            next_cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                break
            cursor = next_cursor

    return {"users": all_users, "count": len(all_users)}


# ===================================================================
# USER MAPPING
# ===================================================================

@router.post("/map-users")
async def map_slack_users_endpoint(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /map-users
    Match Slack workspace users to Plan2Sprint team members by email.
    Updates TeamMember.slack_user_id for each match.
    """
    if settings.is_demo_mode:
        return {"success": True, "demo": True, "mapped": 3, "unmapped": 0}

    org_id = current_user.get("organization_id", "demo-org")

    from ...services.user_mapping import map_slack_users
    result = await map_slack_users(db, org_id)

    return {"success": True, **result}


# ===================================================================
# SEND MESSAGE
# ===================================================================

@router.post("/send")
async def send_slack_message(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /send
    Send a message to a Slack user (DM) or channel.
    Body: { "channel": "U12345" | "C12345", "text": "...", "blocks": [...] }
    """
    channel = body.get("channel")
    text = body.get("text", "")
    blocks = body.get("blocks")

    if not channel:
        raise HTTPException(status_code=400, detail="Missing 'channel' (user ID or channel ID)")

    if settings.is_demo_mode:
        return {
            "success": True,
            "demo": True,
            "channel": channel,
            "message": "Demo mode: message simulated",
        }

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_slack_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Slack not connected")

    bot_token = decrypt_token(conn.access_token)

    # If channel is a user ID (starts with U), open a DM conversation first
    conversation_id = channel
    if channel.startswith("U"):
        result = await _slack_api(
            "conversations.open",
            bot_token,
            {"users": channel},
        )
        conversation_id = result.get("channel", {}).get("id", channel)

    # Send the message
    payload: dict = {
        "channel": conversation_id,
        "text": text,
    }
    if blocks:
        payload["blocks"] = blocks

    result = await _slack_api("chat.postMessage", bot_token, payload)

    return {
        "success": True,
        "channel": conversation_id,
        "ts": result.get("ts"),
        "message_id": result.get("ts"),
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
    POST /test-message
    Send a test message to verify the Slack connection works.
    Body: { "user_id": "U12345" } — Slack user ID to DM
    """
    user_id = body.get("user_id")

    if settings.is_demo_mode:
        return {"success": True, "demo": True, "message": "Test message simulated"}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_slack_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Slack not connected")

    bot_token = decrypt_token(conn.access_token)

    # If no user_id provided, send to the user who authorized the app
    if not user_id:
        config = conn.config or {}
        user_id = config.get("authed_user_id")
        if not user_id:
            raise HTTPException(
                status_code=400,
                detail="No user_id provided and no authed user stored",
            )

    # Open DM
    dm_result = await _slack_api(
        "conversations.open", bot_token, {"users": user_id}
    )
    dm_channel = dm_result.get("channel", {}).get("id")

    # Send test message with Block Kit
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":white_check_mark: *Plan2Sprint is connected!*\n\nYou'll receive standup reports, blocker alerts, and sprint notifications here.",
            },
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Sent at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | <{settings.frontend_url}/settings/notifications|Manage preferences>",
                }
            ],
        },
    ]

    result = await _slack_api(
        "chat.postMessage",
        bot_token,
        {
            "channel": dm_channel,
            "text": "Plan2Sprint is connected! You'll receive notifications here.",
            "blocks": blocks,
        },
    )

    return {
        "success": True,
        "channel": dm_channel,
        "ts": result.get("ts"),
    }


# ===================================================================
# DISCONNECT
# ===================================================================

@router.delete("/disconnect")
async def disconnect_slack(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    DELETE /disconnect
    Remove Slack connection for the current org.
    Revokes the bot token with Slack before deleting.
    """
    require_po(current_user)  # Hotfix 69B — destructive on org connection
    if settings.is_demo_mode:
        return {"success": True, "demo": True}

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_slack_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Slack not connected")

    # Revoke the token with Slack
    try:
        bot_token = decrypt_token(conn.access_token)
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{SLACK_API_BASE}/auth.revoke",
                headers={"Authorization": f"Bearer {bot_token}"},
            )
    except Exception:
        pass  # Best effort — continue with deletion even if revoke fails

    await db.delete(conn)
    await db.commit()

    return {"success": True, "message": "Slack disconnected"}


# ===================================================================
# EVENTS API WEBHOOK (incoming events from Slack)
# ===================================================================

@router.post("/events")
async def slack_events(request: Request):
    """
    POST /events
    Receives Slack Events API payloads (messages, mentions, etc.).
    Verifies request signature before processing.
    """
    body_bytes = await request.body()

    # Verify Slack signature (skip in demo mode)
    if not settings.is_demo_mode and settings.slack_signing_secret:
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "0")
        signature = request.headers.get("X-Slack-Signature", "")

        if not _verify_slack_signature(
            settings.slack_signing_secret, timestamp, body_bytes, signature
        ):
            raise HTTPException(status_code=401, detail="Invalid Slack signature")

    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Handle Slack URL verification challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    # Handle events
    event_type = payload.get("type", "")

    if event_type == "event_callback":
        event = payload.get("event", {})
        event_subtype = event.get("type", "")
        print(f"[Slack Event] {event_subtype}: {event.get('text', '')[:100]}")

    return {"ok": True}


# ===================================================================
# INTERACTIONS WEBHOOK (button clicks, menus, modals from Slack)
# ===================================================================

@router.post("/interactions")
async def slack_interactions(
    request: Request,
):
    """
    POST /interactions
    Receives Slack interactive component payloads (button clicks, menus, modals).

    IMPORTANT: Slack sends interactions as application/x-www-form-urlencoded
    with a single `payload` field containing JSON — NOT as raw JSON body.

    Async-ack pattern (required for cold-start safety):

    Slack rejects an interaction if we don't return 200 within ~3 seconds.
    Plan2Sprint runs at minReplicas=0 between cron windows, so when a PO
    clicks Escalate/Resolve at, say, 11 PM IST the container has to cold-
    start before we can even parse the request — which routinely exceeds
    Slack's deadline. The user sees a "couldn't deliver" warning icon
    next to the message and the action silently fails.

    Fix: this endpoint now does the bare minimum synchronously
    (signature verify + payload parse), schedules the actual work as
    a background task, and returns 200 immediately. The background
    task runs the same `handle_interaction` it always did, then POSTs
    the result to Slack's `response_url` to update the original
    message. Slack accepts that pattern and updates the message
    in-place when the POST lands (within 30 min, up to 5 retries).
    """
    # Slack sends form-encoded data with a "payload" JSON string
    content_type = request.headers.get("content-type", "")

    if "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        payload_str = form.get("payload", "{}")
        body_bytes = f"payload={payload_str}".encode()
    else:
        # Fallback: try raw JSON
        body_bytes = await request.body()
        payload_str = body_bytes.decode("utf-8")

    # Verify Slack signature (skip in demo mode for local testing)
    if not settings.is_demo_mode and settings.slack_signing_secret:
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "0")
        signature = request.headers.get("X-Slack-Signature", "")
        # Use body_bytes already captured above (avoids double read of request body)
        if not _verify_slack_signature(
            settings.slack_signing_secret, timestamp, body_bytes, signature
        ):
            raise HTTPException(status_code=401, detail="Invalid Slack signature")

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid interaction payload")

    interaction_type = payload.get("type", "")
    print(f"[Slack Interaction] type={interaction_type}, actions={[a.get('action_id') for a in payload.get('actions', [])]}")

    if interaction_type == "block_actions":
        # Async-ack pattern: schedule the actual work, return 200 fast.
        import asyncio
        asyncio.create_task(_process_interaction_async(payload))

        # Empty 200 OK is a valid Slack ack. Slack keeps the message
        # in place; the background task will POST to response_url to
        # replace it once the action lands.
        return {}

    elif interaction_type == "view_submission":
        # Modal form submissions (future: blocker detail form)
        print(f"[Slack Modal] view submission received")
        return {"response_action": "clear"}

    elif interaction_type == "shortcut":
        # Global/message shortcuts
        callback_id = payload.get("callback_id", "")
        print(f"[Slack Shortcut] {callback_id}")
        return {"ok": True}

    return {"ok": True}


async def _process_interaction_async(payload: dict) -> None:
    """
    Run the handler with its own DB session, then POST the result to
    Slack's `response_url` so the original message updates in place.

    Errors are caught and logged — they must never propagate to the
    asyncio event loop (would crash the worker). Worst case: the user
    sees the message un-updated and can re-click; the underlying state
    change (e.g. blocker.status = ESCALATED) may still have committed.
    """
    from ...database import AsyncSessionLocal
    from ...services.slack_actions import handle_interaction

    response_url = payload.get("response_url", "")

    try:
        async with AsyncSessionLocal() as db:
            try:
                result = await handle_interaction(db, payload)
            finally:
                # handle_interaction commits its own writes; if it raised
                # before commit, roll back to keep the session clean.
                try:
                    await db.rollback()
                except Exception:
                    pass

        if not response_url:
            print("[Slack Interaction] No response_url — skipping message update")
            return

        update_body: dict = {}
        if result.get("replace_original"):
            update_body["replace_original"] = True
        else:
            # Default to replacing — that's the UX users expect when
            # they click Escalate/Resolve.
            update_body["replace_original"] = True
        if result.get("blocks"):
            update_body["blocks"] = result["blocks"]
        if result.get("text"):
            update_body["text"] = result["text"]
        # Always include a fallback text so Slack notifications work.
        if "text" not in update_body:
            update_body["text"] = "Plan2Sprint update"

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                response_url,
                json=update_body,
                headers={"Content-Type": "application/json"},
            )
            if r.is_error:
                print(
                    f"[Slack Interaction] response_url POST failed: "
                    f"{r.status_code} {r.text[:200]}"
                )
    except Exception as e:
        print(f"[Slack Interaction] async handler error: {e}")


# ===================================================================
# CHANNEL LISTING (for message composer)
# ===================================================================

@router.post("/channels")
async def list_slack_channels(
    body: dict = {},
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /channels
    List public channels the bot has access to, scoped to the requesting
    user's role:
      - PO / admin / owner / engineering_manager → ALL public channels
        the bot can see (used for cross-project announcements).
      - Developer / Stakeholder → only channels mapped to projects the
        user has access to (via TeamMember email match OR explicit
        StakeholderProjectAssignment). A dev assigned to MediCare
        shouldn't see Sellixis's project channel — that's a leak of
        another team's communications surface.
    """
    if settings.is_demo_mode:
        return {
            "channels": [
                {"id": "C001", "name": "general"},
                {"id": "C002", "name": "engineering"},
                {"id": "C003", "name": "standups"},
            ]
        }

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_slack_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Slack not connected")

    bot_token = decrypt_token(conn.access_token)

    all_channels = []
    cursor = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: dict = {"limit": 200, "types": "public_channel", "exclude_archived": "true"}
            if cursor:
                params["cursor"] = cursor

            res = await client.get(
                f"{SLACK_API_BASE}/conversations.list",
                headers={"Authorization": f"Bearer {bot_token}"},
                params=params,
            )
            data = res.json()

            if not data.get("ok"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Slack conversations.list error: {data.get('error', 'unknown')}",
                )

            for ch in data.get("channels", []):
                all_channels.append({
                    "id": ch.get("id", ""),
                    "name": ch.get("name", ""),
                    "is_member": ch.get("is_member", False),
                    "num_members": ch.get("num_members", 0),
                })

            next_cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                break
            cursor = next_cursor

    # Role-based filtering. Devs/stakeholders only see channels mapped
    # to their assigned projects.
    user_role = (current_user.get("role") or "").lower()
    elevated = user_role in ("owner", "admin", "product_owner", "engineering_manager")

    if not elevated:
        from ...models.imported_project import ImportedProject, StakeholderProjectAssignment
        from ...models.team_member import TeamMember
        from ...models.user import User as _User

        user_email = (current_user.get("email") or "").lower()

        # Resolve the user's accessible project IDs (mirrors logic in
        # /api/projects developer branch).
        proj_ids: set[str] = set()
        if user_email:
            tm_q = await db.execute(
                select(TeamMember.imported_project_id).where(
                    TeamMember.organization_id == org_id,
                    TeamMember.email.ilike(user_email),
                    TeamMember.role != "excluded",
                )
            )
            for row in tm_q.all():
                if row[0]:
                    proj_ids.add(row[0])

            ids: list[str] = []
            u_rows = (await db.execute(
                select(_User.id).where(_User.email.ilike(user_email))
            )).scalars().all()
            ids.extend(u_rows)
            tm_id_rows = (await db.execute(
                select(TeamMember.id).where(TeamMember.email.ilike(user_email))
            )).scalars().all()
            ids.extend(tm_id_rows)
            if ids:
                assigned_q = await db.execute(
                    select(StakeholderProjectAssignment.imported_project_id).where(
                        StakeholderProjectAssignment.user_id.in_(ids),
                    )
                )
                for row in assigned_q.all():
                    if row[0]:
                        proj_ids.add(row[0])

        # Look up Slack channel IDs registered on those projects.
        allowed_channel_ids: set[str] = set()
        if proj_ids:
            ch_q = await db.execute(
                select(ImportedProject.slack_channel_id).where(
                    ImportedProject.organization_id == org_id,
                    ImportedProject.id.in_(list(proj_ids)),
                    ImportedProject.slack_channel_id.isnot(None),
                )
            )
            for row in ch_q.all():
                if row[0]:
                    allowed_channel_ids.add(row[0])

        all_channels = [c for c in all_channels if c.get("id") in allowed_channel_ids]

    return {"channels": all_channels, "count": len(all_channels)}


# ===================================================================
# TRIGGER NOTIFICATION (human-initiated actions only)
# ===================================================================
# Design principle: Only actions that make sense as human-initiated
# are exposed here. System-triggered notifications (standup digest,
# sprint approval, health alerts) are handled by automated pipelines.
#
# PO actions:
#   - escalate_blocker → Escalate a critical blocker to the team channel
#   - retro_summary    → Push sprint retro outcomes to the team channel
#
# Developer actions:
#   - flag_blocker     → Raise a blocker — sends to PO's DM
# ===================================================================

@router.post("/trigger-notification")
async def trigger_slack_notification(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /trigger-notification
    Send a human-initiated Slack notification.
    Body: { "type": "escalate_blocker" | "retro_summary" | "flag_blocker" }
    """
    notification_type = body.get("type", "")

    if not notification_type:
        raise HTTPException(status_code=400, detail="Missing 'type' field")

    valid_types = {"escalate_blocker", "retro_summary", "flag_blocker"}
    if notification_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown notification type: {notification_type}. Valid types: {', '.join(sorted(valid_types))}",
        )

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_slack_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=404, detail="Slack not connected")

    bot_token = decrypt_token(conn.access_token)
    config = conn.config or {}
    user_id = config.get("authed_user_id")

    if not user_id:
        raise HTTPException(status_code=400, detail="No authed user found for DM delivery")

    # Open DM to the authed user (used as fallback channel)
    dm_result = await _slack_api("conversations.open", bot_token, {"users": user_id})
    dm_channel = dm_result.get("channel", {}).get("id")

    if not dm_channel:
        raise HTTPException(status_code=500, detail="Failed to open DM channel")

    from ...services import card_builders

    # Default to DM; escalate_blocker and retro_summary will try team channel
    target_channel = dm_channel

    if notification_type == "escalate_blocker":
        # PO escalates a blocker to the team channel (falls back to DM)
        payload = card_builders.slack_blocker_alert(
            dev_name="Sarah Chen",
            ticket_key="AUTH-245",
            ticket_title="OAuth token refresh failing in staging",
            blocker_description="Token refresh endpoint returns 500 intermittently. Blocking QA testing for the auth module. Needs backend team investigation.",
            days_blocked=2,
            blocker_id="blocker-demo-001",
            org_id=org_id,
        )
        # Try to find a team channel; fall back to DM
        team_channel = config.get("team_channel_id")
        if team_channel:
            target_channel = team_channel

    elif notification_type == "retro_summary":
        # PO pushes retrospective outcomes to team channel
        payload = card_builders.slack_retro_summary(
            sprint_name="Sprint 24",
            action_items=[
                "Set up staging deployment pipeline by next sprint",
                "Add integration test coverage for auth module",
                "Schedule weekly 15-min tech debt review",
            ],
            top_theme="Deployment pipeline delays",
            went_well=[
                "Checkout flow shipped ahead of schedule",
                "Zero P0 bugs in production this sprint",
                "Great cross-team collaboration on auth migration",
            ],
            to_improve=[
                "Staging deployments took 3+ hours on average",
                "Standup attendance dropped mid-sprint",
                "Story point estimation accuracy was 62%",
            ],
            retro_id="retro-demo-001",
            org_id=org_id,
        )
        # Try team channel; fall back to DM
        team_channel = config.get("team_channel_id")
        if team_channel:
            target_channel = team_channel

    elif notification_type == "flag_blocker":
        # Developer flags a blocker — goes to PO's DM
        payload = card_builders.slack_flag_blocker(
            dev_name="Alex Chen",
            ticket_key="PROJ-211",
            ticket_title="Payment gateway API credentials not received",
            blocker_description="Waiting on vendor to provide sandbox API keys. Cannot complete E2E tests for checkout flow without them. Blocked for 1 day.",
            blocker_id="blocker-dev-001",
            org_id=org_id,
        )
        # This intentionally goes to DM (PO's attention)

    # Send to Slack
    send_payload: dict = {
        "channel": target_channel,
        "text": payload.get("text", "Plan2Sprint Notification"),
    }
    if payload.get("blocks"):
        send_payload["blocks"] = payload["blocks"]

    result = await _slack_api("chat.postMessage", bot_token, send_payload)

    return {
        "success": True,
        "type": notification_type,
        "channel": target_channel,
        "ts": result.get("ts"),
    }

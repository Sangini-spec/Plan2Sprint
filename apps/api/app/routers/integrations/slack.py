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
    db: AsyncSession = Depends(get_db),
):
    """
    POST /interactions
    Receives Slack interactive component payloads (button clicks, menus, modals).

    IMPORTANT: Slack sends interactions as application/x-www-form-urlencoded
    with a single `payload` field containing JSON — NOT as raw JSON body.

    This is the endpoint configured as "Interactivity Request URL" in the
    Slack app settings (Features > Interactivity & Shortcuts).
    URL: https://<your-domain>/api/integrations/slack/interactions
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
        # Import the action handler
        from ...services.slack_actions import handle_interaction

        result = await handle_interaction(db, payload)

        # Return the response to Slack (updates the original message)
        response: dict = {}
        if result.get("replace_original"):
            response["replace_original"] = True
        if result.get("blocks"):
            response["blocks"] = result["blocks"]
        if result.get("text"):
            response["text"] = result["text"]

        return response

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
    List all public channels the bot has access to.
    Used by the message composer UI to pick a target channel.
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

"""
Message routing and delivery service.

Routes notification payloads to the correct delivery channels
(Slack DM, Teams chat, in-app, email fallback) based on:
  1. Organization connection status
  2. User mapping (slack_user_id / teams_user_id)
  3. User notification preferences
  4. Routing rules (e.g., health alerts → PO DM only)

All sends go through this service — never direct API calls from other modules.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.team_member import TeamMember
from ..models.tool_connection import ToolConnection
from ..models.audit_log import AuditLogEntry
from ..services.encryption import decrypt_token, encrypt_token
from ..config import settings
import httpx

MS_TOKEN_URL = "https://login.microsoftonline.com"


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
NotificationType = Literal[
    "standup_report",
    "standup_digest",
    "blocker_alert",
    "sprint_approval",
    "health_alert",
    "sprint_assignment",
    "ci_failure",
    "retro_action",
]

Channel = Literal["slack", "teams", "in_app", "email"]

SLACK_API = "https://slack.com/api"
GRAPH_API = "https://graph.microsoft.com/v1.0"

# ---------------------------------------------------------------------------
# Routing rules
# ---------------------------------------------------------------------------
# health_alert: ALWAYS PO DM only — never in channels, never cross-developer
HEALTH_ALERT_CHANNELS = {"slack", "teams", "in_app"}  # No channel posting
PO_ONLY_TYPES = {"health_alert", "sprint_approval", "standup_digest", "blocker_alert"}
DEV_ONLY_TYPES = {"standup_report", "sprint_assignment", "ci_failure", "retro_action"}


# ---------------------------------------------------------------------------
# Token refresh helpers
# ---------------------------------------------------------------------------

async def _refresh_teams_token_if_needed(
    db: AsyncSession, conn: ToolConnection
) -> str:
    """Check if Teams access token is expired and refresh if needed.
    Returns a valid (decrypted) access token."""
    access_token = decrypt_token(conn.access_token)

    if conn.token_expires_at:
        buffer = timedelta(minutes=5)
        if datetime.now(timezone.utc) >= (conn.token_expires_at - buffer):
            # Token expired — refresh it
            if not conn.refresh_token:
                return access_token  # Can't refresh, return stale token

            refresh_tok = decrypt_token(conn.refresh_token)
            tenant_id = (conn.config or {}).get("tenant_id", settings.teams_tenant_id)
            scopes = "https://graph.microsoft.com/Chat.ReadWrite https://graph.microsoft.com/ChannelMessage.Send https://graph.microsoft.com/User.Read.All offline_access"

            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    f"{MS_TOKEN_URL}/{tenant_id}/oauth2/v2.0/token",
                    data={
                        "client_id": settings.teams_client_id,
                        "client_secret": settings.teams_client_secret,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_tok,
                        "scope": scopes,
                    },
                )

                if res.is_error:
                    return access_token  # Refresh failed, return stale token

                token_data = res.json()

            new_access = token_data.get("access_token", "")
            new_refresh = token_data.get("refresh_token", refresh_tok)
            expires_in = token_data.get("expires_in", 3600)

            conn.access_token = encrypt_token(new_access)
            conn.refresh_token = encrypt_token(new_refresh)
            conn.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            await db.commit()

            return new_access

    return access_token


# ---------------------------------------------------------------------------
# Delivery functions
# ---------------------------------------------------------------------------

async def send_slack_dm(
    bot_token: str,
    user_id: str,
    text: str,
    blocks: list[dict] | None = None,
) -> dict:
    """Send a Slack DM to a user. Returns Slack API response."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Open DM conversation
        open_res = await client.post(
            f"{SLACK_API}/conversations.open",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"users": user_id},
        )
        open_data = open_res.json()
        if not open_data.get("ok"):
            return {"ok": False, "error": open_data.get("error", "conversations.open failed")}

        channel_id = open_data["channel"]["id"]

        # Send message
        payload: dict[str, Any] = {"channel": channel_id, "text": text}
        if blocks:
            payload["blocks"] = blocks

        send_res = await client.post(
            f"{SLACK_API}/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json=payload,
        )
        return send_res.json()


async def send_teams_chat(
    access_token: str,
    user_id: str,
    content: str,
    content_type: str = "html",
) -> dict:
    """Send a 1:1 Teams chat message via Graph API.

    Graph API requires BOTH the sender and recipient as members for oneOnOne chats.
    We get the sender's ID from /me first.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        # Get sender's user ID from /me
        me_res = await client.get(f"{GRAPH_API}/me", headers=headers)
        if me_res.is_error:
            return {"ok": False, "error": f"Failed to get sender info: {me_res.status_code}"}
        me_id = me_res.json().get("id", "")

        # Create or get 1:1 chat — MUST include both sender and recipient
        chat_res = await client.post(
            f"{GRAPH_API}/chats",
            headers=headers,
            json={
                "chatType": "oneOnOne",
                "members": [
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
                ],
            },
        )

        if chat_res.is_error:
            return {"ok": False, "error": f"Chat creation failed: {chat_res.status_code}"}

        chat_id = chat_res.json().get("id")

        # Send message
        msg_res = await client.post(
            f"{GRAPH_API}/chats/{chat_id}/messages",
            headers=headers,
            json={"body": {"contentType": content_type, "content": content}},
        )

        if msg_res.is_error:
            return {"ok": False, "error": f"Message send failed: {msg_res.status_code}"}

        return {"ok": True, "chat_id": chat_id, "message_id": msg_res.json().get("id")}


# ---------------------------------------------------------------------------
# Main routing function
# ---------------------------------------------------------------------------

async def deliver_notification(
    db: AsyncSession,
    org_id: str,
    recipient_email: str,
    notification_type: NotificationType,
    slack_payload: dict | None = None,
    teams_payload: dict | None = None,
    in_app_payload: dict | None = None,
) -> dict:
    """
    Route and deliver a notification to the appropriate channels.

    Args:
        db: Database session
        org_id: Organization ID
        recipient_email: Email of the recipient
        notification_type: Type of notification (determines routing rules)
        slack_payload: { "text": str, "blocks": [...] } for Slack
        teams_payload: { "content": str, "content_type": "html" } for Teams
        in_app_payload: { "title": str, "body": str, "type": str } for in-app

    Returns:
        { "channels": { "slack": "sent"|"skipped"|"error", ... }, "errors": [] }
    """
    result: dict[str, Any] = {
        "channels": {},
        "errors": [],
    }

    # 1. Find the team member
    member_result = await db.execute(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
            TeamMember.email == recipient_email,
        )
    )
    member = member_result.scalar_one_or_none()

    if not member:
        result["errors"].append(f"Team member not found: {recipient_email}")
        result["channels"] = {"slack": "skipped", "teams": "skipped", "in_app": "skipped"}
        return result

    # 2. Try Slack delivery
    if slack_payload and member.slack_user_id:
        try:
            slack_conn_result = await db.execute(
                select(ToolConnection).where(
                    ToolConnection.organization_id == org_id,
                    ToolConnection.source_tool == "SLACK",
                )
            )
            slack_conn = slack_conn_result.scalar_one_or_none()

            if slack_conn:
                bot_token = decrypt_token(slack_conn.access_token)
                slack_result = await send_slack_dm(
                    bot_token,
                    member.slack_user_id,
                    slack_payload.get("text", ""),
                    slack_payload.get("blocks"),
                )
                if slack_result.get("ok"):
                    result["channels"]["slack"] = "sent"
                    await _log_delivery(
                        db, org_id, recipient_email, notification_type, "slack", "sent"
                    )
                else:
                    result["channels"]["slack"] = "error"
                    result["errors"].append(f"Slack: {slack_result.get('error')}")
                    await _log_delivery(
                        db, org_id, recipient_email, notification_type, "slack", "error",
                        slack_result.get("error", ""),
                    )
            else:
                result["channels"]["slack"] = "skipped"
        except Exception as e:
            result["channels"]["slack"] = "error"
            result["errors"].append(f"Slack error: {str(e)}")
    else:
        result["channels"]["slack"] = "skipped"

    # 3. Try Teams delivery
    if teams_payload and member.teams_user_id:
        try:
            teams_conn_result = await db.execute(
                select(ToolConnection).where(
                    ToolConnection.organization_id == org_id,
                    ToolConnection.source_tool == "TEAMS",
                )
            )
            teams_conn = teams_conn_result.scalar_one_or_none()

            if teams_conn:
                # Refresh token if expired (Teams tokens expire after 1 hour)
                access_token = await _refresh_teams_token_if_needed(db, teams_conn)
                teams_result = await send_teams_chat(
                    access_token,
                    member.teams_user_id,
                    teams_payload.get("content", ""),
                    teams_payload.get("content_type", "html"),
                )
                if teams_result.get("ok"):
                    result["channels"]["teams"] = "sent"
                    await _log_delivery(
                        db, org_id, recipient_email, notification_type, "teams", "sent"
                    )
                else:
                    result["channels"]["teams"] = "error"
                    result["errors"].append(f"Teams: {teams_result.get('error')}")
                    await _log_delivery(
                        db, org_id, recipient_email, notification_type, "teams", "error",
                        teams_result.get("error", ""),
                    )
            else:
                result["channels"]["teams"] = "skipped"
        except Exception as e:
            result["channels"]["teams"] = "error"
            result["errors"].append(f"Teams error: {str(e)}")
    else:
        result["channels"]["teams"] = "skipped"

    # 4. In-app notification (always available — persisted to DB)
    if in_app_payload:
        try:
            from ..models.in_app_notification import InAppNotification
            notif = InAppNotification(
                organization_id=org_id,
                recipient_email=recipient_email,
                notification_type=notification_type,
                title=in_app_payload.get("title", "Notification"),
                body=in_app_payload.get("body", ""),
                data_json=in_app_payload,
            )
            db.add(notif)
            await db.commit()
            await db.refresh(notif)

            # Broadcast via WebSocket so NotificationBell updates in real-time
            try:
                from ..routers.ws import ws_manager
                await ws_manager.broadcast(org_id, {
                    "type": "notification",
                    "data": {
                        "id": notif.id,
                        "title": notif.title,
                        "body": notif.body,
                        "notificationType": notification_type,
                    },
                })
            except Exception:
                pass  # WS broadcast is best-effort

            result["channels"]["in_app"] = "sent"
        except Exception as e:
            result["channels"]["in_app"] = "error"
            result["errors"].append(f"In-app: {str(e)}")
        await _log_delivery(
            db, org_id, recipient_email, notification_type, "in_app", "sent"
        )

    # 5. Fallback: If no external channel succeeded, ensure in-app was used
    external_sent = (
        result["channels"].get("slack") == "sent"
        or result["channels"].get("teams") == "sent"
    )
    if not external_sent and "in_app" not in result["channels"]:
        result["channels"]["in_app"] = "fallback"
        await _log_delivery(
            db, org_id, recipient_email, notification_type, "in_app", "fallback"
        )

    return result


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

async def _log_delivery(
    db: AsyncSession,
    org_id: str,
    recipient_email: str,
    notification_type: str,
    channel: str,
    status: str,
    error_detail: str = "",
) -> None:
    """Log a delivery attempt to the audit log."""
    try:
        entry = AuditLogEntry(
            organization_id=org_id,
            actor_id="system",  # System-initiated delivery
            actor_role="system",
            event_type=f"notification.{notification_type}.{channel}",
            resource_type="notification",
            resource_id=f"{notification_type}:{recipient_email}",
            source_channel=channel.upper(),
            success=status == "sent",
            metadata_={
                "recipient": recipient_email,
                "notification_type": notification_type,
                "channel": channel,
                "status": status,
                "error": error_detail,
            },
        )
        db.add(entry)
        await db.commit()
    except Exception:
        pass  # Don't fail delivery over audit log errors

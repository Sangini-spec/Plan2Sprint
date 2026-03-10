"""
POST /api/notifications/send
POST /api/notifications/test

Notification trigger API — the single entry point for all platform events
to fire notifications through the delivery queue.

Used by:
  - sprints.py (sprint plan generated → PO notification)
  - standups.py (blocker flagged → PO notification)
  - team_health.py (health alert → PO DM)
  - Frontend manual triggers (test messages)
  - Future: scheduled cron jobs (daily standup digest)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models.team_member import TeamMember
from ..models.user import User
from ..services.delivery_queue import enqueue_notification
from ..services import card_builders

# Roles that are considered PO/admin for notification routing
PO_ROLES = {"OWNER", "ADMIN", "PRODUCT_OWNER", "ENGINEERING_MANAGER",
            "owner", "admin", "product_owner", "engineering_manager"}

router = APIRouter()


# ---------------------------------------------------------------------------
# SEND NOTIFICATION (internal API — called by other routers or frontend)
# ---------------------------------------------------------------------------

@router.post("/notifications/send")
async def send_notification(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /api/notifications/send

    Trigger a notification through the delivery queue.

    Body:
    {
        "type": "sprint_approval" | "blocker_alert" | "health_alert" | "standup_report" | ...,
        "recipient_email": "po@example.com",   // who gets the notification
        "data": { ... }                         // type-specific payload data
    }
    """
    notification_type = body.get("type")
    recipient_email = body.get("recipient_email")
    data = body.get("data", {})
    org_id = current_user.get("organization_id", "demo-org")

    if not notification_type:
        raise HTTPException(status_code=400, detail="Missing 'type'")
    if not recipient_email:
        raise HTTPException(status_code=400, detail="Missing 'recipient_email'")

    # Build platform-specific payloads based on notification type
    slack_payload = None
    teams_payload = None
    in_app_payload = {"title": "", "body": "", "type": notification_type}

    if notification_type == "sprint_approval":
        slack_payload = card_builders.slack_sprint_approval(
            sprint_name=data.get("sprint_name", "Sprint"),
            total_points=data.get("total_points", 0),
            ticket_count=data.get("ticket_count", 0),
            team_name=data.get("team_name", ""),
            plan_id=data.get("plan_id", ""),
            org_id=org_id,
        )
        teams_payload = card_builders.teams_sprint_approval(
            sprint_name=data.get("sprint_name", "Sprint"),
            total_points=data.get("total_points", 0),
            ticket_count=data.get("ticket_count", 0),
            team_name=data.get("team_name", ""),
        )
        in_app_payload["title"] = "Sprint Plan Ready"
        in_app_payload["body"] = f"Sprint '{data.get('sprint_name', '')}' needs your approval"

    elif notification_type == "blocker_alert":
        slack_payload = card_builders.slack_blocker_alert(
            dev_name=data.get("dev_name", "A developer"),
            ticket_key=data.get("ticket_key", ""),
            ticket_title=data.get("ticket_title", ""),
            blocker_description=data.get("description", ""),
            days_blocked=data.get("days_blocked", 0),
            blocker_id=data.get("blocker_id", ""),
            org_id=org_id,
        )
        teams_payload = card_builders.teams_blocker_alert(
            dev_name=data.get("dev_name", "A developer"),
            ticket_key=data.get("ticket_key", ""),
            ticket_title=data.get("ticket_title", ""),
            blocker_description=data.get("description", ""),
            days_blocked=data.get("days_blocked", 0),
        )
        in_app_payload["title"] = "Blocker Flagged"
        in_app_payload["body"] = f"{data.get('dev_name', '')} flagged a blocker on {data.get('ticket_key', '')}"

    elif notification_type == "health_alert":
        slack_payload = card_builders.slack_health_alert(
            member_name=data.get("member_name", ""),
            alert_type=data.get("alert_type", "Workload Alert"),
            severity=data.get("severity", "medium"),
            details=data.get("details", ""),
            alert_id=data.get("alert_id", ""),
            org_id=org_id,
        )
        teams_payload = card_builders.teams_health_alert(
            member_name=data.get("member_name", ""),
            alert_type=data.get("alert_type", "Workload Alert"),
            severity=data.get("severity", "medium"),
            details=data.get("details", ""),
        )
        in_app_payload["title"] = "Health Alert"
        in_app_payload["body"] = f"Health alert for {data.get('member_name', '')}: {data.get('alert_type', '')}"

    elif notification_type == "standup_report":
        slack_payload = card_builders.slack_standup_report(
            dev_name=data.get("dev_name", ""),
            yesterday=data.get("yesterday", []),
            today=data.get("today", []),
            blockers=data.get("blockers", []),
            sprint_name=data.get("sprint_name", ""),
            report_id=data.get("report_id", ""),
            org_id=org_id,
        )
        teams_payload = card_builders.teams_standup_report(
            dev_name=data.get("dev_name", ""),
            yesterday=data.get("yesterday", []),
            today=data.get("today", []),
            blockers=data.get("blockers", []),
            sprint_name=data.get("sprint_name", ""),
        )
        in_app_payload["title"] = "Standup Report"
        in_app_payload["body"] = f"Daily standup report for {data.get('dev_name', '')}"

    elif notification_type == "standup_digest":
        # PO gets a summary digest — use standup report format for now
        slack_payload = {
            "text": f"Team Standup Digest — {data.get('date', 'today')}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "📊 Team Standup Digest"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Sprint Health:* {data.get('sprint_health', 'GREEN')}\n"
                            f"*Pacing:* {data.get('sprint_pacing', 0)}%\n"
                            f"*Blockers:* {data.get('blocker_count', 0)} active\n"
                            f"*Acknowledged:* {data.get('acknowledged_pct', 0)}%"
                        ),
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Summary:*\n{data.get('summary_text', 'No summary available.')}",
                    },
                },
                {"type": "divider"},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View Full Report"},
                            "url": f"{card_builders.FRONTEND_URL}/po/standups",
                            "style": "primary",
                        },
                    ],
                },
            ],
        }
        # Teams payload for standup digest
        teams_payload = {
            "content": f"""<div>
  <h3>📊 Team Standup Digest</h3>
  <table>
    <tr><td><strong>Sprint Health:</strong></td><td>{data.get('sprint_health', 'GREEN')}</td></tr>
    <tr><td><strong>Pacing:</strong></td><td>{data.get('sprint_pacing', 0)}%</td></tr>
    <tr><td><strong>Blockers:</strong></td><td>{data.get('blocker_count', 0)} active</td></tr>
    <tr><td><strong>Acknowledged:</strong></td><td>{data.get('acknowledged_pct', 0)}%</td></tr>
  </table>
  <p><strong>Summary:</strong> {data.get('summary_text', 'No summary available.')}</p>
  <hr/>
  <p><a href="{card_builders.FRONTEND_URL}/po/standups">View Full Report in Plan2Sprint</a></p>
</div>""",
            "content_type": "html",
        }
        in_app_payload["title"] = "Team Standup Digest"
        in_app_payload["body"] = f"Sprint pacing at {data.get('sprint_pacing', 0)}%, {data.get('blocker_count', 0)} active blockers"

    elif notification_type == "sprint_assignment":
        slack_payload = card_builders.slack_sprint_assignment(
            dev_name=data.get("dev_name", ""),
            ticket_key=data.get("ticket_key", ""),
            ticket_title=data.get("ticket_title", ""),
            sprint_name=data.get("sprint_name", ""),
            story_points=data.get("story_points", 0),
            org_id=org_id,
        )
        teams_payload = card_builders.teams_sprint_assignment(
            dev_name=data.get("dev_name", ""),
            ticket_key=data.get("ticket_key", ""),
            ticket_title=data.get("ticket_title", ""),
            sprint_name=data.get("sprint_name", ""),
            story_points=data.get("story_points", 0),
        )
        in_app_payload["title"] = "Sprint Assignment"
        in_app_payload["body"] = f"{data.get('ticket_key', '')} assigned to you in {data.get('sprint_name', '')}"

    elif notification_type == "ci_failure":
        slack_payload = card_builders.slack_ci_failure(
            dev_name=data.get("dev_name", ""),
            repo_name=data.get("repo_name", ""),
            branch=data.get("branch", ""),
            pr_title=data.get("pr_title", ""),
            failure_summary=data.get("failure_summary", ""),
            run_url=data.get("run_url", ""),
            org_id=org_id,
        )
        teams_payload = card_builders.teams_ci_failure(
            dev_name=data.get("dev_name", ""),
            repo_name=data.get("repo_name", ""),
            branch=data.get("branch", ""),
            pr_title=data.get("pr_title", ""),
            failure_summary=data.get("failure_summary", ""),
            run_url=data.get("run_url", ""),
        )
        in_app_payload["title"] = "CI/CD Failure"
        in_app_payload["body"] = f"Pipeline failed on {data.get('repo_name', '')}/{data.get('branch', '')}"

    elif notification_type == "retro_action":
        slack_payload = card_builders.slack_retro_action(
            dev_name=data.get("dev_name", ""),
            action_item=data.get("action_item", ""),
            sprint_name=data.get("sprint_name", ""),
            retro_id=data.get("retro_id", ""),
            org_id=org_id,
        )
        teams_payload = card_builders.teams_retro_action(
            dev_name=data.get("dev_name", ""),
            action_item=data.get("action_item", ""),
            sprint_name=data.get("sprint_name", ""),
        )
        in_app_payload["title"] = "Retro Action Item"
        in_app_payload["body"] = f"Action item from {data.get('sprint_name', '')}: {data.get('action_item', '')[:60]}"

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown notification type: {notification_type}. "
                   f"Valid types: sprint_approval, blocker_alert, health_alert, standup_report, "
                   f"standup_digest, sprint_assignment, ci_failure, retro_action",
        )

    # Enqueue for async delivery
    await enqueue_notification(
        org_id=org_id,
        recipient_email=recipient_email,
        notification_type=notification_type,
        slack_payload=slack_payload,
        teams_payload=teams_payload,
        in_app_payload=in_app_payload,
    )

    return {
        "success": True,
        "message": f"Notification '{notification_type}' queued for delivery to {recipient_email}",
        "notification_type": notification_type,
        "recipient": recipient_email,
    }


# ---------------------------------------------------------------------------
# GET /api/notifications — list recent in-app notifications for current user
# ---------------------------------------------------------------------------

@router.get("/notifications")
async def list_notifications(
    limit: int = Query(20, le=50),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return recent in-app notifications for the current user."""
    from ..models.in_app_notification import InAppNotification

    user_email = current_user.get("email", "")
    org_id = current_user.get("organization_id", "demo-org")

    result = await db.execute(
        select(InAppNotification)
        .where(
            InAppNotification.organization_id == org_id,
            InAppNotification.recipient_email == user_email,
        )
        .order_by(InAppNotification.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()

    return {
        "notifications": [
            {
                "id": n.id,
                "type": n.notification_type,
                "title": n.title,
                "message": n.body,
                "time": n.created_at.isoformat() if n.created_at else "",
                "read": n.read,
            }
            for n in rows
        ]
    }


# ---------------------------------------------------------------------------
# PATCH /api/notifications/:id/read — mark as read
# ---------------------------------------------------------------------------

@router.patch("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a single in-app notification as read."""
    from ..models.in_app_notification import InAppNotification

    org_id = current_user.get("organization_id", "demo-org")

    result = await db.execute(
        select(InAppNotification).where(
            InAppNotification.id == notification_id,
            InAppNotification.organization_id == org_id,
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    notif.read = True
    await db.commit()
    return {"success": True}


# ---------------------------------------------------------------------------
# GET PO EMAIL for org (helper for internal use)
# ---------------------------------------------------------------------------

async def get_po_email(db: AsyncSession, org_id: str) -> str | None:
    """Get the PO/admin email for an organization. Used for routing PO-only notifications.

    Looks for a user with a PO/admin role in the Users table first.
    Falls back to the first team member if no PO user found (backwards compat).
    """
    # Try to find a user with PO/admin role in this org
    result = await db.execute(
        select(User)
        .where(
            User.organization_id == org_id,
            User.role.in_(list(PO_ROLES)),
        )
        .limit(1)
    )
    user = result.scalar_one_or_none()
    if user:
        return user.email

    # Fallback: first team member (for demo/dev mode)
    result = await db.execute(
        select(TeamMember)
        .where(TeamMember.organization_id == org_id)
        .limit(1)
    )
    member = result.scalar_one_or_none()
    return member.email if member else None

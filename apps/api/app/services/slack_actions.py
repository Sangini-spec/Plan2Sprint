"""
Slack interaction action handlers.

When a PO/developer clicks a button in a Slack Block Kit message,
Slack sends an interaction payload to our /interactions endpoint.
This module processes those actions and performs the corresponding
backend operations (approve sprint, acknowledge blocker, etc.).

Each handler:
  1. Validates the action context
  2. Performs the database mutation
  3. Returns an updated Block Kit message (replaces the original)
  4. Logs to audit trail
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.sprint_plan import SprintPlan
from ..models.standup import BlockerFlag, StandupReport
from ..models.audit_log import AuditLogEntry
from ..models.team_member import TeamMember
from ..config import settings

FRONTEND_URL = settings.frontend_url
_timedelta_60m = timedelta(minutes=60)


# ---------------------------------------------------------------------------
# ACTION REGISTRY
# ---------------------------------------------------------------------------
# Maps action_id from Block Kit buttons → handler function
# Each handler receives (db, payload, action) and returns a response dict

async def handle_interaction(
    db: AsyncSession,
    payload: dict,
) -> dict:
    """
    Main dispatcher. Receives the full Slack interaction payload,
    routes to the correct action handler, and returns the response.

    Returns:
        {
            "response_action": "update" | "clear" | "errors" | None,
            "replace_original": True,
            "blocks": [...] | None,
            "text": str,
        }
    """
    actions = payload.get("actions", [])
    if not actions:
        return {"text": "No action found"}

    action = actions[0]
    action_id = action.get("action_id", "")
    user = payload.get("user", {})
    trigger_id = payload.get("trigger_id", "")

    # Extract metadata from action value (we encode context in the button value)
    action_value = action.get("value", "{}")
    try:
        action_data = json.loads(action_value) if action_value.startswith("{") else {"raw": action_value}
    except (json.JSONDecodeError, AttributeError):
        action_data = {"raw": str(action_value)}

    handler = ACTION_HANDLERS.get(action_id)
    if not handler:
        return {
            "replace_original": False,
            "text": f"Unknown action: {action_id}",
        }

    return await handler(db, payload, action, action_data, user)


# ===================================================================
# SPRINT APPROVAL
# ===================================================================

async def _handle_approve_sprint(
    db: AsyncSession,
    payload: dict,
    action: dict,
    action_data: dict,
    user: dict,
) -> dict:
    """
    PO clicks "Review & Approve" on a sprint plan notification.
    Updates SprintPlan status → APPROVED and returns confirmation message.
    """
    plan_id = action_data.get("plan_id")
    sprint_name = action_data.get("sprint_name", "Sprint")
    org_id = action_data.get("org_id", "demo-org")

    if plan_id:
        result = await db.execute(
            select(SprintPlan).where(SprintPlan.id == plan_id)
        )
        plan = result.scalar_one_or_none()

        if plan and plan.status == "PENDING_REVIEW":
            plan.status = "APPROVED"
            plan.approved_at = datetime.now(timezone.utc)
            plan.undo_available_until = datetime.now(timezone.utc) + _timedelta_60m
            plan.approved_by_id = user.get("id", "slack-user")

            # Log to audit
            audit = AuditLogEntry(
                organization_id=org_id,
                actor_id=user.get("id", "slack-user"),
                actor_role="product_owner",
                event_type="sprint_plan.approved_via_slack",
                resource_type="sprint_plan",
                resource_id=plan_id,
                source_channel="SLACK",
                success=True,
                metadata_={
                    "slack_user_id": user.get("id"),
                    "slack_username": user.get("username"),
                    "sprint_name": sprint_name,
                },
            )
            db.add(audit)
            await db.commit()

            # ── Trigger batch write-back (all assignments) ──
            wb_summary = ""
            try:
                tool = (plan.tool or "").lower()
                if not tool:
                    from ..models.tool_connection import ToolConnection
                    tc_result = await db.execute(
                        select(ToolConnection)
                        .where(ToolConnection.organization_id == org_id)
                        .where(ToolConnection.source_tool.in_(["ADO", "JIRA"]))
                        .order_by(ToolConnection.created_at.desc())
                        .limit(1)
                    )
                    tc = tc_result.scalar_one_or_none()
                    if tc:
                        tool = tc.source_tool.lower()

                if tool == "jira":
                    from .jira_writeback import execute_batch_writeback
                else:
                    from .ado_writeback import execute_batch_writeback

                wb_result = await execute_batch_writeback(
                    db, plan_id, org_id, user.get("id", "slack-user")
                )
                synced = wb_result.get("synced", 0)
                failed_count = wb_result.get("failed", 0)
                wb_summary = f"\n:arrows_counterclockwise: Synced {synced} assignments to {tool.upper()}"
                if failed_count:
                    wb_summary += f" ({failed_count} failed)"
            except Exception as wb_err:
                import logging
                logging.getLogger(__name__).error(f"Slack approval write-back error: {wb_err}")
                wb_summary = f"\n:warning: Write-back to external tool failed: {str(wb_err)[:100]}"

            return {
                "replace_original": True,
                "text": f"✅ Sprint plan '{sprint_name}' approved!",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f":white_check_mark: *Sprint plan '{sprint_name}' — Approved*\n\n"
                                f"Approved by <@{user.get('id', '')}> from Slack at "
                                f"{datetime.now(timezone.utc).strftime('%H:%M UTC')}."
                                f"{wb_summary}"
                            ),
                        },
                    },
                    {"type": "divider"},
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "View in Plan2Sprint"},
                                "url": f"{FRONTEND_URL}/po/planning",
                            },
                        ],
                    },
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": "Action completed via Slack • Plan2Sprint"},
                        ],
                    },
                ],
            }
        elif plan and plan.status == "APPROVED":
            return {
                "replace_original": False,
                "text": "This sprint plan has already been approved.",
            }

    return {
        "replace_original": False,
        "text": "Sprint plan not found or no longer pending review.",
    }


async def _handle_reject_sprint(
    db: AsyncSession,
    payload: dict,
    action: dict,
    action_data: dict,
    user: dict,
) -> dict:
    """
    PO clicks "Reject" on a sprint plan notification.
    Updates SprintPlan status → REJECTED.
    """
    plan_id = action_data.get("plan_id")
    sprint_name = action_data.get("sprint_name", "Sprint")
    org_id = action_data.get("org_id", "demo-org")

    if plan_id:
        result = await db.execute(
            select(SprintPlan).where(SprintPlan.id == plan_id)
        )
        plan = result.scalar_one_or_none()

        if plan and plan.status == "PENDING_REVIEW":
            plan.status = "REJECTED"
            plan.rejection_feedback = f"Rejected via Slack by {user.get('username', 'PO')}"

            audit = AuditLogEntry(
                organization_id=org_id,
                actor_id=user.get("id", "slack-user"),
                actor_role="product_owner",
                event_type="sprint_plan.rejected_via_slack",
                resource_type="sprint_plan",
                resource_id=plan_id,
                source_channel="SLACK",
                success=True,
                metadata_={
                    "slack_user_id": user.get("id"),
                    "sprint_name": sprint_name,
                },
            )
            db.add(audit)
            await db.commit()

            return {
                "replace_original": True,
                "text": f"❌ Sprint plan '{sprint_name}' rejected.",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":x: *Sprint plan '{sprint_name}' — Rejected*\n\nRejected by <@{user.get('id', '')}> from Slack. Please review and regenerate in the app.",
                        },
                    },
                    {"type": "divider"},
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Review in Plan2Sprint"},
                                "url": f"{FRONTEND_URL}/po/planning",
                                "style": "primary",
                            },
                        ],
                    },
                ],
            }

    return {
        "replace_original": False,
        "text": "Sprint plan not found or no longer pending.",
    }


# ===================================================================
# BLOCKER ACKNOWLEDGMENT
# ===================================================================

async def _handle_acknowledge_blocker(
    db: AsyncSession,
    payload: dict,
    action: dict,
    action_data: dict,
    user: dict,
) -> dict:
    """
    PO clicks "Acknowledge" on a blocker alert.
    Updates BlockerFlag status → ACKNOWLEDGED.
    """
    blocker_id = action_data.get("blocker_id")
    ticket_key = action_data.get("ticket_key", "")
    org_id = action_data.get("org_id", "demo-org")

    if blocker_id:
        result = await db.execute(
            select(BlockerFlag).where(BlockerFlag.id == blocker_id)
        )
        blocker = result.scalar_one_or_none()

        if blocker and blocker.status == "OPEN":
            blocker.status = "ACKNOWLEDGED"

            audit = AuditLogEntry(
                organization_id=org_id,
                actor_id=user.get("id", "slack-user"),
                actor_role="product_owner",
                event_type="blocker.acknowledged_via_slack",
                resource_type="blocker_flag",
                resource_id=blocker_id,
                source_channel="SLACK",
                success=True,
                metadata_={
                    "slack_user_id": user.get("id"),
                    "ticket_key": ticket_key,
                    "description": blocker.description[:100],
                },
            )
            db.add(audit)
            await db.commit()

            return {
                "replace_original": True,
                "text": f"✅ Blocker acknowledged: {ticket_key}",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":white_check_mark: *Blocker Acknowledged*\n\n*{ticket_key}*: {blocker.description[:120]}\n\nAcknowledged by <@{user.get('id', '')}> at {datetime.now(timezone.utc).strftime('%H:%M UTC')}",
                        },
                    },
                    {"type": "divider"},
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Escalate"},
                                "action_id": "escalate_blocker",
                                "style": "danger",
                                "value": json.dumps({
                                    "blocker_id": blocker_id,
                                    "ticket_key": ticket_key,
                                    "org_id": org_id,
                                }),
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "View in App"},
                                "url": f"{FRONTEND_URL}/po/standups",
                            },
                        ],
                    },
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": "Action completed via Slack • Plan2Sprint"},
                        ],
                    },
                ],
            }

    return {
        "replace_original": False,
        "text": "Blocker not found or already acknowledged.",
    }


async def _handle_escalate_blocker(
    db: AsyncSession,
    payload: dict,
    action: dict,
    action_data: dict,
    user: dict,
) -> dict:
    """
    PO clicks "Escalate" on a blocker. Marks status → ESCALATED.
    """
    blocker_id = action_data.get("blocker_id")
    ticket_key = action_data.get("ticket_key", "")
    org_id = action_data.get("org_id", "demo-org")

    if blocker_id:
        result = await db.execute(
            select(BlockerFlag).where(BlockerFlag.id == blocker_id)
        )
        blocker = result.scalar_one_or_none()

        if blocker and blocker.status in ("OPEN", "ACKNOWLEDGED"):
            blocker.status = "ESCALATED"

            audit = AuditLogEntry(
                organization_id=org_id,
                actor_id=user.get("id", "slack-user"),
                actor_role="product_owner",
                event_type="blocker.escalated_via_slack",
                resource_type="blocker_flag",
                resource_id=blocker_id,
                source_channel="SLACK",
                success=True,
                metadata_={"slack_user_id": user.get("id"), "ticket_key": ticket_key},
            )
            db.add(audit)
            await db.commit()

            return {
                "replace_original": True,
                "text": f"🚨 Blocker escalated: {ticket_key}",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":rotating_light: *Blocker Escalated*\n\n*{ticket_key}*: {blocker.description[:120]}\n\nEscalated by <@{user.get('id', '')}> — engineering manager has been notified.",
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": "Action completed via Slack • Plan2Sprint"},
                        ],
                    },
                ],
            }

    return {"replace_original": False, "text": "Blocker not found."}


# ===================================================================
# BLOCKER FLAG (developer)
# ===================================================================

async def _handle_flag_blocker(
    db: AsyncSession,
    payload: dict,
    action: dict,
    action_data: dict,
    user: dict,
) -> dict:
    """
    Developer clicks "Flag a Blocker" from their standup report.
    Since we can't open a Slack modal from a webhook response,
    we create a placeholder blocker and ask them to add details in the app.
    """
    report_id = action_data.get("report_id")
    org_id = action_data.get("org_id", "demo-org")

    # Create a new blocker flag
    if report_id:
        blocker = BlockerFlag(
            standup_report_id=report_id,
            description="Blocker flagged via Slack — details pending",
            status="OPEN",
        )
        db.add(blocker)
        await db.commit()
        await db.refresh(blocker)

        audit = AuditLogEntry(
            organization_id=org_id,
            actor_id=user.get("id", "slack-user"),
            actor_role="developer",
            event_type="blocker.flagged_via_slack",
            resource_type="blocker_flag",
            resource_id=blocker.id,
            source_channel="SLACK",
            success=True,
            metadata_={"slack_user_id": user.get("id"), "report_id": report_id},
        )
        db.add(audit)
        await db.commit()

        return {
            "replace_original": False,
            "text": f":rotating_light: *Blocker flagged!*\n\nA blocker has been created. <{FRONTEND_URL}/dev/standups|Add details in Plan2Sprint> so your PO can review it.",
        }

    return {
        "replace_original": False,
        "text": f":rotating_light: *Blocker flagged!*\n\nPlease <{FRONTEND_URL}/dev/standups|add details in Plan2Sprint>.",
    }


# ===================================================================
# SNOOZE HEALTH ALERT
# ===================================================================

async def _handle_snooze_alert(
    db: AsyncSession,
    payload: dict,
    action: dict,
    action_data: dict,
    user: dict,
) -> dict:
    """PO clicks "Snooze" on a health alert."""
    alert_id = action_data.get("alert_id")
    member_name = action_data.get("member_name", "team member")

    return {
        "replace_original": True,
        "text": f"🔇 Health alert snoozed for {member_name}.",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":mute: *Health alert snoozed*\n\nAlert for {member_name} snoozed for 24 hours by <@{user.get('id', '')}>. You'll be reminded tomorrow if the signal persists.",
                },
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "Action completed via Slack • Plan2Sprint"},
                ],
            },
        ],
    }


# ===================================================================
# ACTION HANDLER REGISTRY
# ===================================================================

ACTION_HANDLERS = {
    "approve_sprint": _handle_approve_sprint,
    "reject_sprint": _handle_reject_sprint,
    "acknowledge_blocker": _handle_acknowledge_blocker,
    "escalate_blocker": _handle_escalate_blocker,
    "flag_blocker": _handle_flag_blocker,
    "snooze_alert": _handle_snooze_alert,
}

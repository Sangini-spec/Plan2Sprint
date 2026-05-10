"""
Slack Project Channel Management — endpoints appended to slack router.

This file is imported and registered by slack.py.
Endpoints: create-channel, link-channel, project-channel, post-to-channel
"""

from __future__ import annotations

import re
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.supabase import get_current_user
from ...database import get_db
from ...models.tool_connection import ToolConnection
from ...models.imported_project import ImportedProject
from ...models.team_member import TeamMember

logger = logging.getLogger(__name__)

router = APIRouter()

SLACK_API_BASE = "https://slack.com/api"


async def _get_slack_conn(db: AsyncSession, org_id: str) -> Optional[ToolConnection]:
    result = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == "SLACK",
        )
    )
    return result.scalar_one_or_none()


async def _slack_call(method: str, token: str, data: dict | None = None) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            f"{SLACK_API_BASE}/{method}",
            headers={"Authorization": f"Bearer {token}"},
            json=data or {},
        )
        result = res.json()
        if not result.get("ok"):
            err = result.get("error", "unknown_error")
            raise HTTPException(status_code=400, detail=f"Slack API error: {err}")
        return result


def _get_bot_token(conn: ToolConnection) -> str:
    from ...services.encryption import decrypt_token
    token = decrypt_token(conn.access_token)
    if not token:
        raise HTTPException(status_code=400, detail="Slack token unavailable")
    return token


# =====================================================================
# Create Project Channel
# =====================================================================

@router.post("/create-channel")
async def create_project_channel(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Slack channel for a project and auto-invite team members."""
    org_id = current_user.get("organization_id", "demo-org")
    project_id = body.get("projectId")
    if not project_id:
        raise HTTPException(status_code=400, detail="projectId is required")

    proj_result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == project_id,
            ImportedProject.organization_id == org_id,
        )
    )
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.slack_channel_id:
        return {
            "ok": True,
            "channelId": project.slack_channel_id,
            "channelName": project.slack_channel_name,
            "alreadyExists": True,
        }

    conn = await _get_slack_conn(db, org_id)
    if not conn or not conn.access_token:
        raise HTTPException(status_code=400, detail="Slack not connected")

    bot_token = _get_bot_token(conn)

    # Channel name: "{project}-p2s" — Slack requires lowercase letters/numbers/hyphens
    slug = re.sub(r"[^a-z0-9-]", "", project.name.lower().replace(" ", "-"))[:72]
    channel_name = f"{slug}-p2s"

    # Create channel
    try:
        create_result = await _slack_call("conversations.create", bot_token, {
            "name": channel_name,
            "is_private": False,
        })
        channel_id = create_result["channel"]["id"]
        actual_name = create_result["channel"]["name"]
    except HTTPException as e:
        if "name_taken" in str(e.detail):
            # Find existing channel
            channels_result = await _slack_call("conversations.list", bot_token, {
                "types": "public_channel",
                "limit": 200,
            })
            existing = next(
                (ch for ch in channels_result.get("channels", []) if ch["name"] == channel_name),
                None,
            )
            if existing:
                channel_id = existing["id"]
                actual_name = existing["name"]
            else:
                raise HTTPException(status_code=400, detail=f"Channel name taken but not found")
        else:
            raise

    # Bot joins channel (required before inviting others)
    try:
        await _slack_call("conversations.join", bot_token, {"channel": channel_id})
    except Exception:
        pass

    # Set topic
    try:
        await _slack_call("conversations.setTopic", bot_token, {
            "channel": channel_id,
            "topic": f"Plan2Sprint project channel for {project.name}",
        })
    except Exception:
        pass

    # Auto-invite team members
    members_result = await db.execute(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
            TeamMember.slack_user_id.isnot(None),
        )
    )
    members = members_result.scalars().all()
    invited = 0

    for member in members:
        try:
            await _slack_call("conversations.invite", bot_token, {
                "channel": channel_id,
                "users": member.slack_user_id,
            })
            invited += 1
        except Exception:
            pass  # Already in channel or deactivated

    # Store mapping
    project.slack_channel_id = channel_id
    project.slack_channel_name = actual_name
    await db.commit()

    # Broadcast so all pages (PO + dev) refresh without a manual reload
    try:
        from ...services.ws_manager import ws_manager
        await ws_manager.broadcast(org_id, {
            "type": "channel_created",
            "data": {
                "platform": "slack",
                "projectId": project.id,
                "channelId": channel_id,
                "channelName": actual_name,
            },
        })
    except Exception:
        pass

    logger.info(f"Created Slack channel #{actual_name} for project {project.name} ({invited}/{len(members)} members invited)")

    return {
        "ok": True,
        "channelId": channel_id,
        "channelName": actual_name,
        "invitedCount": invited,
        "totalMembers": len(members),
    }


# =====================================================================
# Link Existing Channel
# =====================================================================

@router.post("/link-channel")
async def link_existing_channel(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Link an existing Slack channel to a project."""
    org_id = current_user.get("organization_id", "demo-org")
    project_id = body.get("projectId")
    channel_id = body.get("channelId")
    channel_name = body.get("channelName", "")

    if not project_id or not channel_id:
        raise HTTPException(status_code=400, detail="projectId and channelId required")

    proj_result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == project_id,
            ImportedProject.organization_id == org_id,
        )
    )
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project.slack_channel_id = channel_id
    project.slack_channel_name = channel_name
    await db.commit()

    return {"ok": True, "channelId": channel_id, "channelName": channel_name}


# =====================================================================
# Get Project Channel
# =====================================================================

@router.get("/project-channel")
async def get_project_channel(
    projectId: str = Query(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get Slack channel info for a project."""
    org_id = current_user.get("organization_id", "demo-org")
    proj_result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == projectId,
            ImportedProject.organization_id == org_id,
        )
    )
    project = proj_result.scalar_one_or_none()
    if not project:
        return {"hasChannel": False}

    if project.slack_channel_id:
        return {
            "hasChannel": True,
            "channelId": project.slack_channel_id,
            "channelName": project.slack_channel_name,
        }
    return {"hasChannel": False}


# =====================================================================
# Post to Project Channel (Quick Actions)
# =====================================================================

@router.post("/post-to-channel")
async def post_to_project_channel(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Post a message to a project Slack channel. Used by quick actions."""
    org_id = current_user.get("organization_id", "demo-org")
    project_id = body.get("projectId")
    action_type = body.get("type")
    message_data = body.get("data", {})

    if not project_id:
        raise HTTPException(status_code=400, detail="projectId is required")

    # Get project + channel
    proj_result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == project_id,
            ImportedProject.organization_id == org_id,
        )
    )
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.slack_channel_id:
        return {
            "ok": False,
            "error": "channel_not_found",
            "message": f"No Slack channel for {project.name}. Ask your PO to create one from the Channels page.",
        }

    conn = await _get_slack_conn(db, org_id)
    if not conn or not conn.access_token:
        raise HTTPException(status_code=400, detail="Slack not connected")

    bot_token = _get_bot_token(conn)
    user_name = current_user.get("display_name") or current_user.get("email", "Unknown")

    text = ""
    blocks = None

    if action_type == "standup_to_channel":
        working_on = message_data.get("workingOn", "")
        completed = message_data.get("completed", "")
        blockers = message_data.get("blockers", "")
        sections = []
        if completed:
            sections.append(f"*Completed:* {completed}")
        if working_on:
            sections.append(f"*Working on:* {working_on}")
        if blockers:
            sections.append(f"*Blockers:* {blockers}")
        body_text = "\n".join(sections) if sections else "No specific updates"
        text = f"Standup from {user_name}"

        # Find team_member_id for the current user to link to their standup
        tm_result = await db.execute(
            select(TeamMember).where(
                TeamMember.organization_id == org_id,
                TeamMember.email.ilike(current_user.get("email", "")),
            ).limit(1)
        )
        tm = tm_result.scalar_one_or_none()
        tm_id = tm.id if tm else ""

        link = f"https://plan2sprint-web.purplebeach-150945ee.westus3.azurecontainerapps.io/po/standups"
        if tm_id:
            link += f"?developer={tm_id}"

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f":clipboard: *Standup Overview — {user_name}*\n{body_text}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_Quick overview only — full standup report available on Plan2Sprint_"}]},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "View on Plan2Sprint"}, "url": link, "style": "primary"},
            ]},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{project.name} • via Plan2Sprint_"}]},
        ]

    elif action_type == "blocker_to_channel":
        # Hotfix 78 — frontend now sends a structured ``blockerType``
        # (one of a curated set of categories) in place of the
        # freeform ticket reference. Older clients still send
        # ``ticket`` so we accept either; ``blockerType`` wins.
        blocker_type = message_data.get("blockerType") or message_data.get("ticket") or ""
        ticket = blocker_type  # store under the existing column name
        description = message_data.get("description", "")
        text = f"Blocker flagged by {user_name}"

        # Create a BlockerFlag record so we can attach action buttons to it.
        # Find or create today's StandupReport for this dev, then attach the blocker.
        from ...models.standup import BlockerFlag, StandupReport
        from datetime import date as _date, datetime as _dt, timezone as _tz
        import json as _json

        user_email = (current_user.get("email") or "").lower().strip()
        tm_result = await db.execute(
            select(TeamMember).where(
                TeamMember.organization_id == org_id,
                TeamMember.email.ilike(user_email),
            ).limit(1)
        )
        dev_tm = tm_result.scalar_one_or_none()

        # If no team_member exists for this user (e.g. imported tool used a
        # different email), create a self-referential one so the blocker has
        # a home and the dev's history query will find it. Scope it to the
        # current project so project-filter queries return it correctly.
        if not dev_tm and user_email:
            dev_tm = TeamMember(
                organization_id=org_id,
                imported_project_id=project.id,
                external_id=f"self:{user_email}:{project.id}",
                email=user_email,
                display_name=(current_user.get("full_name") or user_email.split("@")[0]),
                role="developer",
                skill_tags=[],
            )
            db.add(dev_tm)
            await db.flush()

        blocker_id = ""
        if dev_tm:
            today = _date.today()
            sr_q = await db.execute(
                select(StandupReport).where(
                    StandupReport.organization_id == org_id,
                    StandupReport.team_member_id == dev_tm.id,
                    func.date(StandupReport.report_date) == today,
                )
            )
            report = sr_q.scalar_one_or_none()
            if not report:
                report = StandupReport(
                    organization_id=org_id,
                    team_member_id=dev_tm.id,
                    report_date=_dt.now(_tz.utc),
                    completed_items=[],
                    in_progress_items=[],
                    blockers=[],
                    narrative_text="",
                )
                db.add(report)
                await db.flush()

            new_blocker = BlockerFlag(
                standup_report_id=report.id,
                description=description or "(no description)",
                ticket_reference=ticket or None,
                status="OPEN",
            )
            db.add(new_blocker)
            await db.flush()
            blocker_id = new_blocker.id
            await db.commit()

        action_ctx = _json.dumps({
            "blocker_id": blocker_id,
            "ticket_key": ticket,
            "org_id": org_id,
        })

        # Hotfix 78 — render the blocker type as a prominent tag at
        # the top (before the description) so the channel can scan
        # the category at a glance.
        type_tag = f"`{blocker_type}`" if blocker_type else "`Unspecified`"
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f":construction: *Blocker Flagged by {user_name}*\n\n*Type:* {type_tag}\n*Description:* {description}"}},
            {"type": "actions", "block_id": f"blocker_actions:{blocker_id}", "elements": [
                {
                    "type": "button",
                    "action_id": "escalate_blocker",
                    "text": {"type": "plain_text", "text": "🚨 Escalate"},
                    "style": "danger",
                    "value": action_ctx,
                },
                {
                    "type": "button",
                    "action_id": "resolve_blocker",
                    "text": {"type": "plain_text", "text": "✅ Resolve"},
                    "style": "primary",
                    "value": action_ctx,
                },
            ]},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{project.name} • via Plan2Sprint_"}]},
        ]

    elif action_type == "custom_message":
        msg = message_data.get("message", "")
        text = msg
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f":speech_balloon: *{user_name}:*\n{msg}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{project.name} • via Plan2Sprint_"}]},
        ]

    elif action_type == "announcement":
        msg = message_data.get("message", "")
        text = f"Announcement from {user_name}"
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"Announcement — {project.name}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": msg}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_From {user_name} • via Plan2Sprint_"}]},
        ]

    elif action_type == "sprint_plan_channel":
        # Fetch real sprint plan data for this project
        from ...models.sprint_plan import SprintPlan, PlanAssignment
        from ...models.work_item import WorkItem
        from sqlalchemy import func as sa_func

        plan_result = await db.execute(
            select(SprintPlan).where(
                SprintPlan.organization_id == org_id,
                SprintPlan.project_id == project_id,
                SprintPlan.status.in_(["APPROVED", "SYNCED", "SYNCED_PARTIAL", "PENDING_REVIEW"]),
            ).order_by(SprintPlan.created_at.desc()).limit(1)
        )
        plan = plan_result.scalar_one_or_none()

        if plan:
            sprint_name = f"Sprint Plan ({plan.estimated_sprints or '?'} sprints)"
            sp_total = int(plan.total_story_points or 0)
            # Count unique features (work items of type feature/epic referenced by assignments)
            feat_q = await db.execute(
                select(sa_func.count(sa_func.distinct(WorkItem.epic_id)))
                .select_from(PlanAssignment)
                .join(WorkItem, PlanAssignment.work_item_id == WorkItem.id)
                .where(PlanAssignment.sprint_plan_id == plan.id, WorkItem.epic_id.isnot(None))
            )
            features = feat_q.scalar() or 0
            if not features:
                # Fallback: count assignments
                cnt_q = await db.execute(
                    select(sa_func.count()).select_from(PlanAssignment).where(PlanAssignment.sprint_plan_id == plan.id)
                )
                features = cnt_q.scalar() or 0
            success = plan.success_probability or 0
        else:
            sprint_name = "No active sprint plan"
            sp_total = 0
            features = 0
            success = 0

        link = f"https://plan2sprint-web.purplebeach-150945ee.westus3.azurecontainerapps.io/po/planning"
        text = f"Sprint plan update — {project.name}"
        summary_lines = [f"*{sprint_name}*"]
        if sp_total > 0:
            summary_lines.append(f"• {sp_total} story points")
        if features > 0:
            summary_lines.append(f"• {features} features planned")
        if success > 0:
            summary_lines.append(f"• {success}% success probability")
        if not plan:
            summary_lines.append("_No approved sprint plan yet. Generate one in Plan2Sprint._")

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"📊 Sprint Plan — {project.name}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(summary_lines)}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "View on Plan2Sprint"}, "url": link, "style": "primary"},
            ]},
        ]

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action type: {action_type}")

    # Send
    send_payload = {"channel": project.slack_channel_id, "text": text}
    if blocks:
        send_payload["blocks"] = blocks

    result = await _slack_call("chat.postMessage", bot_token, send_payload)

    return {
        "ok": True,
        "type": action_type,
        "channel": project.slack_channel_id,
        "channelName": project.slack_channel_name,
        "ts": result.get("ts"),
    }

"""
Teams Project Channel Management — channels, posting, parent team selection.

Mirrors the Slack channel router but uses MS Graph API.
Endpoints: list-teams, select-parent-team, create-channel, project-channel, post-to-channel.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx
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

MS_GRAPH_API = "https://graph.microsoft.com/v1.0"


async def _get_teams_conn(db: AsyncSession, org_id: str) -> Optional[ToolConnection]:
    result = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == "TEAMS",
        )
    )
    return result.scalar_one_or_none()


async def _get_access_token(db: AsyncSession, conn: ToolConnection) -> str:
    """Get access token, refreshing if expired. Reuses logic from teams.py.

    If refresh fails (e.g. scope changed server-side and user hasn't re-consented),
    raise a 409 with code=reconsent_required so the UI can show a clean Reconnect CTA.
    """
    from .teams import _refresh_token_if_needed
    try:
        await _refresh_token_if_needed(db, conn)
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else str(e.detail)
        if "refresh" in detail.lower() or "reconnect" in detail.lower() or e.status_code in (401, 403):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "reconsent_required",
                    "message": (
                        "Microsoft Teams permissions have changed. "
                        "Please disconnect and reconnect Teams to grant the new permissions "
                        "(Team.ReadBasic.All, Channel.Create)."
                    ),
                },
            )
        raise
    from ...services.encryption import decrypt_token
    token = decrypt_token(conn.access_token)
    if not token:
        raise HTTPException(status_code=400, detail="Teams token unavailable")
    return token


async def _graph_call(method: str, endpoint: str, token: str, json_body: dict | None = None) -> dict:
    """Make a Microsoft Graph API call."""
    url = f"{MS_GRAPH_API}/{endpoint.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        if method == "GET":
            res = await client.get(url, headers=headers)
        elif method == "POST":
            res = await client.post(url, headers=headers, json=json_body or {})
        else:
            raise HTTPException(status_code=500, detail=f"Unsupported method: {method}")
        if res.status_code >= 400:
            try:
                err_data = res.json()
                err_msg = err_data.get("error", {}).get("message", res.text)
                err_code = err_data.get("error", {}).get("code", "")
            except Exception:
                err_msg = res.text
                err_code = ""
            # 401/403 on Graph usually means the current token doesn't carry the
            # required scope — user needs to reconnect to re-consent.
            if res.status_code in (401, 403) or err_code in ("Authorization_RequestDenied", "InvalidAuthenticationToken"):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "reconsent_required",
                        "message": (
                            "Microsoft Teams is missing required permissions. "
                            "Please disconnect and reconnect Teams to grant the new permissions "
                            "(Team.ReadBasic.All, Channel.Create)."
                        ),
                    },
                )
            raise HTTPException(status_code=400, detail=f"Graph API error: {err_msg}")
        try:
            return res.json()
        except Exception:
            return {}


# =====================================================================
# List Teams (for Parent Team selection)
# =====================================================================

@router.post("/list-teams")
async def list_joined_teams(
    body: dict = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all MS Teams the user is a member of. PO picks one as parent for project channels."""
    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_teams_conn(db, org_id)
    if not conn or not conn.access_token:
        raise HTTPException(status_code=400, detail="Teams not connected")

    token = await _get_access_token(db, conn)
    data = await _graph_call("GET", "/me/joinedTeams", token)
    teams = data.get("value", [])
    return {
        "teams": [
            {"id": t["id"], "displayName": t.get("displayName", ""), "description": t.get("description", "")}
            for t in teams
        ]
    }


# =====================================================================
# Select Parent Team (stored in ToolConnection.config)
# =====================================================================

@router.post("/select-parent-team")
async def select_parent_team(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store the MS Team ID that will host all Plan2Sprint project channels."""
    org_id = current_user.get("organization_id", "demo-org")
    team_id = body.get("teamId")
    team_name = body.get("teamName", "")
    if not team_id:
        raise HTTPException(status_code=400, detail="teamId is required")

    conn = await _get_teams_conn(db, org_id)
    if not conn:
        raise HTTPException(status_code=400, detail="Teams not connected")

    config = dict(conn.config or {})
    config["parent_team_id"] = team_id
    config["parent_team_name"] = team_name
    conn.config = config
    await db.commit()

    return {"ok": True, "parentTeamId": team_id, "parentTeamName": team_name}


@router.get("/parent-team")
async def get_parent_team(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the currently selected parent Team for this org."""
    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_teams_conn(db, org_id)
    if not conn:
        return {"selected": False}
    config = conn.config or {}
    if config.get("parent_team_id"):
        return {
            "selected": True,
            "parentTeamId": config["parent_team_id"],
            "parentTeamName": config.get("parent_team_name", ""),
        }
    return {"selected": False}


# =====================================================================
# Create Project Channel
# =====================================================================

@router.post("/create-channel")
async def create_project_channel(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a channel inside the selected parent Team for a project."""
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

    if project.teams_channel_id:
        return {
            "ok": True,
            "channelId": project.teams_channel_id,
            "channelName": project.teams_channel_name,
            "alreadyExists": True,
        }

    conn = await _get_teams_conn(db, org_id)
    if not conn or not conn.access_token:
        raise HTTPException(status_code=400, detail="Teams not connected")

    config = conn.config or {}
    parent_team_id = config.get("parent_team_id")
    if not parent_team_id:
        raise HTTPException(
            status_code=400,
            detail="No parent Team selected. Please select a parent Team first.",
        )

    token = await _get_access_token(db, conn)

    # Channel display name: "{Project}-P2S" — Teams keeps original casing.
    # Teams channel names disallow a handful of characters (# % & * : < > ? / \ { | }),
    # but allow spaces, letters, digits, hyphens, and underscores.
    raw = re.sub(r'[#%&*:<>?/\\{|}]', '', project.name).strip()
    # Keep within ~45 chars so we can safely append "-P2S"
    safe = raw[:45] if len(raw) > 45 else raw
    channel_name = f"{safe}-P2S"

    try:
        result = await _graph_call("POST", f"/teams/{parent_team_id}/channels", token, {
            "displayName": channel_name,
            "description": f"Plan2Sprint project channel for {project.name}",
            "membershipType": "standard",
        })
        channel_id = result.get("id", "")
        actual_name = result.get("displayName", channel_name)
    except HTTPException as e:
        # If channel already exists with same name, try to find it
        if "already exists" in str(e.detail).lower() or "nameAlreadyExists" in str(e.detail):
            try:
                list_result = await _graph_call("GET", f"/teams/{parent_team_id}/channels", token)
                channels = list_result.get("value", [])
                existing = next((c for c in channels if c.get("displayName") == channel_name), None)
                if existing:
                    channel_id = existing["id"]
                    actual_name = existing["displayName"]
                else:
                    raise HTTPException(status_code=400, detail=f"Channel name taken but not found")
            except Exception as ex:
                raise HTTPException(status_code=400, detail=f"Could not find existing channel: {ex}")
        else:
            raise

    # Store mapping
    project.teams_channel_id = channel_id
    project.teams_channel_name = actual_name
    await db.commit()

    # Broadcast so all pages (PO + dev) refresh without a manual reload
    try:
        from ...services.ws_manager import ws_manager
        await ws_manager.broadcast(org_id, {
            "type": "channel_created",
            "data": {
                "platform": "teams",
                "projectId": project.id,
                "channelId": channel_id,
                "channelName": actual_name,
            },
        })
    except Exception:
        pass

    logger.info(f"Created Teams channel {actual_name} for project {project.name}")

    return {
        "ok": True,
        "channelId": channel_id,
        "channelName": actual_name,
        "parentTeamId": parent_team_id,
    }


# =====================================================================
# Get Project Channel
# =====================================================================

@router.get("/project-channel")
async def get_project_channel(
    projectId: str = Query(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get Teams channel info for a project."""
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

    if project.teams_channel_id:
        return {
            "hasChannel": True,
            "channelId": project.teams_channel_id,
            "channelName": project.teams_channel_name,
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
    """Post a message to a project Teams channel. Used by quick actions."""
    org_id = current_user.get("organization_id", "demo-org")
    project_id = body.get("projectId")
    action_type = body.get("type")
    message_data = body.get("data", {})

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

    if not project.teams_channel_id:
        return {
            "ok": False,
            "error": "channel_not_found",
            "message": f"No Teams channel for {project.name}. Ask your PO to create one from the Channels page.",
        }

    conn = await _get_teams_conn(db, org_id)
    if not conn or not conn.access_token:
        raise HTTPException(status_code=400, detail="Teams not connected")

    config = conn.config or {}
    parent_team_id = config.get("parent_team_id")
    if not parent_team_id:
        raise HTTPException(status_code=400, detail="No parent Team configured")

    token = await _get_access_token(db, conn)
    user_name = current_user.get("display_name") or current_user.get("email", "Unknown")

    # Build HTML content based on action type
    base_url = "https://plan2sprint-web.purplebeach-150945ee.westus3.azurecontainerapps.io"
    content_html = ""

    if action_type == "standup_to_channel":
        working_on = message_data.get("workingOn", "")
        completed = message_data.get("completed", "")
        blockers = message_data.get("blockers", "")

        # Find team_member_id for View on Plan2Sprint link
        tm_result = await db.execute(
            select(TeamMember).where(
                TeamMember.organization_id == org_id,
                TeamMember.email.ilike(current_user.get("email", "")),
            ).limit(1)
        )
        tm = tm_result.scalar_one_or_none()
        link = f"{base_url}/po/standups"
        if tm:
            link += f"?developer={tm.id}"

        body_parts = []
        if completed:
            body_parts.append(f"<li><b>Completed:</b> {completed}</li>")
        if working_on:
            body_parts.append(f"<li><b>Working on:</b> {working_on}</li>")
        if blockers:
            body_parts.append(f"<li><b>Blockers:</b> {blockers}</li>")
        body_list = "".join(body_parts) if body_parts else "<li>No specific updates</li>"

        content_html = (
            f"<div><p>📋 <b>Standup Overview — {user_name}</b></p>"
            f"<ul>{body_list}</ul>"
            f"<p><i>Quick overview only — full standup report available on Plan2Sprint</i></p>"
            f'<p><a href="{link}">View on Plan2Sprint →</a></p>'
            f"<p><i>{project.name} • via Plan2Sprint</i></p></div>"
        )

    elif action_type == "blocker_to_channel":
        # Hotfix 78 — frontend now sends a structured ``blockerType``
        # in place of the freeform ticket reference. Older clients
        # still send ``ticket`` so we accept either.
        blocker_type = message_data.get("blockerType") or message_data.get("ticket") or ""
        ticket = blocker_type
        description = message_data.get("description", "")

        # Create a BlockerFlag record so action buttons have something to act on
        from ...models.standup import BlockerFlag, StandupReport
        from datetime import date as _date, datetime as _dt, timezone as _tz

        user_email = (current_user.get("email") or "").lower().strip()
        tm_result = await db.execute(
            select(TeamMember).where(
                TeamMember.organization_id == org_id,
                TeamMember.email.ilike(user_email),
            ).limit(1)
        )
        dev_tm = tm_result.scalar_one_or_none()

        # Fallback: create self team_member if none exists for this user,
        # scoped to the current project so project-filtered queries find it.
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

        # Build signed URLs for Escalate / Resolve
        from ...services.teams_action_signer import build_signed_action_url
        escalate_url = build_signed_action_url(blocker_id, "escalate", org_id)
        resolve_url = build_signed_action_url(blocker_id, "resolve", org_id)

        # Adaptive Card with two Action.OpenUrl buttons
        adaptive_card = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"🚧 **Blocker Flagged by {user_name}**",
                    "weight": "Bolder",
                    "size": "Medium",
                    "wrap": True,
                },
                {
                    "type": "FactSet",
                    "facts": [
                        # Hotfix 78 — type-of-blocker tag in place of ticket ref.
                        {"title": "Type", "value": blocker_type or "Unspecified"},
                        {"title": "Description", "value": description[:300] or "(no description)"},
                        {"title": "Project", "value": project.name},
                    ],
                },
                {
                    "type": "TextBlock",
                    "text": "via Plan2Sprint",
                    "isSubtle": True,
                    "size": "Small",
                    "spacing": "Medium",
                },
            ],
            "actions": [
                {
                    "type": "Action.OpenUrl",
                    "title": "🚨 Escalate",
                    "url": escalate_url,
                    "style": "destructive",
                },
                {
                    "type": "Action.OpenUrl",
                    "title": "✅ Resolve",
                    "url": resolve_url,
                    "style": "positive",
                },
            ],
        }

        # Use attachment-based message body — the text-body references the attachment
        import uuid as _uuid
        attachment_id = str(_uuid.uuid4())
        content_html = f'<attachment id="{attachment_id}"></attachment>'
        # Stash the attachments list for later use by the graph call
        teams_attachments = [
            {
                "id": attachment_id,
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": json.dumps(adaptive_card),
            }
        ]

    elif action_type == "custom_message":
        msg = message_data.get("message", "")
        content_html = (
            f"<div><p>💬 <b>{user_name}:</b></p>"
            f"<p>{msg}</p>"
            f"<p><i>{project.name} • via Plan2Sprint</i></p></div>"
        )

    elif action_type == "announcement":
        msg = message_data.get("message", "")
        content_html = (
            f"<div><h3>📢 Announcement — {project.name}</h3>"
            f"<p>{msg}</p>"
            f"<p><i>From {user_name} • via Plan2Sprint</i></p></div>"
        )

    elif action_type == "sprint_plan_channel":
        # Fetch real sprint plan data
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
            feat_q = await db.execute(
                select(sa_func.count(sa_func.distinct(WorkItem.epic_id)))
                .select_from(PlanAssignment)
                .join(WorkItem, PlanAssignment.work_item_id == WorkItem.id)
                .where(PlanAssignment.sprint_plan_id == plan.id, WorkItem.epic_id.isnot(None))
            )
            features = feat_q.scalar() or 0
            success = plan.success_probability or 0
            body_list = f"<li>{sp_total} story points</li><li>{features} features planned</li>"
            if success > 0:
                body_list += f"<li>{success}% success probability</li>"
        else:
            sprint_name = "No active sprint plan"
            body_list = "<li><i>No approved sprint plan yet. Generate one in Plan2Sprint.</i></li>"

        content_html = (
            f"<div><h3>📊 Sprint Plan — {project.name}</h3>"
            f"<p><b>{sprint_name}</b></p>"
            f"<ul>{body_list}</ul>"
            f'<p><a href="{base_url}/po/planning">View on Plan2Sprint →</a></p></div>'
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action type: {action_type}")

    # Build the Graph API payload (include attachments if the action set any)
    graph_body: dict = {
        "body": {
            "contentType": "html",
            "content": content_html,
        }
    }
    try:
        teams_attachments  # noqa: F821 — may be defined by specific action types
        graph_body["attachments"] = teams_attachments  # type: ignore[name-defined]
    except NameError:
        pass

    # Post to channel via Graph API
    try:
        result = await _graph_call(
            "POST",
            f"/teams/{parent_team_id}/channels/{project.teams_channel_id}/messages",
            token,
            graph_body,
        )
    except HTTPException as e:
        return {"ok": False, "error": "send_failed", "message": str(e.detail)}

    return {
        "ok": True,
        "type": action_type,
        "channelId": project.teams_channel_id,
        "channelName": project.teams_channel_name,
        "messageId": result.get("id", ""),
    }

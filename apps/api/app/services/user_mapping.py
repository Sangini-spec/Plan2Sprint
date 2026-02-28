"""
User mapping service.
Matches Slack/Teams user accounts to Plan2Sprint team members by email.

Flow:
1. Fetch all workspace users from Slack/Teams API
2. Fetch all TeamMember records for the org
3. Match by email (case-insensitive)
4. Update TeamMember.slack_user_id or teams_user_id
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.team_member import TeamMember
from ..models.tool_connection import ToolConnection
from ..services.encryption import decrypt_token
from ..config import settings
import httpx


# ---------------------------------------------------------------------------
# SLACK USER MAPPING
# ---------------------------------------------------------------------------

async def map_slack_users(db: AsyncSession, org_id: str) -> dict:
    """
    Fetch Slack workspace users and map them to TeamMembers by email.
    Returns summary: { mapped: int, unmapped: int, errors: [] }
    """
    # Get Slack connection
    result = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == "SLACK",
        )
    )
    conn = result.scalar_one_or_none()

    if not conn:
        return {"mapped": 0, "unmapped": 0, "errors": ["Slack not connected"]}

    bot_token = decrypt_token(conn.access_token)

    # Fetch all Slack users with pagination
    slack_users: dict[str, str] = {}  # email -> slack_user_id
    cursor = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: dict = {"limit": 200}
            if cursor:
                params["cursor"] = cursor

            res = await client.get(
                "https://slack.com/api/users.list",
                headers={"Authorization": f"Bearer {bot_token}"},
                params=params,
            )
            data = res.json()

            if not data.get("ok"):
                return {
                    "mapped": 0,
                    "unmapped": 0,
                    "errors": [f"Slack API error: {data.get('error')}"],
                }

            for member in data.get("members", []):
                if member.get("is_bot") or member.get("deleted") or member.get("id") == "USLACKBOT":
                    continue
                email = member.get("profile", {}).get("email", "").lower().strip()
                if email:
                    slack_users[email] = member["id"]

            next_cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                break
            cursor = next_cursor

    # Fetch all team members for this org
    result = await db.execute(
        select(TeamMember).where(TeamMember.organization_id == org_id)
    )
    team_members = result.scalars().all()

    mapped = 0
    unmapped = 0

    for tm in team_members:
        email = (tm.email or "").lower().strip()
        if email in slack_users:
            tm.slack_user_id = slack_users[email]
            mapped += 1
        else:
            unmapped += 1

    await db.commit()

    return {
        "mapped": mapped,
        "unmapped": unmapped,
        "total_slack_users": len(slack_users),
        "total_team_members": len(team_members),
        "errors": [],
    }


# ---------------------------------------------------------------------------
# TEAMS USER MAPPING
# ---------------------------------------------------------------------------

async def map_teams_users(db: AsyncSession, org_id: str) -> dict:
    """
    Fetch MS Graph users and map them to TeamMembers by email.
    Returns summary: { mapped: int, unmapped: int, errors: [] }
    """
    result = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == "TEAMS",
        )
    )
    conn = result.scalar_one_or_none()

    if not conn:
        return {"mapped": 0, "unmapped": 0, "errors": ["Teams not connected"]}

    access_token = decrypt_token(conn.access_token)

    # Fetch all users from Graph API
    teams_users: dict[str, str] = {}  # email -> graph_user_id
    endpoint = "https://graph.microsoft.com/v1.0/users?$select=id,mail,userPrincipalName&$top=100"

    async with httpx.AsyncClient(timeout=30.0) as client:
        while endpoint:
            res = await client.get(
                endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if res.is_error:
                return {
                    "mapped": 0,
                    "unmapped": 0,
                    "errors": [f"Graph API error: {res.status_code}"],
                }

            data = res.json()

            for user in data.get("value", []):
                email = (user.get("mail") or user.get("userPrincipalName") or "").lower().strip()
                if email:
                    teams_users[email] = user["id"]

            endpoint = data.get("@odata.nextLink")

    # Match to team members
    result = await db.execute(
        select(TeamMember).where(TeamMember.organization_id == org_id)
    )
    team_members = result.scalars().all()

    mapped = 0
    unmapped = 0

    for tm in team_members:
        email = (tm.email or "").lower().strip()
        if email in teams_users:
            tm.teams_user_id = teams_users[email]
            mapped += 1
        else:
            unmapped += 1

    await db.commit()

    return {
        "mapped": mapped,
        "unmapped": unmapped,
        "total_teams_users": len(teams_users),
        "total_team_members": len(team_members),
        "errors": [],
    }


# ---------------------------------------------------------------------------
# GET MAPPED USER IDS
# ---------------------------------------------------------------------------

async def get_slack_user_id(
    db: AsyncSession, org_id: str, member_email: str
) -> Optional[str]:
    """Get the Slack user ID for a team member by email."""
    result = await db.execute(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
            func.lower(TeamMember.email) == member_email.lower().strip(),
        )
    )
    member = result.scalar_one_or_none()
    return member.slack_user_id if member else None


async def get_teams_user_id(
    db: AsyncSession, org_id: str, member_email: str
) -> Optional[str]:
    """Get the Teams/Graph user ID for a team member by email."""
    result = await db.execute(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
            func.lower(TeamMember.email) == member_email.lower().strip(),
        )
    )
    member = result.scalar_one_or_none()
    return member.teams_user_id if member else None

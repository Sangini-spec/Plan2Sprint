"""
Organization & Team Management API.

GET    /current                           - Get current org details
PATCH  /current                           - Update org settings (admin+)
GET    /current/members                   - List org members (users + team_members)
PATCH  /current/members/:id               - Update member role (admin+)
DELETE /current/members/:id               - Remove member (admin+, block last owner)
POST   /current/invitations               - Create invitation (admin+)
GET    /current/invitations               - List pending invitations (admin+)
DELETE /current/invitations/:id           - Revoke invitation (admin+)
POST   /current/invitations/:id/resend    - Resend invitation email (admin+)
GET    /invitations/:token                - Get invitation by token (public)
POST   /invitations/:token/accept         - Accept invitation (authed)
"""

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sa_delete, text

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models.organization import Organization
from ..models.user import User
from ..models.team_member import TeamMember
from ..models.invitation import Invitation
from ..models.imported_project import ImportedProject, StakeholderProjectAssignment
from ..models.work_item import WorkItem
from ..models.base import generate_cuid
from ..config import settings as app_settings
from ..email import send_invite_email

router = APIRouter()

ADMIN_ROLES = {"owner", "admin", "product_owner"}
VALID_ROLES = {"product_owner", "developer", "stakeholder"}


def _is_admin(role: str | None) -> bool:
    return (role or "").lower() in {"owner", "admin", "product_owner"}


def _require_admin(current_user: dict):
    if not _is_admin(current_user.get("role")):
        raise HTTPException(status_code=403, detail="Admin or Owner role required")


# ---------------------------------------------------------------------------
# Organization CRUD
# ---------------------------------------------------------------------------

@router.get("/current")
async def get_current_org(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")
    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        # Auto-create org for the current user (handles demo + first-run)
        org = Organization(
            id=org_id,
            name=current_user.get("organization_name", "My Organization"),
            slug=org_id,
        )
        db.add(org)
        await db.commit()
        await db.refresh(org)

    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "timezone": org.timezone,
        "workingHoursStart": org.working_hours_start,
        "workingHoursEnd": org.working_hours_end,
        "standupTime": org.standup_time,
        "createdAt": org.created_at.isoformat() if org.created_at else None,
    }


@router.patch("/current")
async def update_current_org(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)
    org_id = current_user.get("organization_id", "demo-org")

    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        # Auto-create for first-run
        org = Organization(
            id=org_id,
            name=current_user.get("organization_name", "My Organization"),
            slug=org_id,
        )
        db.add(org)
        await db.flush()

    allowed = {"name", "timezone", "workingHoursStart", "workingHoursEnd", "standupTime"}
    field_map = {
        "name": "name",
        "timezone": "timezone",
        "workingHoursStart": "working_hours_start",
        "workingHoursEnd": "working_hours_end",
        "standupTime": "standup_time",
    }

    for key, val in body.items():
        if key in allowed and val is not None:
            setattr(org, field_map[key], val)

    await db.commit()
    await db.refresh(org)

    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "timezone": org.timezone,
        "workingHoursStart": org.working_hours_start,
        "workingHoursEnd": org.working_hours_end,
        "standupTime": org.standup_time,
    }


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@router.get("/current/members")
async def list_members(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")

    # 1) Fetch Users (active Plan2Sprint accounts), exclude demo user
    user_result = await db.execute(
        select(User).where(User.organization_id == org_id)
    )
    users = [u for u in user_result.scalars().all()
             if u.email.lower() != "demo@plan2sprint.app"]

    # 2) Fetch TeamMembers synced from tools (may or may not have a User account)
    tm_result = await db.execute(
        select(TeamMember).where(TeamMember.organization_id == org_id)
    )
    team_members = tm_result.scalars().all()

    # 3) Check Supabase auth.users to determine who has ever logged in
    active_emails: set[str] = set()
    try:
        auth_result = await db.execute(
            text("SELECT email FROM auth.users WHERE last_sign_in_at IS NOT NULL")
        )
        active_emails = {row[0].lower() for row in auth_result.all()}
    except Exception:
        pass  # If auth.users is inaccessible, fall back to users table

    # 4) Fetch project assignments: member_id -> list of project names
    #    Sources: WorkItem assignees + StakeholderProjectAssignment (manual assigns)
    project_map: dict[str, list[dict]] = {}  # member_id -> [{id, name}]
    proj_result = await db.execute(
        select(
            WorkItem.assignee_id,
            ImportedProject.id,
            ImportedProject.name,
        )
        .join(ImportedProject, WorkItem.imported_project_id == ImportedProject.id)
        .where(
            WorkItem.organization_id == org_id,
            WorkItem.assignee_id.isnot(None),
        )
        .distinct()
    )
    for row in proj_result.all():
        tm_id = row[0]
        if tm_id not in project_map:
            project_map[tm_id] = []
        project_map[tm_id].append({"id": row[1], "name": row[2]})

    # Also include manually assigned projects (StakeholderProjectAssignment)
    assign_result = await db.execute(
        select(
            StakeholderProjectAssignment.user_id,
            ImportedProject.id,
            ImportedProject.name,
        )
        .join(ImportedProject, StakeholderProjectAssignment.imported_project_id == ImportedProject.id)
        .where(StakeholderProjectAssignment.organization_id == org_id)
    )
    for row in assign_result.all():
        uid = row[0]
        if uid not in project_map:
            project_map[uid] = []
        # Avoid duplicates
        if not any(p["id"] == row[1] for p in project_map[uid]):
            project_map[uid].append({"id": row[1], "name": row[2]})

    # 5) Build unified member list
    members = []
    seen_emails: set[str] = set()

    # Users first (these have Plan2Sprint accounts)
    for u in users:
        email_lower = u.email.lower()
        seen_emails.add(email_lower)

        matching_tm = next(
            (tm for tm in team_members if tm.email.lower() == email_lower), None
        )
        # Merge projects from work items (by tm.id) + manual assignments (by user.id)
        projects_by_tm = project_map.get(matching_tm.id, []) if matching_tm else []
        projects_by_user = project_map.get(u.id, [])
        seen_proj_ids = {p["id"] for p in projects_by_tm}
        projects = projects_by_tm + [p for p in projects_by_user if p["id"] not in seen_proj_ids]

        members.append({
            "id": u.id,
            "teamMemberId": matching_tm.id if matching_tm else None,
            "type": "user",
            "email": u.email,
            "displayName": u.full_name,
            "avatarUrl": u.avatar_url or (matching_tm.avatar_url if matching_tm else None),
            "role": u.role.lower() if u.role else "developer",
            "isActive": email_lower in active_emails,
            "projects": projects,
            "createdAt": u.created_at.isoformat() if u.created_at else None,
        })

    # TeamMembers who don't have a User account (synced from tools)
    for tm in team_members:
        email_lower = tm.email.lower()
        if email_lower in seen_emails:
            continue
        seen_emails.add(email_lower)
        projects = project_map.get(tm.id, [])

        members.append({
            "id": tm.id,
            "teamMemberId": tm.id,
            "type": "team_member",
            "email": tm.email,
            "displayName": tm.display_name,
            "avatarUrl": tm.avatar_url,
            "role": tm.role.lower() if tm.role else "developer",
            "isActive": email_lower in active_emails,
            "projects": projects,
            "createdAt": tm.created_at.isoformat() if tm.created_at else None,
        })

    return {"members": members}


@router.patch("/current/members/{member_id}")
async def update_member_role(
    member_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)
    org_id = current_user.get("organization_id", "demo-org")

    new_role = (body.get("role") or "").lower()
    if new_role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {new_role}")

    # Try User first
    result = await db.execute(
        select(User).where(User.id == member_id, User.organization_id == org_id)
    )
    user = result.scalar_one_or_none()
    if user:
        # Block demoting last owner
        if user.role.lower() == "owner" and new_role != "owner":
            owner_count = await _count_owners(db, org_id)
            if owner_count <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot change role — this is the only owner"
                )
        user.role = new_role.upper()
        await db.commit()
        return {"ok": True, "role": new_role}

    # Try TeamMember if User not found
    tm_result = await db.execute(
        select(TeamMember).where(TeamMember.id == member_id, TeamMember.organization_id == org_id)
    )
    tm = tm_result.scalar_one_or_none()
    if tm:
        tm.role = new_role
        await db.commit()
        return {"ok": True, "role": new_role}

    raise HTTPException(status_code=404, detail="Member not found")


@router.delete("/current/members/{member_id}")
async def remove_member(
    member_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)
    org_id = current_user.get("organization_id", "demo-org")

    result = await db.execute(
        select(User).where(User.id == member_id, User.organization_id == org_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Member not found")

    if user.role.lower() == "owner":
        owner_count = await _count_owners(db, org_id)
        if owner_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the only owner"
            )

    # Prevent self-removal
    caller_id = current_user.get("sub") or current_user.get("id")
    if user.supabase_user_id == caller_id or user.id == caller_id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    await db.delete(user)
    await db.commit()
    return {"ok": True}


async def _count_owners(db: AsyncSession, org_id: str) -> int:
    result = await db.execute(
        select(User).where(
            User.organization_id == org_id,
            User.role.in_(["OWNER", "owner"]),
        )
    )
    return len(result.scalars().all())


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

@router.post("/current/invitations")
async def create_invitation(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)
    org_id = current_user.get("organization_id", "demo-org")

    email = (body.get("email") or "").strip().lower()
    role = (body.get("role") or "developer").lower()

    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {role}")

    # Check for existing member
    existing = await db.execute(
        select(User).where(User.email == email, User.organization_id == org_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member")

    # Check for existing pending invite
    existing_inv = await db.execute(
        select(Invitation).where(
            Invitation.email == email,
            Invitation.organization_id == org_id,
            Invitation.status == "pending",
        )
    )
    if existing_inv.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Pending invitation already exists for this email")

    invitation = Invitation(
        organization_id=org_id,
        email=email,
        role=role,
        invited_by=current_user.get("email", "unknown"),
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    # Build invite URL
    frontend_url = app_settings.frontend_url.rstrip("/")
    invite_url = f"{frontend_url}/invite/{invitation.token}"

    # Fetch org name for email
    org_result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    org_name = org.name if org else "Plan2Sprint"

    # Send branded invitation email (best-effort)
    email_sent = False
    try:
        email_sent = await send_invite_email(
            to_email=email,
            invite_url=invite_url,
            org_name=org_name,
            role=role,
            invited_by=current_user.get("full_name", current_user.get("email", "A team member")),
        )
    except Exception:
        pass

    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role,
        "status": invitation.status,
        "inviteUrl": invite_url,
        "emailSent": email_sent,
        "expiresAt": invitation.expires_at.isoformat() if invitation.expires_at else None,
        "createdAt": invitation.created_at.isoformat() if invitation.created_at else None,
    }


@router.get("/current/invitations")
async def list_invitations(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)
    org_id = current_user.get("organization_id", "demo-org")

    result = await db.execute(
        select(Invitation)
        .where(Invitation.organization_id == org_id)
        .order_by(Invitation.created_at.desc())
    )
    invitations = result.scalars().all()

    now = datetime.now(timezone.utc)
    items = []
    for inv in invitations:
        status = inv.status
        if status == "pending" and inv.expires_at and inv.expires_at < now:
            status = "expired"
        items.append({
            "id": inv.id,
            "email": inv.email,
            "role": inv.role,
            "status": status,
            "invitedBy": inv.invited_by,
            "expiresAt": inv.expires_at.isoformat() if inv.expires_at else None,
            "createdAt": inv.created_at.isoformat() if inv.created_at else None,
        })

    return {"invitations": items}


@router.delete("/current/invitations/{invitation_id}")
async def revoke_invitation(
    invitation_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)
    org_id = current_user.get("organization_id", "demo-org")

    result = await db.execute(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.organization_id == org_id,
        )
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")

    await db.delete(inv)
    await db.commit()
    return {"ok": True}


@router.post("/current/invitations/{invitation_id}/resend")
async def resend_invitation(
    invitation_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)
    org_id = current_user.get("organization_id", "demo-org")

    result = await db.execute(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.organization_id == org_id,
            Invitation.status == "pending",
        )
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found or not pending")

    # Refresh expiry
    inv.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db.commit()
    await db.refresh(inv)

    frontend_url = app_settings.frontend_url.rstrip("/")
    invite_url = f"{frontend_url}/invite/{inv.token}"

    # Fetch org name for email
    org_result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    org_name = org.name if org else "Plan2Sprint"

    email_sent = False
    try:
        email_sent = await send_invite_email(
            to_email=inv.email,
            invite_url=invite_url,
            org_name=org_name,
            role=inv.role,
            invited_by=current_user.get("full_name", current_user.get("email", "A team member")),
        )
    except Exception:
        pass

    return {
        "ok": True,
        "inviteUrl": invite_url,
        "emailSent": email_sent,
        "expiresAt": inv.expires_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Public token endpoints (no org scope)
# ---------------------------------------------------------------------------

@router.get("/invitations/{token}")
async def get_invitation_by_token(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invitation).where(Invitation.token == token)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")

    now = datetime.now(timezone.utc)
    status = inv.status
    if status == "pending" and inv.expires_at and inv.expires_at < now:
        status = "expired"

    # Get org name
    org_result = await db.execute(
        select(Organization).where(Organization.id == inv.organization_id)
    )
    org = org_result.scalar_one_or_none()

    return {
        "id": inv.id,
        "email": inv.email,
        "role": inv.role,
        "status": status,
        "organizationName": org.name if org else "Unknown",
        "expiresAt": inv.expires_at.isoformat() if inv.expires_at else None,
    }


@router.post("/invitations/{token}/accept")
async def accept_invitation(
    token: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invitation).where(Invitation.token == token)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if inv.status != "pending":
        raise HTTPException(status_code=400, detail=f"Invitation is {inv.status}")

    now = datetime.now(timezone.utc)
    if inv.expires_at and inv.expires_at < now:
        inv.status = "expired"
        await db.commit()
        raise HTTPException(status_code=400, detail="Invitation has expired")

    # Check if user already exists in this org
    user_email = current_user.get("email", "")
    existing = await db.execute(
        select(User).where(
            User.email == user_email,
            User.organization_id == inv.organization_id,
        )
    )
    if existing.scalar_one_or_none():
        inv.status = "accepted"
        inv.accepted_at = now
        await db.commit()
        return {"ok": True, "message": "Already a member of this organization"}

    # Create user record
    new_user = User(
        email=user_email,
        full_name=current_user.get("full_name", current_user.get("user_metadata", {}).get("full_name", user_email)),
        role=inv.role.upper(),
        supabase_user_id=current_user.get("sub", generate_cuid()),
        organization_id=inv.organization_id,
    )
    db.add(new_user)

    inv.status = "accepted"
    inv.accepted_at = now
    await db.commit()

    return {"ok": True, "message": "Invitation accepted", "organizationId": inv.organization_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


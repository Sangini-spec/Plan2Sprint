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
from sqlalchemy import select, delete as sa_delete, text, update as sa_update, func as sa_func

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
    """Update the caller's current organisation.

    Hotfix 85 — when ``name`` is in the patch body, we now treat the
    new name as a canonical-match candidate against existing orgs:

      1. Compute ``canonical = lower(trim(new_name))``.
      2. If another org already has that canonical:
         a. Caller is the SOLE user of their current org → migrate the
            caller (and any data they own under that org) into the
            matched existing org, delete the now-empty placeholder.
            This is the OAuth flow: PO signs up via Google → lands in
            "Sangini Tripathi's Organization" → goes to Settings →
            renames to "C2A" → ends up inside the real C2A tenant.
         b. Caller's org has OTHER users → reject with 409. Renaming a
            shared org into an existing one would yank everyone else
            into the new tenant; force the caller to go through a
            manual support flow instead.
      3. If no match: just update the row's ``name`` + ``name_canonical``.
         The unique index makes the in-place rename safe — collisions
         would have been caught above.

    Non-name fields (timezone, working hours, etc.) bypass the
    canonical machinery entirely and update the current org row only.
    """
    _require_admin(current_user)
    org_id = current_user.get("organization_id", "demo-org")

    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        # Auto-create for first-run
        from ..services.org_lookup import canonicalize_org_name as _canon
        fallback_name = current_user.get("organization_name", "My Organization")
        org = Organization(
            id=org_id,
            name=fallback_name,
            slug=org_id,
            name_canonical=_canon(fallback_name) or f"placeholder-{org_id[:8]}",
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

    # Hotfix 85 — handle the ``name`` change with canonical-match
    # logic BEFORE the generic setattr loop, so we can either redirect
    # the caller to an existing org (and skip the in-place rename) or
    # update both ``name`` AND ``name_canonical`` together.
    requested_name = body.get("name")
    name_handled = False
    if requested_name is not None and isinstance(requested_name, str):
        from ..services.org_lookup import (
            canonicalize_org_name,
            find_org_by_name,
        )
        new_canonical = canonicalize_org_name(requested_name)
        if not new_canonical:
            raise HTTPException(
                status_code=400,
                detail="Organization name cannot be empty.",
            )

        if new_canonical != org.name_canonical:
            # User actually changed the name (not just casing /
            # whitespace tweaks within the same canonical bucket).
            existing_match = await find_org_by_name(db, requested_name)
            if existing_match and existing_match.id != org.id:
                # An organisation with this canonical name already
                # exists. Decide whether to migrate the caller into it
                # or refuse.
                _other_users_q = await db.execute(
                    select(User).where(
                        User.organization_id == org.id,
                        User.id != current_user.get("user_id", current_user.get("id")),
                    )
                )
                other_users = _other_users_q.scalars().all()
                if other_users:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"An organisation named '{existing_match.name}' "
                            f"already exists. Your current organisation has "
                            f"other members, so it can't be merged "
                            f"automatically. Contact support if you intended "
                            f"to join the existing organisation."
                        ),
                    )

                # Sole-user case — Hotfix 86 gates the migration behind
                # founder approval. Was previously an auto-migrate; now
                # we create an OrgJoinRequest and let the target org's
                # founder accept/reject from the Invitations page.
                #
                # SECURITY rationale: name-only matching is generous (a
                # stranger who guesses "C2A" would have been auto-let-
                # in by the original auto-migrate path). The approval
                # gate makes joining an existing tenant a deliberate
                # act by someone already inside it.
                from ..models.org_join_request import (
                    OrgJoinRequest, STATUS_PENDING,
                )
                from ..services.org_join_flow import get_org_founder

                # Find the requester's User row
                requester_email = (current_user.get("email") or "").lower().strip()
                req_q = await db.execute(
                    select(User).where(User.email == requester_email)
                )
                requester = req_q.scalar_one_or_none()
                if not requester:
                    raise HTTPException(
                        status_code=403, detail="Requester not found in DB"
                    )

                # Reject duplicate open requests
                dup_q = await db.execute(
                    select(OrgJoinRequest).where(
                        OrgJoinRequest.requester_user_id == requester.id,
                        OrgJoinRequest.target_org_id == existing_match.id,
                        OrgJoinRequest.status == STATUS_PENDING,
                    )
                )
                dup = dup_q.scalar_one_or_none()
                if dup:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"You already have a pending request to join "
                            f"'{existing_match.name}'. Wait for it to be "
                            f"approved or cancel it first."
                        ),
                    )

                founder = await get_org_founder(db, existing_match.id)
                if not founder:
                    raise HTTPException(
                        status_code=500,
                        detail="Target organisation has no users — cannot route approval",
                    )

                jr = OrgJoinRequest(
                    requester_user_id=requester.id,
                    requester_email=requester.email,
                    requester_full_name=requester.full_name,
                    source_org_id=org.id,
                    target_org_id=existing_match.id,
                    target_org_name=existing_match.name,
                    status=STATUS_PENDING,
                )
                db.add(jr)
                await db.commit()
                await db.refresh(jr)

                # Real-time poke for the founder so the Invitations
                # page lights up immediately + best-effort email.
                try:
                    from ..services.ws_manager import ws_manager
                    await ws_manager.broadcast(existing_match.id, {
                        "type": "join_request_created",
                        "data": {
                            "id": jr.id,
                            "requesterEmail": requester.email,
                            "requesterName": requester.full_name,
                            "targetOrgName": existing_match.name,
                        },
                    })
                except Exception:
                    pass
                # Email (best-effort, fails silently if SMTP unconfigured)
                try:
                    from ..services.org_join_email import send_join_request_email
                    await send_join_request_email(
                        founder_email=founder.email,
                        founder_name=founder.full_name or founder.email,
                        requester_email=requester.email,
                        requester_name=requester.full_name or requester.email,
                        target_org_name=existing_match.name,
                    )
                except Exception as e:
                    logger.warning(f"Join request email skipped: {e}")

                logger.info(
                    f"[org-join-request] {requester.email} requested to "
                    f"join '{existing_match.name}' ({existing_match.id}); "
                    f"approver={founder.email}; request={jr.id}"
                )
                # 202 Accepted — request created, awaiting approval. We
                # return the CURRENT org untouched so the frontend
                # shows their existing org while displaying the
                # pending state.
                return {
                    "id": org.id,
                    "name": org.name,
                    "slug": org.slug,
                    "timezone": org.timezone,
                    "workingHoursStart": org.working_hours_start,
                    "workingHoursEnd": org.working_hours_end,
                    "standupTime": org.standup_time,
                    "joinRequest": {
                        "status": "pending_approval",
                        "requestId": jr.id,
                        "targetOrgId": existing_match.id,
                        "targetOrgName": existing_match.name,
                        "approverEmail": founder.email,
                        "approverName": founder.full_name,
                    },
                }

            # No collision — in-place rename. Update both name and
            # name_canonical so the unique index stays consistent.
            org.name = requested_name.strip()
            org.name_canonical = new_canonical
            name_handled = True

    for key, val in body.items():
        if key == "name" and name_handled:
            continue  # already handled above with canonical machinery
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
# Sole-user org migration helper (Hotfix 85)
# ---------------------------------------------------------------------------

async def _migrate_user_to_existing_org(
    db: AsyncSession,
    *,
    current_user_email: str,
    from_org_id: str,
    to_org_id: str,
) -> dict[str, int]:
    """Reassign every FK that references ``from_org_id`` to point at
    ``to_org_id``, then delete the orphan org row. Used by the
    Settings → org-rename flow when a sole-user org collides with an
    existing canonical-name match.

    Returns a dict ``{table_name: rows_reassigned}`` for logging.
    Raises if the migration would clobber a unique constraint (e.g.
    both orgs have the same source_tool ToolConnection); in that case
    we keep the destination's row and drop the source's.
    """
    from sqlalchemy import update, delete

    # Ordered list of tables that reference organizations.id. Each
    # entry is (model class, column attr to rewrite, optional
    # uniqueness-conflict resolution).
    from ..models.user import User as _User
    from ..models.team_member import TeamMember as _TM
    from ..models.imported_project import (
        ImportedProject as _IP,
        StakeholderProjectAssignment as _SPA,
    )
    from ..models.tool_connection import ToolConnection as _TC
    from ..models.work_item import WorkItem as _WI
    from ..models.iteration import Iteration as _IT
    from ..models.sprint_plan import SprintPlan as _SP
    from ..models.standup import StandupReport as _SR, TeamStandupDigest as _TSD
    from ..models.retrospective import Retrospective as _R
    from ..models.audit_log import AuditLogEntry as _AL
    from ..models.activity import ActivityEvent as _AE
    from ..models.invitation import Invitation as _INV
    from ..models.repository import Repository as _REPO
    from ..models.analytics import HealthSignal as _HS, BurnoutAlert as _BA

    plain_reassign = [
        ("users", _User), ("team_members", _TM),
        ("imported_projects", _IP),
        ("stakeholder_project_assignments", _SPA),
        ("work_items", _WI), ("iterations", _IT),
        ("sprint_plans", _SP),
        ("standup_reports", _SR), ("team_standup_digests", _TSD),
        ("retrospectives", _R),
        ("audit_log_entries", _AL),
        ("activity_events", _AE),
        ("invitations", _INV),
        ("repositories", _REPO),
        ("health_signals", _HS), ("burnout_alerts", _BA),
    ]

    report: dict[str, int] = {}
    for label, model in plain_reassign:
        res = await db.execute(
            update(model)
            .where(model.organization_id == from_org_id)
            .values(organization_id=to_org_id)
        )
        report[label] = res.rowcount or 0

    # ToolConnection has a unique (org_id, source_tool) constraint.
    # If destination already has a connection for this source_tool we
    # KEEP destination's (it's the active one) and drop source's.
    tc_rows = (
        await db.execute(
            select(_TC).where(_TC.organization_id == from_org_id)
        )
    ).scalars().all()
    tc_moved = 0
    tc_dropped = 0
    for tc in tc_rows:
        dest_existing = (
            await db.execute(
                select(_TC).where(
                    _TC.organization_id == to_org_id,
                    _TC.source_tool == tc.source_tool,
                )
            )
        ).scalar_one_or_none()
        if dest_existing:
            await db.delete(tc)
            tc_dropped += 1
        else:
            tc.organization_id = to_org_id
            tc_moved += 1
    report["tool_connections_moved"] = tc_moved
    report["tool_connections_dropped"] = tc_dropped

    # Finally, delete the orphan org row.
    from ..models.organization import Organization as _Org
    await db.execute(delete(_Org).where(_Org.id == from_org_id))
    report["organization_deleted"] = 1

    # Audit log entry
    audit = _AL(
        organization_id=to_org_id,
        actor_id=None,
        actor_role="product_owner",
        event_type="org.canonical_merge",
        resource_type="organization",
        resource_id=to_org_id,
        source_channel="WEB",
        success=True,
        metadata_={
            "from_org_id": from_org_id,
            "to_org_id": to_org_id,
            "merged_by_email": current_user_email,
            "rows_reassigned": report,
        },
    )
    db.add(audit)

    return report


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

    # 3) Determine active status — populated below from the GLOBAL User
    #    table (not just current org), so a member who has a Plan2Sprint
    #    account in another org also shows as Active. Hotfix 63B.
    active_emails: set[str] = set()

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

    # Hotfix 37 — global User role lookup. A member's "true" role is
    # the one on their User row regardless of which org we're listing.
    # Without this, a stakeholder viewing their org sees a member who
    # is actually a Product Owner in another org listed as "Developer"
    # because we only had their TeamMember row available locally. Pull
    # User.role for every email seen here so the displayed role is
    # accurate (e.g. ``sangini@concept2action.ai`` always shows as
    # ``product_owner`` even when viewed from a different org).
    all_emails: list[str] = (
        [u.email for u in users]
        + [tm.email for tm in team_members if tm.email]
    )
    role_priority = {
        "owner": 6, "admin": 5, "product_owner": 4,
        "engineering_manager": 3, "developer": 2, "stakeholder": 1,
    }
    global_role_by_email: dict[str, str] = {}
    if all_emails:
        global_users_q = await db.execute(
            select(User).where(User.email.in_(all_emails))
        )
        for gu in global_users_q.scalars().all():
            email_lc = (gu.email or "").lower()
            new_role = (gu.role or "").lower()
            existing = global_role_by_email.get(email_lc)
            if not existing or role_priority.get(new_role, 0) > role_priority.get(existing, 0):
                global_role_by_email[email_lc] = new_role
            # Hotfix 63B — anyone with a User row anywhere counts as
            # Active. Previously this set was built from current-org
            # Users only, which incorrectly flagged cross-org Plan2Sprint
            # users (e.g. a stakeholder who has their own org elsewhere)
            # as "Inactive" in this org's team list.
            active_emails.add(email_lc)

    def _resolve_role(email: str, fallback: str) -> str:
        """Use global User.role when known, falling back to the local
        TeamMember/User role we already had."""
        return global_role_by_email.get(email.lower(), fallback)

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

        local_role = u.role.lower() if u.role else "developer"
        members.append({
            "id": u.id,
            "teamMemberId": matching_tm.id if matching_tm else None,
            "type": "user",
            "email": u.email,
            "displayName": u.full_name,
            "avatarUrl": u.avatar_url or (matching_tm.avatar_url if matching_tm else None),
            "role": _resolve_role(u.email, local_role),
            "isActive": email_lower in active_emails,
            "projects": projects,
            "createdAt": u.created_at.isoformat() if u.created_at else None,
        })

    # TeamMembers who don't have a User account in THIS org (synced
    # from tools, or referenced from another org). Hotfix 37 — skip
    # rows whose role is ``excluded`` because those members were
    # explicitly removed from a project; surfacing them in the team
    # listing is misleading.
    for tm in team_members:
        email_lower = tm.email.lower()
        if email_lower in seen_emails:
            continue
        local_role = tm.role.lower() if tm.role else "developer"
        if local_role == "excluded":
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
            "role": _resolve_role(tm.email, local_role),
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

    # Hotfix 63A — mark synced TeamMember rows for the same email as
    # ``role='excluded'`` so the removed member doesn't zombie-reappear
    # in the team list as "Inactive". The list_members query already
    # filters out role='excluded' rows. We DON'T hard-delete the
    # TeamMember rows because work_items.assignee_id may reference them
    # (e.g. Pallavi's 34 assignments) — keeping the row preserves the
    # historical assignment data; setting the role to 'excluded' just
    # hides them from the live team listing.
    removed_email = (user.email or "").lower()
    excluded_count = 0
    if removed_email:
        upd_result = await db.execute(
            sa_update(TeamMember)
            .where(
                TeamMember.organization_id == org_id,
                sa_func.lower(TeamMember.email) == removed_email,
                TeamMember.role != "excluded",
            )
            .values(role="excluded")
        )
        excluded_count = upd_result.rowcount or 0

    await db.delete(user)
    await db.commit()
    return {"ok": True, "teamMembersExcluded": excluded_count}


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

    # Hotfix 66A — verify the caller's email actually matches the
    # invitation's recipient. Without this, anyone with the URL can
    # mark an invitation accepted under their own session, leaving the
    # actual invitee with no way to consume the invitation later. (The
    # production scenario from 2026-05-05: a PO clicked an invite from
    # her own browser tab while logged in as herself, silently flipped
    # the invitation to ``accepted``, then the real invitee fell
    # through to auto-org creation with role=product_owner.)
    #
    # Hotfix 70A — re-ordered: the email check now runs BEFORE the
    # status check so we can distinguish "already accepted by the
    # legitimate recipient" (idempotent success) from "already accepted
    # by someone else" (still a 400). Common reason for the former:
    # _resolve_user_org's Hotfix 65A consumes the invitation a few ms
    # before this body runs in the same request.
    caller_email = (current_user.get("email") or "").strip().lower()
    invite_email = (inv.email or "").strip().lower()
    if caller_email and invite_email and caller_email != invite_email:
        raise HTTPException(
            status_code=403,
            detail=(
                "This invitation was issued to a different email address. "
                "Please sign in with the email address the invitation was "
                "sent to."
            ),
        )

    now = datetime.now(timezone.utc)

    if inv.status != "pending":
        # Hotfix 70A — idempotent success when the legitimate recipient
        # re-hits accept (almost always because Hotfix 65A's race in
        # _resolve_user_org just consumed the invitation). Look up
        # their User row in the inviter's org and return their role
        # so the frontend can route them to the correct dashboard
        # exactly as if this were a clean accept.
        if inv.status == "accepted" and caller_email and caller_email == invite_email:
            existing_self = await db.execute(
                select(User).where(
                    User.email == caller_email,
                    User.organization_id == inv.organization_id,
                )
            )
            existing_user = existing_self.scalar_one_or_none()
            if existing_user:
                return {
                    "ok": True,
                    "message": "Invitation already accepted",
                    "organizationId": inv.organization_id,
                    "role": (existing_user.role or inv.role or "developer").lower(),
                }
        raise HTTPException(status_code=400, detail=f"Invitation is {inv.status}")

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
    existing_in_invited_org = existing.scalar_one_or_none()
    if existing_in_invited_org:
        inv.status = "accepted"
        inv.accepted_at = now
        await db.commit()
        return {
            "ok": True,
            "message": "Already a member of this organization",
            "organizationId": inv.organization_id,
            "role": (existing_in_invited_org.role or inv.role or "").lower(),
        }

    # Hotfix 61 — detect the "already has a workspace under another org"
    # case BEFORE we attempt the INSERT. Plan2Sprint enforces a global
    # UNIQUE(email) on users (single-org-per-user model), so blindly
    # INSERT-ing a row for someone who self-signed-up earlier explodes
    # with a 500 IntegrityError and leaves the user staring at "Invalid
    # Invitation" forever. Surface a 409 Conflict with a clear next step
    # instead so the inviter knows they need to use a different email.
    cross_org = await db.execute(
        select(User).where(User.email == user_email)
    )
    cross_org_user = cross_org.scalar_one_or_none()
    if cross_org_user:
        raise HTTPException(
            status_code=409,
            detail=(
                "This email is already registered to another Plan2Sprint "
                "workspace. Please ask your inviter to use a different "
                "email address, or contact support if you need to "
                "consolidate your accounts."
            ),
        )

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

    # Hotfix 60 — write the role into Supabase ``user_metadata`` so the
    # JWT carries it on every subsequent login. The frontend's
    # AuthProvider (lib/auth/context.tsx) reads
    # ``user.user_metadata.role`` to decide which dashboard to land on
    # via /dashboard's ROLE_DASHBOARD_ROUTES; without this sync, future
    # logins default to "product_owner" and route invited developers /
    # stakeholders to /po by mistake. Best-effort — never blocks the
    # acceptance response. Requires SUPABASE_SERVICE_ROLE_KEY in env.
    try:
        from ..config import settings as _settings
        sup_uid = current_user.get("sub")
        service_key = (_settings.supabase_service_role_key or "").strip()
        sup_url = (_settings.supabase_url or "").strip().rstrip("/")
        if sup_uid and service_key and sup_url:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=8.0) as _client:
                _r = await _client.put(
                    f"{sup_url}/auth/v1/admin/users/{sup_uid}",
                    headers={
                        "apikey": service_key,
                        "Authorization": f"Bearer {service_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "user_metadata": {
                            "role": (inv.role or "").lower(),
                            # Preserve full_name so we don't blow away
                            # whatever the user set during signup.
                            "full_name": current_user.get(
                                "full_name",
                                current_user.get("user_metadata", {}).get(
                                    "full_name", user_email
                                ),
                            ),
                        }
                    },
                )
                if _r.status_code >= 300:
                    import logging as _logging
                    _logging.warning(
                        f"[invite-accept] Supabase metadata sync failed "
                        f"({_r.status_code}): {_r.text[:200]}"
                    )
    except Exception as _e:
        import logging as _logging
        _logging.warning(f"[invite-accept] Supabase metadata sync error: {_e!r}")

    # Hotfix 59 — return role so the frontend can route the new user
    # straight to their role-specific dashboard instead of the marketing
    # landing page. Lower-case for frontend convenience.
    return {
        "ok": True,
        "message": "Invitation accepted",
        "organizationId": inv.organization_id,
        "role": (inv.role or "").lower(),
    }


# ===========================================================================
# Org join requests (Hotfix 86 — owner approval gate)
# ===========================================================================

@router.get("/current/join-requests")
async def list_pending_join_requests(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List pending join requests targeting the caller's org.

    Visible to founders (the earliest-created PO of the org). Other
    POs see an empty list — keeps approval authority centralized so a
    second PO can't approve people the founder hasn't reviewed.
    """
    from ..models.org_join_request import OrgJoinRequest, STATUS_PENDING
    from ..services.org_join_flow import get_org_founder

    org_id = current_user.get("organization_id", "demo-org")
    founder = await get_org_founder(db, org_id)
    caller_email = (current_user.get("email") or "").lower().strip()
    is_founder = founder and (founder.email or "").lower().strip() == caller_email
    if not is_founder:
        return {"requests": [], "isFounder": False}

    rows = (await db.execute(
        select(OrgJoinRequest)
        .where(
            OrgJoinRequest.target_org_id == org_id,
            OrgJoinRequest.status == STATUS_PENDING,
        )
        .order_by(OrgJoinRequest.created_at.asc())
    )).scalars().all()

    return {
        "isFounder": True,
        "requests": [
            {
                "id": r.id,
                "requesterEmail": r.requester_email,
                "requesterName": r.requester_full_name,
                "targetOrgName": r.target_org_name,
                "createdAt": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/join-requests/mine")
async def get_my_join_request(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the caller's own pending join request, if any.

    Used by the Settings page so the user can see "Pending approval
    from <Founder>" instead of a stale success toast after they
    submit a rename that triggered the approval gate.
    """
    from ..models.org_join_request import OrgJoinRequest, STATUS_PENDING
    from ..services.org_join_flow import get_org_founder

    caller_email = (current_user.get("email") or "").lower().strip()
    if not caller_email:
        return {"request": None}

    me_q = await db.execute(select(User).where(User.email == caller_email))
    me = me_q.scalar_one_or_none()
    if not me:
        return {"request": None}

    jr = (await db.execute(
        select(OrgJoinRequest)
        .where(
            OrgJoinRequest.requester_user_id == me.id,
            OrgJoinRequest.status == STATUS_PENDING,
        )
        .order_by(OrgJoinRequest.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if not jr:
        return {"request": None}

    founder = await get_org_founder(db, jr.target_org_id)
    return {
        "request": {
            "id": jr.id,
            "targetOrgId": jr.target_org_id,
            "targetOrgName": jr.target_org_name,
            "approverEmail": founder.email if founder else None,
            "approverName": founder.full_name if founder else None,
            "createdAt": jr.created_at.isoformat() if jr.created_at else None,
        }
    }


@router.post("/join-requests/{request_id}/approve")
async def approve_join_request(
    request_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Founder approves a pending join request → migration runs.

    Re-validates at approval time:
      - Caller is still the founder of the target org
      - Request is still pending
      - Requester is still the sole user of their source org

    On success, runs the same migration helper Phase 1 used to do
    auto-magically and marks the request approved + audit-logs.
    """
    import logging as _logging
    _logger = _logging.getLogger(__name__)
    from ..models.org_join_request import (
        OrgJoinRequest, STATUS_PENDING, STATUS_APPROVED,
    )
    from ..services.org_join_flow import get_org_founder

    jr = (await db.execute(
        select(OrgJoinRequest).where(OrgJoinRequest.id == request_id)
    )).scalar_one_or_none()
    if not jr:
        raise HTTPException(status_code=404, detail="Request not found")
    if jr.status != STATUS_PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Request is not pending (current status: {jr.status})",
        )

    # Authz — caller must be founder of target org
    caller_email = (current_user.get("email") or "").lower().strip()
    founder = await get_org_founder(db, jr.target_org_id)
    if not founder or (founder.email or "").lower().strip() != caller_email:
        raise HTTPException(
            status_code=403,
            detail="Only the founder of this organisation can approve join requests",
        )

    # Re-validate sole-user invariant on the source org
    source_users = (await db.execute(
        select(User).where(User.organization_id == jr.source_org_id)
    )).scalars().all()
    if len(source_users) != 1 or source_users[0].id != jr.requester_user_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Requester's organisation has new members since this "
                "request was filed. Ask them to resubmit so they can "
                "leave that org alone."
            ),
        )

    # Run the migration via the shared helper
    migrated = await _migrate_user_to_existing_org(
        db,
        current_user_email=caller_email,
        from_org_id=jr.source_org_id,
        to_org_id=jr.target_org_id,
    )

    jr.status = STATUS_APPROVED
    jr.resolved_at = datetime.now(timezone.utc)
    me_q = await db.execute(select(User).where(User.email == caller_email))
    me = me_q.scalar_one_or_none()
    if me:
        jr.resolved_by_user_id = me.id

    await db.commit()

    # Notify requester so their Settings page swaps from "pending" to "approved"
    try:
        from ..services.ws_manager import ws_manager
        # Broadcast on the TARGET org channel (where they now live)
        # AND the source org channel (where they came from) so
        # whichever the requester's WS is currently bound to picks it up.
        for org_ch in (jr.source_org_id, jr.target_org_id):
            await ws_manager.broadcast(org_ch, {
                "type": "join_request_resolved",
                "data": {
                    "id": jr.id,
                    "status": "approved",
                    "targetOrgId": jr.target_org_id,
                    "targetOrgName": jr.target_org_name,
                },
            })
    except Exception:
        pass

    _logger.info(
        f"[org-join-request] APPROVED id={jr.id} requester={jr.requester_email} "
        f"target={jr.target_org_id}; migrated: {migrated}"
    )
    return {"ok": True, "migrated": migrated}


@router.post("/join-requests/{request_id}/reject")
async def reject_join_request(
    request_id: str,
    body: dict | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Founder rejects a pending join request → no migration."""
    from ..models.org_join_request import (
        OrgJoinRequest, STATUS_PENDING, STATUS_REJECTED,
    )
    from ..services.org_join_flow import get_org_founder

    jr = (await db.execute(
        select(OrgJoinRequest).where(OrgJoinRequest.id == request_id)
    )).scalar_one_or_none()
    if not jr:
        raise HTTPException(status_code=404, detail="Request not found")
    if jr.status != STATUS_PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Request is not pending (current status: {jr.status})",
        )

    caller_email = (current_user.get("email") or "").lower().strip()
    founder = await get_org_founder(db, jr.target_org_id)
    if not founder or (founder.email or "").lower().strip() != caller_email:
        raise HTTPException(
            status_code=403,
            detail="Only the founder of this organisation can reject join requests",
        )

    jr.status = STATUS_REJECTED
    jr.resolved_at = datetime.now(timezone.utc)
    jr.resolution_note = (body or {}).get("note") if body else None
    me_q = await db.execute(select(User).where(User.email == caller_email))
    me = me_q.scalar_one_or_none()
    if me:
        jr.resolved_by_user_id = me.id
    await db.commit()

    try:
        from ..services.ws_manager import ws_manager
        for org_ch in (jr.source_org_id, jr.target_org_id):
            await ws_manager.broadcast(org_ch, {
                "type": "join_request_resolved",
                "data": {
                    "id": jr.id,
                    "status": "rejected",
                    "targetOrgName": jr.target_org_name,
                },
            })
    except Exception:
        pass

    return {"ok": True}


@router.post("/join-requests/{request_id}/cancel")
async def cancel_join_request(
    request_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Requester withdraws their own pending join request."""
    from ..models.org_join_request import (
        OrgJoinRequest, STATUS_PENDING, STATUS_CANCELLED,
    )

    jr = (await db.execute(
        select(OrgJoinRequest).where(OrgJoinRequest.id == request_id)
    )).scalar_one_or_none()
    if not jr:
        raise HTTPException(status_code=404, detail="Request not found")
    if jr.status != STATUS_PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Request is not pending (current status: {jr.status})",
        )

    caller_email = (current_user.get("email") or "").lower().strip()
    if (jr.requester_email or "").lower().strip() != caller_email:
        raise HTTPException(
            status_code=403,
            detail="You can only cancel your own join request",
        )

    jr.status = STATUS_CANCELLED
    jr.resolved_at = datetime.now(timezone.utc)
    await db.commit()

    return {"ok": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


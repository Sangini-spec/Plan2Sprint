"""
Imported Projects API — persist project references in the database.

GET  /              - List all imported projects for the org
POST /              - Save/upsert an imported project
POST /:id/cache     - Update cached data (work items, team members, iterations)
DELETE /:id         - Remove an imported project

User Project Preference (persists selected project across sessions):
GET  /preferences/selected   - Get user's last-selected project
POST /preferences/selected   - Save user's selected project
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..auth.supabase import get_current_user, require_po
from ..database import get_db
from ..models.imported_project import ImportedProject, UserProjectPreference, StakeholderProjectAssignment
from ..models.project_phase import ProjectPhase
from ..models.user import User
from ..models.team_member import TeamMember
from ..models.base import generate_cuid

router = APIRouter()


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------

@router.get("")
@router.get("/")
async def list_imported_projects(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List imported projects for the user's org. Developers see only their assigned projects."""
    org_id = current_user.get("organization_id", "demo-org")
    user_role = current_user.get("role", "").lower()
    user_email = current_user.get("email", "")

    if user_role == "developer" and user_email:
        # Developers see projects from BOTH:
        #   1. team_member rows where their email matches (auto-populated
        #      by ADO/Jira sync — historical behaviour), AND
        #   2. Hotfix 69C — explicit assignments by the PO via the
        #      Settings → Team → Assign UI. That UI inserts into
        #      ``stakeholder_project_assignments`` regardless of the
        #      target user's role, but until now the developer branch
        #      only read from team_members, so PO-clicked assignments
        #      were silently lost. Same lookup pattern as the
        #      stakeholder branch below.
        from ..models.imported_project import StakeholderProjectAssignment
        from ..models.user import User as _User
        member_result = await db.execute(
            select(TeamMember.imported_project_id).where(
                TeamMember.organization_id == org_id,
                TeamMember.email.ilike(user_email),
                TeamMember.role != "excluded",
            )
        )
        project_ids: list[str] = [r[0] for r in member_result.all() if r[0]]

        # Add explicit assignments — same identity-resolution as the
        # stakeholder branch (User.id and TeamMember.id can both
        # appear in assignment.user_id).
        ids: list[str] = []
        u_rows = (await db.execute(
            select(_User.id).where(_User.email.ilike(user_email))
        )).scalars().all()
        ids.extend(u_rows)
        tm_rows = (await db.execute(
            select(TeamMember.id).where(TeamMember.email.ilike(user_email))
        )).scalars().all()
        ids.extend(tm_rows)
        if ids:
            assigned_q = await db.execute(
                select(StakeholderProjectAssignment.imported_project_id).where(
                    StakeholderProjectAssignment.user_id.in_(ids),
                )
            )
            for row in assigned_q.all():
                if row[0] and row[0] not in project_ids:
                    project_ids.append(row[0])

        # Hotfix 90c — work-item-assignee path. Projects where any
        # work item is assigned to a TM whose email matches the
        # caller. Mirrors what the Team Management projects-badge
        # uses, so a dev with ADO-imported work shows up consistently
        # in both surfaces. This is the common case where the TM row
        # was synced from ADO with imported_project_id=NULL but
        # WorkItem.assignee_id carries the link.
        if tm_rows:
            from ..models.work_item import WorkItem as _WI
            wi_q = await db.execute(
                select(_WI.imported_project_id).where(
                    _WI.organization_id == org_id,
                    _WI.assignee_id.in_(tm_rows),
                ).distinct()
            )
            for row in wi_q.all():
                if row[0] and row[0] not in project_ids:
                    project_ids.append(row[0])

        if project_ids:
            result = await db.execute(
                select(ImportedProject).where(
                    ImportedProject.organization_id == org_id,
                    ImportedProject.id.in_(project_ids),
                )
            )
        else:
            # No team_member rows AND no explicit PO assignments — show
            # empty welcome state, not the entire org's projects.
            result = await db.execute(
                select(ImportedProject).where(
                    ImportedProject.organization_id == org_id,
                    ImportedProject.id == "__none__",  # Returns empty
                )
            )
    elif user_role == "stakeholder" and user_email:
        # Hotfix 56 (MED-4) — stakeholders see ONLY projects they have an
        # explicit StakeholderProjectAssignment for. Previously the
        # endpoint dropped them into the "see all org projects" branch,
        # which leaked unassigned project metadata to read-only viewers.
        from ..models.imported_project import StakeholderProjectAssignment
        from ..models.user import User as _User
        # Resolve every user-side identity for this email (User.id and
        # any TeamMember.id matching the email — both can appear in the
        # assignment.user_id column depending on assignment path).
        ids: list[str] = []
        u_rows = (await db.execute(
            select(_User.id).where(_User.email.ilike(user_email))
        )).scalars().all()
        ids.extend(u_rows)
        tm_rows = (await db.execute(
            select(TeamMember.id).where(TeamMember.email.ilike(user_email))
        )).scalars().all()
        ids.extend(tm_rows)
        if ids:
            assigned_q = await db.execute(
                select(StakeholderProjectAssignment.imported_project_id).where(
                    StakeholderProjectAssignment.user_id.in_(ids),
                )
            )
            assigned_ids = [r[0] for r in assigned_q.all() if r[0]]
        else:
            assigned_ids = []
        if assigned_ids:
            # IMPORTANT: org_id filter is mandatory. Without it a
            # stakeholder whose StakeholderProjectAssignment row points at
            # a project_id from a different org (legacy data, cross-org
            # invitation, manual DB tweak) would see that project. We
            # observed this surface as a "stale data" symptom: a duplicate
            # Plan2Sprint row in another org with only Iteration 1 was
            # being picked up here, so the stakeholder's dashboard was
            # locked to that stale row while the PO (org-scoped) saw the
            # live row with Iteration 3. Same projectId leak shape would
            # also let an attacker who knew an internalId enumerate
            # cross-org projects via assignment manipulation.
            result = await db.execute(
                select(ImportedProject).where(
                    ImportedProject.organization_id == org_id,
                    ImportedProject.id.in_(assigned_ids),
                )
            )
        else:
            result = await db.execute(
                select(ImportedProject).where(ImportedProject.id == "__none__")
            )
    else:
        # PO, Admin, Owner see all org projects
        result = await db.execute(
            select(ImportedProject).where(ImportedProject.organization_id == org_id)
        )
    projects = result.scalars().all()
    return {
        "projects": [
            {
                "internalId": p.id,
                "id": p.external_id,
                "name": p.name,
                "key": p.key,
                "description": p.description,
                "source": p.source_tool,
                "boardId": p.board_id,
                "isActive": p.is_active,
                "cachedData": p.cached_data,
                "syncedAt": p.synced_at.isoformat() if p.synced_at else None,
                "createdAt": p.created_at.isoformat() if p.created_at else None,
                "updatedAt": p.updated_at.isoformat() if p.updated_at else None,
            }
            for p in projects
        ]
    }


@router.post("")
@router.post("/")
async def save_imported_project(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save or upsert an imported project."""
    # Hotfix 81 — reverted the require_po gate added in Hotfix 67A.
    # With devs now OAuthing their own Jira/ADO accounts, completing
    # the explicit "Select Projects → Import Projects" flow in the
    # Connect Tools modal calls this endpoint, so it must work for
    # non-PO too. Whoever last OAuthed owns the stored tokens; the
    # imported project goes into the org regardless of caller role.
    org_id = current_user.get("organization_id", "demo-org")
    external_id = body.get("id") or body.get("external_id")
    source_tool = body.get("source") or body.get("sourceTool")
    name = body.get("name")

    if not external_id or not source_tool or not name:
        raise HTTPException(status_code=400, detail="id, source, and name are required")

    # Check if already exists
    result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.organization_id == org_id,
            ImportedProject.external_id == str(external_id),
            ImportedProject.source_tool == source_tool,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.name = name
        existing.key = body.get("key")
        existing.description = body.get("description")
        if body.get("boardId") is not None:
            existing.board_id = body["boardId"]
        if body.get("cachedData"):
            existing.cached_data = body["cachedData"]
        await db.commit()
        return {"ok": True, "action": "updated", "internalId": existing.id}

    project = ImportedProject(
        id=generate_cuid(),
        organization_id=org_id,
        external_id=str(external_id),
        source_tool=source_tool,
        name=name,
        key=body.get("key"),
        description=body.get("description"),
        board_id=body.get("boardId"),
        cached_data=body.get("cachedData"),
    )
    db.add(project)
    await db.commit()
    return {"ok": True, "action": "created", "internalId": project.id}


# ---------------------------------------------------------------------------
# Project access probe (Hotfix 91)
# ---------------------------------------------------------------------------
#
# Frontend hits this to determine whether the *current* caller has access to
# a given project, so the dashboard can render an "ask the PO to assign you"
# banner instead of empty 0s when the answer is no. Returns 200/{hasAccess}
# when allowed; 403/{hasAccess: false, reason} when denied; 404 when the
# project doesn't exist in the caller's org (don't leak cross-org).
#
# Lightweight wrapper around ``services.project_access.assert_project_access``
# so the matrix here can never drift from the matrix that enforces data
# access on every dashboard endpoint.

@router.get("/{project_id}/access")
async def check_project_access(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..services.project_access import assert_project_access
    try:
        proj = await assert_project_access(db, project_id, current_user)
        return {
            "hasAccess": True,
            "projectId": proj.id,
            "projectName": proj.name,
        }
    except HTTPException as e:
        # Re-raise 404 (not found / cross-org) as-is so the frontend
        # can tell "project doesn't exist" from "you can't access it".
        if e.status_code == 404:
            raise
        # 403 → return JSON 200 with hasAccess=false so the banner
        # component doesn't have to special-case error paths. Status
        # code stays 200 only because the access check itself
        # succeeded — it's the *answer* that's no.
        #
        # Hotfix 91 — also return ``projectName`` on the denial path so
        # the banner can always identify the project by name, even if
        # the frontend's selected-project context is stale or the user
        # navigated via URL to a project they don't have in localStorage.
        org_id = current_user.get("organization_id", "demo-org")
        proj_name = None
        proj_row = (await db.execute(
            select(ImportedProject.name).where(
                ImportedProject.id == project_id,
                ImportedProject.organization_id == org_id,
            )
        )).scalar_one_or_none()
        if proj_row:
            proj_name = proj_row
        return {
            "hasAccess": False,
            "projectId": project_id,
            "projectName": proj_name,
            "reason": e.detail if isinstance(e.detail, str) else "denied",
        }


@router.post("/{project_id}/cache")
async def update_project_cache(
    project_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update cached data for an imported project."""
    org_id = current_user.get("organization_id", "demo-org")
    result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.organization_id == org_id,
            ImportedProject.external_id == project_id,
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project.cached_data = body.get("cachedData", {})
    await db.commit()
    return {"ok": True}


@router.delete("/{project_id}")
async def delete_imported_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an imported project and all dependent records."""
    require_po(current_user)  # Hotfix 55 (HIGH-7) — was reachable by any developer
    from sqlalchemy import text as sa_text

    org_id = current_user.get("organization_id", "demo-org")

    # Try by external_id first, then by internal id
    result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.organization_id == org_id,
            ImportedProject.external_id == project_id,
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        result = await db.execute(
            select(ImportedProject).where(
                ImportedProject.organization_id == org_id,
                ImportedProject.id == project_id,
            )
        )
        project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pid = project.id
    # Cascade delete dependent records
    await db.execute(sa_text(f"DELETE FROM plan_assignments WHERE sprint_plan_id IN (SELECT id FROM sprint_plans WHERE project_id = :pid)"), {"pid": pid})
    await db.execute(sa_text("DELETE FROM sprint_plans WHERE project_id = :pid"), {"pid": pid})
    await db.execute(sa_text("DELETE FROM sprint_constraints WHERE project_id = :pid"), {"pid": pid})
    await db.execute(sa_text("DELETE FROM project_phases WHERE project_id = :pid"), {"pid": pid})
    await db.execute(sa_text("DELETE FROM user_project_preferences WHERE selected_project_id = :pid"), {"pid": pid})
    await db.execute(sa_text("DELETE FROM stakeholder_project_assignments WHERE imported_project_id = :pid"), {"pid": pid})
    await db.execute(sa_text("DELETE FROM work_items WHERE imported_project_id = :pid"), {"pid": pid})
    await db.execute(sa_text("DELETE FROM iterations WHERE imported_project_id = :pid"), {"pid": pid})

    await db.delete(project)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# User Project Preferences (selected project persists across sessions)
# ---------------------------------------------------------------------------

@router.get("/preferences/selected")
async def get_selected_project(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's last-selected project."""
    user_id = current_user.get("sub", "demo-user-1")
    result = await db.execute(
        select(UserProjectPreference).where(UserProjectPreference.user_id == user_id)
    )
    pref = result.scalar_one_or_none()

    if not pref or not pref.selected_project_id:
        return {"selectedProject": None}

    # Fetch the actual project details — scoped to org for security
    org_id = current_user.get("organization_id", "demo-org")
    proj_result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == pref.selected_project_id,
            ImportedProject.organization_id == org_id,
        )
    )
    project = proj_result.scalar_one_or_none()
    if not project:
        return {"selectedProject": None}

    return {
        "selectedProject": {
            "internalId": project.id,
            "id": project.external_id,
            "name": project.name,
            "key": project.key,
            "description": project.description,
            "source": project.source_tool,
            "boardId": project.board_id,
            "isActive": project.is_active,
        }
    }


@router.post("/preferences/selected")
async def save_selected_project(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save the user's selected project. Pass projectId=null for 'All Projects'."""
    user_id = current_user.get("sub", "demo-user-1")
    org_id = current_user.get("organization_id", "demo-org")
    project_id = body.get("projectId")  # internal DB id, or null for "All Projects"

    # Hotfix 29 — coerce empty string / whitespace to None. The frontend
    # sometimes serialises "no selection" as an empty string instead of null,
    # which used to land in the DB and immediately fail FK validation against
    # imported_projects ("Key (selected_project_id)=() is not present").
    if isinstance(project_id, str) and not project_id.strip():
        project_id = None

    # Validate the project exists if provided
    if project_id:
        proj_result = await db.execute(
            select(ImportedProject).where(
                ImportedProject.id == project_id,
                ImportedProject.organization_id == org_id,
            )
        )
        if not proj_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Project not found")

    # Upsert preference
    result = await db.execute(
        select(UserProjectPreference).where(UserProjectPreference.user_id == user_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.selected_project_id = project_id
        existing.organization_id = org_id
    else:
        pref = UserProjectPreference(
            id=generate_cuid(),
            user_id=user_id,
            organization_id=org_id,
            selected_project_id=project_id,
        )
        db.add(pref)

    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Stakeholder Project Assignments (PO/admin assigns projects to stakeholders)
# ---------------------------------------------------------------------------

@router.get("/stakeholder-assignments")
async def list_stakeholder_assignments(
    userId: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List stakeholder project assignments. If userId is given, filter by that user."""
    org_id = current_user.get("organization_id", "demo-org")
    query = (
        select(StakeholderProjectAssignment)
        .where(StakeholderProjectAssignment.organization_id == org_id)
    )
    if userId:
        query = query.where(StakeholderProjectAssignment.user_id == userId)

    result = await db.execute(query)
    assignments = result.scalars().all()

    project_ids = [a.imported_project_id for a in assignments]
    projects_map = {}
    if project_ids:
        proj_result = await db.execute(
            select(ImportedProject).where(
                ImportedProject.id.in_(project_ids),
                ImportedProject.organization_id == org_id,
            )
        )
        for p in proj_result.scalars().all():
            projects_map[p.id] = p

    return {
        "assignments": [
            {
                "id": a.id,
                "userId": a.user_id,
                "projectId": a.imported_project_id,
                "project": {
                    "internalId": projects_map[a.imported_project_id].id,
                    "id": projects_map[a.imported_project_id].external_id,
                    "name": projects_map[a.imported_project_id].name,
                    "key": projects_map[a.imported_project_id].key,
                    "source": projects_map[a.imported_project_id].source_tool,
                } if a.imported_project_id in projects_map else None,
                "assignedBy": a.assigned_by,
                "createdAt": a.created_at.isoformat() if a.created_at else None,
            }
            for a in assignments
        ]
    }


@router.get("/stakeholder-assignments/my-projects")
async def get_my_stakeholder_projects(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get projects assigned to the current stakeholder user.

    Hotfix 35 — match by EMAIL globally, not by ``(user_id, org_id)``.

    The bug we hit: PO assigned a project, the assignment was stored
    with ``user_id = TeamMember.id`` (because the PO's Team page sent
    that id when the target had no User account in the PO's org). When
    the stakeholder logged in, their JWT was for a different org
    (e.g. their personal email's org), so the original ``WHERE user_id IN
    (User.id, TeamMember.id) AND org_id = JWT.org_id`` query couldn't
    match — both the user_id format AND the org_id were different.

    Fix: enumerate every User and TeamMember row matching the
    stakeholder's email (in ANY org), then look up assignments whose
    ``user_id`` is any of those ids — without filtering by the JWT's
    ``org_id``. The assignment record itself is the authorisation
    grant; if a PO explicitly assigned this email to that project, the
    stakeholder is allowed to view it. We still scope returned projects
    to the assignment's organization (each project belongs to whichever
    org the assigning PO was in), so there is no cross-org leak — only
    projects the stakeholder was explicitly granted are returned.

    Hotfix 51 (CRIT-1) — removed the ``email`` query parameter. The
    previous version accepted ``?email=victim@target.com`` from any
    authenticated caller and returned every project assigned to that
    email globally, leaking cross-tenant project metadata to anyone
    with a session. Email is now strictly derived from the JWT.
    """
    user_email = (current_user.get("email") or "").strip()
    if not user_email:
        return {"projects": []}

    # Find every user_id that could refer to this email — both User
    # accounts and TeamMember rows, in ANY organization. The assignment
    # could have been stored under any of these.
    from ..models.team_member import TeamMember

    user_ids: list[str] = []

    user_result = await db.execute(
        select(User).where(User.email.ilike(user_email))
    )
    user_ids.extend(u.id for u in user_result.scalars().all())

    tm_result = await db.execute(
        select(TeamMember).where(TeamMember.email.ilike(user_email))
    )
    user_ids.extend(tm.id for tm in tm_result.scalars().all())

    if not user_ids:
        return {"projects": []}

    # Assignment lookup — no org filter. The assignment row is the
    # grant; if it exists, the stakeholder is authorised regardless of
    # which org their JWT carries.
    result = await db.execute(
        select(StakeholderProjectAssignment)
        .where(StakeholderProjectAssignment.user_id.in_(user_ids))
    )
    assignments = result.scalars().all()

    project_ids = [a.imported_project_id for a in assignments]
    if not project_ids:
        return {"projects": []}

    proj_result = await db.execute(
        select(ImportedProject).where(ImportedProject.id.in_(project_ids))
    )
    projects = proj_result.scalars().all()

    return {
        "projects": [
            {
                "internalId": p.id,
                "id": p.external_id,
                "name": p.name,
                "key": p.key,
                "description": p.description,
                "source": p.source_tool,
                "boardId": p.board_id,
                "isActive": p.is_active,
            }
            for p in projects
        ]
    }


@router.post("/stakeholder-assignments")
async def assign_project_to_stakeholder(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign a project to a stakeholder user. Requires PO/admin role."""
    org_id = current_user.get("organization_id", "demo-org")
    assigner_email = current_user.get("email", "")

    user_id = body.get("userId")
    project_id = body.get("projectId")

    if not user_id or not project_id:
        raise HTTPException(status_code=400, detail="userId and projectId are required")

    existing = await db.execute(
        select(StakeholderProjectAssignment).where(
            StakeholderProjectAssignment.user_id == user_id,
            StakeholderProjectAssignment.imported_project_id == project_id,
        )
    )
    if existing.scalar_one_or_none():
        return {"ok": True, "action": "already_assigned"}

    assigner_result = await db.execute(
        select(User).where(User.email == assigner_email)
    )
    assigner = assigner_result.scalar_one_or_none()

    assignment = StakeholderProjectAssignment(
        id=generate_cuid(),
        user_id=user_id,
        imported_project_id=project_id,
        organization_id=org_id,
        assigned_by=assigner.id if assigner else None,
    )
    db.add(assignment)
    await db.commit()
    return {"ok": True, "action": "assigned", "id": assignment.id}


@router.delete("/stakeholder-assignments/{assignment_id}")
async def remove_stakeholder_assignment(
    assignment_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a project assignment from a stakeholder."""
    org_id = current_user.get("organization_id", "demo-org")
    result = await db.execute(
        select(StakeholderProjectAssignment).where(
            StakeholderProjectAssignment.id == assignment_id,
            StakeholderProjectAssignment.organization_id == org_id,
        )
    )
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    await db.delete(assignment)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Target Launch Date — hover-edit on PO hero banner
# ---------------------------------------------------------------------------

class TargetLaunchBody(BaseModel):
    """Request body for PATCH /api/projects/{id}/target-launch.

    Accepts either an ISO 8601 datetime string or a plain YYYY-MM-DD date. A
    null value resets the field and flips source back to AUTO so the next
    plan-approval cycle re-derives it.
    """
    targetLaunchDate: Optional[str] = None


@router.patch("/{project_id}/target-launch")
async def patch_target_launch(
    project_id: str,
    body: TargetLaunchBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the project's enforceable launch date + rescale the future
    portion of the phase timeline proportionally to match.

    Sprint 6 persists the value + flips source to MANUAL. The proportional
    rescale of ``project_phases.planned_start``/``planned_end`` lands in
    Sprint 9 (timeline rescale math). Today Sprint 7's frontend will refetch
    ``/dashboard/project-plan`` after this PATCH and the dates will update on
    the next ``compute_timeline`` call for AI/Rebalanced modes — Raw mode
    doesn't use the target as a constraint so the timeline is unaffected.
    """
    org_id = current_user.get("organization_id", "demo-org")

    # Lookup by internal id (project_id is a cuid in this endpoint)
    result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.organization_id == org_id,
            ImportedProject.id == project_id,
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    raw = body.targetLaunchDate

    # null => reset to AUTO (allow future plan approval to repopulate)
    if raw is None:
        project.target_launch_date = None
        project.target_launch_source = None
        await db.commit()
        return {
            "ok": True,
            "targetLaunchDate": None,
            "targetLaunchSource": None,
        }

    # Parse ISO datetime or YYYY-MM-DD.
    #
    # When the PO picks a plain date like "2026-04-30" we anchor it at NOON
    # UTC, not end-of-day. At end-of-day UTC the same instant is already the
    # next calendar day everywhere east of the prime meridian (the bug the
    # PO reported: they picked Apr 30, the hero rendered May 1). Noon UTC
    # lands on the same calendar day in every timezone from UTC-11 through
    # UTC+11, which covers every timezone we realistically care about.
    try:
        if "T" in raw:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(raw, "%Y-%m-%d").replace(
                hour=12, minute=0, second=0, tzinfo=timezone.utc
            )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Invalid targetLaunchDate — expected ISO 8601 or YYYY-MM-DD: {e}")

    # Basic sanity: must be in the future. Same-day is allowed (launch today).
    now = datetime.now(timezone.utc)
    if dt.date() < now.date():
        raise HTTPException(400, "targetLaunchDate must be today or later")

    project.target_launch_date = dt
    project.target_launch_source = "MANUAL"
    await db.commit()

    # Sprint 9 — proportional rescale. Done phases stay immutable; the
    # remaining (current + future) window gets stretched / compressed to fit
    # (now → new target). Sprint plan itself is NOT modified — per the PO's
    # product decision this is a pure timeline override.
    rescale_info = await _rescale_future_phases(db, project, dt)

    return {
        "ok": True,
        "targetLaunchDate": dt.isoformat(),
        "targetLaunchSource": "MANUAL",
        "rescale": rescale_info,
    }


async def _rescale_future_phases(
    db: AsyncSession,
    project: ImportedProject,
    new_target: datetime,
) -> dict:
    """Stretch/compress all not-yet-done phases to end on ``new_target``.

    Rules:
      - Phases with ``planned_end <= now`` are considered "done" → untouched.
      - All remaining phases collectively occupy the window [now, new_target].
      - Each remaining phase keeps its proportional share of the original
        summed duration (or equal share as fallback if originals are missing).
      - If the new window is <= 0 (target in the past / today — already
        rejected upstream but defensive), we skip silently.

    Returns a small summary dict for the API response so the frontend can
    toast what moved.
    """
    now = datetime.now(timezone.utc)
    new_window = (new_target - now).total_seconds()
    if new_window <= 0:
        return {"rescaled": 0, "window_seconds": 0}

    q = await db.execute(
        select(ProjectPhase)
        .where(ProjectPhase.project_id == project.id)
        .order_by(ProjectPhase.sort_order)
    )
    phases = list(q.scalars().all())

    # Partition: done vs future. A phase is "done" if it has a planned_end in
    # the past. Phases with null dates are treated as future (they haven't
    # started yet). The Ready phase is always future — it's the handoff.
    future = [
        p for p in phases
        if p.planned_end is None or p.planned_end > now
    ]
    if not future:
        return {"rescaled": 0, "window_seconds": int(new_window)}

    # Compute each future phase's original duration so we can redistribute.
    durations: list[float] = []
    for p in future:
        if p.planned_start and p.planned_end and p.planned_end > p.planned_start:
            durations.append((p.planned_end - p.planned_start).total_seconds())
        else:
            # No usable original duration — fall back to 0, we'll
            # equal-share at the end.
            durations.append(0.0)
    total_original = sum(durations)

    # Equal-share fallback when nothing has a sensible original duration.
    if total_original <= 0:
        equal = new_window / len(future)
        cursor = now
        for p in future:
            p.planned_start = cursor
            cursor = cursor + timedelta(seconds=equal)
            p.planned_end = cursor
            p.updated_at = now
        await db.commit()
        return {
            "rescaled": len(future),
            "window_seconds": int(new_window),
            "strategy": "equal_share",
        }

    # Proportional redistribution.
    cursor = now
    for p, original in zip(future, durations):
        frac = (original / total_original) if total_original > 0 else (1.0 / len(future))
        seg = new_window * frac
        p.planned_start = cursor
        cursor = cursor + timedelta(seconds=seg)
        p.planned_end = cursor
        p.updated_at = now

    # Pin the last future phase's end to the target so floating-point drift
    # doesn't leave us a millisecond early / late.
    future[-1].planned_end = new_target

    await db.commit()
    return {
        "rescaled": len(future),
        "window_seconds": int(new_window),
        "strategy": "proportional",
    }

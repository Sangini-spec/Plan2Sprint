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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models.imported_project import ImportedProject, UserProjectPreference, StakeholderProjectAssignment
from ..models.user import User
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
    """List all imported projects for the user's org."""
    org_id = current_user.get("organization_id", "demo-org")
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


@router.post("/")
async def save_imported_project(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save or upsert an imported project."""
    org_id = current_user.get("organization_id", "demo-org")
    external_id = body.get("id") or body.get("external_id")
    source_tool = body.get("source")
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

    # Fetch the actual project details
    proj_result = await db.execute(
        select(ImportedProject).where(ImportedProject.id == pref.selected_project_id)
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
            select(ImportedProject).where(ImportedProject.id.in_(project_ids))
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
    email: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get projects assigned to the current stakeholder user."""
    org_id = current_user.get("organization_id", "demo-org")
    # Use explicit email param if provided, otherwise fall back to JWT email
    user_email = email or current_user.get("email", "")

    # Find the user's ID — could be in User table or TeamMember table
    user_ids: list[str] = []

    user_result = await db.execute(
        select(User).where(User.email == user_email, User.organization_id == org_id)
    )
    user = user_result.scalar_one_or_none()
    if user:
        user_ids.append(user.id)

    # Also check TeamMember table (synced from ADO/Jira)
    from ..models.team_member import TeamMember
    tm_result = await db.execute(
        select(TeamMember).where(TeamMember.email == user_email, TeamMember.organization_id == org_id)
    )
    tm = tm_result.scalar_one_or_none()
    if tm:
        user_ids.append(tm.id)

    if not user_ids:
        return {"projects": []}

    result = await db.execute(
        select(StakeholderProjectAssignment)
        .where(
            StakeholderProjectAssignment.user_id.in_(user_ids),
            StakeholderProjectAssignment.organization_id == org_id,
        )
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

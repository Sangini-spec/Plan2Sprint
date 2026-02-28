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
from ..models.imported_project import ImportedProject, UserProjectPreference
from ..models.base import generate_cuid

router = APIRouter()


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------

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
    """Remove an imported project."""
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

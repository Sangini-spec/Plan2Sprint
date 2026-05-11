"""Project-level authorization guard (Hotfix 90).

Plan2Sprint already filters the project LIST per role (see
``routers/projects.list_imported_projects``):

  - PO / admin / owner       -> all org projects
  - developer                -> projects where their email matches a
                                non-excluded TeamMember row, OR an
                                explicit StakeholderProjectAssignment
  - stakeholder              -> only StakeholderProjectAssignment matches

But the per-project DATA endpoints (``/api/dashboard/feature-progress``,
``/project-plan``, ``/standups``, etc.) only filtered by ``org_id``.
Anyone in the org who knew an ``internalId`` could fetch project data
they weren't actually a member of — bypassing the project-list filter
entirely.

This helper is the single source of truth for "can this caller see
this project?" Apply it at the top of every project-scoped endpoint.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.imported_project import (
    ImportedProject,
    StakeholderProjectAssignment,
)
from ..models.team_member import TeamMember
from ..models.user import User
from ..models.work_item import WorkItem


_PRIVILEGED_ROLES = {"product_owner", "owner", "admin"}


async def assert_project_access(
    db: AsyncSession,
    project_id: str,
    current_user: dict,
) -> ImportedProject:
    """Raise 404 / 403 unless the caller is allowed to see ``project_id``.

    Returns the ``ImportedProject`` row on success so the caller doesn't
    have to re-fetch it.

    Authorization matrix (mirrors ``/api/projects`` role filtering):

      * PO / admin / owner: project must be in caller's org. Otherwise 404.
      * Developer / stakeholder / engineering_manager / anything else:
        project must be in caller's org AND the caller must have a
        TeamMember row matching their email (non-excluded) OR an
        explicit ``StakeholderProjectAssignment`` row pointing at it.

    Returns 404 (not 403) for cross-org access so we don't leak that
    the project exists in a different tenant.
    """
    org_id = current_user.get("organization_id", "demo-org")
    user_email = (current_user.get("email") or "").lower().strip()
    user_role = (current_user.get("role") or "").lower()

    # 1. Project must exist in caller's org.
    proj = (
        await db.execute(
            select(ImportedProject).where(
                ImportedProject.id == project_id,
                ImportedProject.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Privileged roles get all org projects.
    if user_role in _PRIVILEGED_ROLES:
        return proj

    # 3. Non-privileged: must have ONE of:
    #    (a) TeamMember row directly linked to this project (email match
    #        on a row where ``imported_project_id == project_id``)
    #    (b) StakeholderProjectAssignment for this project
    #    (c) Any work item in this project assigned to a TeamMember of
    #        theirs (matches the Team Management page's logic — that's
    #        what populates the "Projects" badges next to a member). This
    #        is the common ADO-imported-member case: their TeamMember
    #        row was created with ``imported_project_id=NULL`` but
    #        WorkItems in the project carry ``assignee_id == tm.id``,
    #        which is the strongest possible signal that they're on
    #        the team.
    if not user_email:
        raise HTTPException(status_code=403, detail="Forbidden")

    tm_match = (
        await db.execute(
            select(TeamMember.id).where(
                TeamMember.organization_id == org_id,
                TeamMember.imported_project_id == project_id,
                TeamMember.email.ilike(user_email),
                TeamMember.role != "excluded",
            ).limit(1)
        )
    ).scalar_one_or_none()
    if tm_match:
        return proj

    # Resolve every user-side identity for this email — User.id and any
    # TeamMember.id matching the email can both appear in
    # StakeholderProjectAssignment.user_id depending on assignment path.
    user_ids: list[str] = []
    u_rows = (
        await db.execute(select(User.id).where(User.email.ilike(user_email)))
    ).scalars().all()
    user_ids.extend(u_rows)
    tm_ids = (
        await db.execute(
            select(TeamMember.id).where(TeamMember.email.ilike(user_email))
        )
    ).scalars().all()
    user_ids.extend(tm_ids)

    if user_ids:
        spa_match = (
            await db.execute(
                select(StakeholderProjectAssignment.id).where(
                    StakeholderProjectAssignment.imported_project_id == project_id,
                    StakeholderProjectAssignment.organization_id == org_id,
                    StakeholderProjectAssignment.user_id.in_(user_ids),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if spa_match:
            return proj

    # (c) Work-item assignee check. ``WorkItem.assignee_id`` is a
    # TeamMember.id. If ANY work item in this project is assigned to a
    # TM whose email matches the caller, they have real work here →
    # grant access.
    if tm_ids:
        wi_match = (
            await db.execute(
                select(WorkItem.id).where(
                    WorkItem.organization_id == org_id,
                    WorkItem.imported_project_id == project_id,
                    WorkItem.assignee_id.in_(tm_ids),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if wi_match:
            return proj

    raise HTTPException(
        status_code=403,
        detail="You do not have access to this project",
    )

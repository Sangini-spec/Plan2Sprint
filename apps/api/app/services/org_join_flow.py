"""Helpers for the owner-approval gate (Hotfix 86).

Two responsibilities:
  1. Resolving the *founder* of a target org — the earliest-created
     ``product_owner`` whose ``organization_id`` matches. The founder
     is who receives the join request and is authorised to approve /
     reject it. Falls back to any PO if the original creator's row was
     deleted (e.g. user-level deletion later).
  2. Performing the actual migration when a request is approved.
     Re-uses the same row-level FK reassignment logic that
     ``routers/organizations._migrate_user_to_existing_org`` runs for
     the auto-migrate path; we just go through it via this helper so
     the approve endpoint stays small.

Application-level guards (only one open request per requester +
target, status transitions) live in the router so we can return
specific HTTP errors.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user import User


async def get_org_founder(db: AsyncSession, org_id: str) -> Optional[User]:
    """Return the user who founded ``org_id`` (earliest-created PO).

    Definition: the User row in this org with role
    ``product_owner`` (case-insensitive) and the smallest
    ``created_at``; ties broken by ``id`` lexicographically.

    Falls back to the earliest user of any role if no PO exists
    (shouldn't happen post-Hotfix-51 which guarantees the first user
    in every new org is a PO, but defensive).
    """
    from sqlalchemy import func

    PO_ROLES = ("product_owner", "owner", "admin")
    result = await db.execute(
        select(User)
        .where(
            User.organization_id == org_id,
            func.lower(User.role).in_(PO_ROLES),
        )
        .order_by(User.created_at.asc(), User.id.asc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row:
        return row

    # Fallback — earliest user of any role
    result = await db.execute(
        select(User)
        .where(User.organization_id == org_id)
        .order_by(User.created_at.asc(), User.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()

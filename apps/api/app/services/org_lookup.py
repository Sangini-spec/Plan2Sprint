"""Organization-by-name canonical lookup (Hotfix 85).

Single source of truth for "given a typed organization name, find or
create the right Organization row". Used by:

  * ``auth/supabase.py`` at signup time (Path B — form signup with all
    fields filled in)
  * ``auth/supabase.py`` for OAuth signups (Path A — placeholder
    org gets created so the user has a valid ``organization_id``;
    later renamed via Settings)
  * ``routers/organizations.py`` at PATCH /current (Path A's later
    rename, where the typed name might match an EXISTING org and the
    user should be migrated rather than the org renamed)

The matching rule is simple and intentionally generous:
    canonical = name.strip().lower()
Any user typing "C2A", "  c2a", or "c2A" lands in the same canonical
slot. The matching is whitespace-trimmed but otherwise preserves the
internal characters — "Concept 2 Action" is NOT the same canonical as
"Concept2Action" on purpose (they could be different orgs).

Security note: this is intentionally name-based for the testing phase
the user is in right now. In a production launch we'd want some
verification step (email-domain match, invitation, owner approval) to
prevent strangers from joining an org just by guessing its name. The
docstring on ``find_or_create_org`` flags this.
"""

from __future__ import annotations

import re
from typing import Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.base import generate_cuid
from ..models.organization import Organization


def canonicalize_org_name(raw: str) -> str:
    """Return the canonical form used for org-row lookup.

    Empty / whitespace-only input becomes "" — callers should treat
    that as "no name supplied" and skip the matching path entirely
    (creating a placeholder org with a unique fallback canonical).
    """
    return (raw or "").strip().lower()


async def find_org_by_name(db: AsyncSession, raw_name: str) -> Organization | None:
    """Look up an existing org by typed name (case-insensitive).

    Returns the matching ``Organization`` or ``None``. Whitespace-only
    or empty inputs always return ``None``.
    """
    canonical = canonicalize_org_name(raw_name)
    if not canonical:
        return None
    result = await db.execute(
        select(Organization).where(Organization.name_canonical == canonical)
    )
    return result.scalar_one_or_none()


async def find_or_create_org(
    db: AsyncSession,
    raw_name: str,
    *,
    fallback_canonical: str | None = None,
) -> Tuple[Organization, bool]:
    """Find an org by typed name OR create a new one.

    Returns ``(org, was_created)``. ``was_created=False`` means the
    caller's user should be ATTACHED to ``org`` (Hotfix 85 makes this
    the correct behaviour for two POs typing the same org name).
    ``was_created=True`` means a brand-new org was just inserted; the
    caller's user is its founding member.

    SECURITY: when ``was_created=False`` the caller is being placed
    inside an existing tenant. During the testing phase we accept this
    on the strength of name-match alone; for production you'd want an
    extra verification step. Audit-log the join at the call site so
    the existing org's PO can see who joined.

    Args:
        raw_name: the user-typed organisation name. Must be non-empty
            for matching to be attempted.
        fallback_canonical: when ``raw_name`` is empty (OAuth signup
            with no org input), the caller can supply a unique
            canonical (e.g. ``f"oauth-placeholder-{uid}"``) so the
            placeholder org satisfies the unique constraint without
            matching anyone else.
    """
    canonical = canonicalize_org_name(raw_name)

    if canonical:
        existing = await find_org_by_name(db, raw_name)
        if existing:
            return existing, False

    # No match (or no name supplied) — create a fresh row.
    new_id = generate_cuid()
    if not canonical:
        # Caller didn't supply a name AND didn't supply a fallback
        # canonical — invent one. This shouldn't happen in well-formed
        # call sites but we fail safe rather than violate NOT NULL.
        canonical = fallback_canonical or f"unnamed-org-{new_id[:8]}"

    # Slug stays globally unique with a random suffix — nothing in the
    # app reads it for matching, only for URL construction. The
    # canonical column is what guarantees one-row-per-typed-name.
    display_name = (raw_name or "").strip() or "Untitled Organization"
    slug_base = re.sub(r"[^a-z0-9]+", "-", canonical).strip("-")[:40] or "org"
    slug = f"{slug_base}-{new_id[:8]}"

    org = Organization(
        id=new_id,
        name=display_name,
        slug=slug,
        name_canonical=canonical,
    )
    db.add(org)
    await db.flush()
    return org, True

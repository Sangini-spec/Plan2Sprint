"""
Onboarding — product-tour state management.

The Plan2Sprint onboarding feature is a role-aware product tour
(welcome modal → spotlight cards → checklist widget → completion
modal) plus first-visit page hints. State lives in
``users.onboarding_progress`` (JSONB column, see ``models/user.py``).

Endpoints:
  GET    /api/onboarding/progress              — current state
  PATCH  /api/onboarding/progress              — advance step / complete / dismiss
  POST   /api/onboarding/replay                — wipe progress + restart
  POST   /api/onboarding/page-hints/seen       — mark a single page hint dismissed
  POST   /api/onboarding/page-hints/reset      — clear all page hints
  POST   /api/onboarding/dismiss               — dismiss tour permanently
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# Roles that map to the three tour variants. Anything outside this set
# falls through to the developer variant (safe default — no PO-only or
# stakeholder-only content leaks).
PO_ROLES = {"product_owner", "owner", "admin", "engineering_manager"}
STAKEHOLDER_ROLES = {"stakeholder"}


def _tour_role_for(user_role: str) -> str:
    """Map a Plan2Sprint role to a tour variant.

    Owner/admin/eng-manager see the PO tour (they share the PO surface).
    Stakeholders see the stakeholder tour. Everyone else (developers,
    unknown roles) sees the developer tour.
    """
    r = (user_role or "").lower()
    if r in PO_ROLES:
        return "product_owner"
    if r in STAKEHOLDER_ROLES:
        return "stakeholder"
    return "developer"


def _empty_progress(user_role: str) -> dict[str, Any]:
    """Default-shape progress for a user who has never started a tour."""
    return {
        "role": _tour_role_for(user_role),
        "current_step": "welcome",
        "completed_steps": [],
        "skipped_steps": [],
        "page_hints_seen": [],
        "status": "not_started",
        "started_at": None,
        "completed_at": None,
        "banner_dismissed": False,
        "replay_count": 0,
    }


async def _load_user(db: AsyncSession, current_user: dict) -> User:
    """Fetch the User row for the caller. 404 if the JWT references a
    user we never imported (e.g. demo mode with a placeholder JWT).
    """
    sup_id = current_user.get("supabase_user_id") or current_user.get("sub")
    if not sup_id:
        raise HTTPException(status_code=401, detail="No supabase user id on token")
    result = await db.execute(
        select(User).where(User.supabase_user_id == sup_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User row not found")
    return user


def _normalise(progress: dict[str, Any] | None, user_role: str) -> dict[str, Any]:
    """Return progress with all expected keys present, healing legacy/empty rows.

    NULL → empty progress for the user's role.
    Partial dict → fill in missing keys with defaults (forward-compat).
    """
    if not progress or not isinstance(progress, dict):
        return _empty_progress(user_role)
    base = _empty_progress(user_role)
    base.update({k: v for k, v in progress.items() if v is not None or k in (
        # Keys where ``None`` is a meaningful value:
        "completed_at",
        "started_at",
    )})
    # Hard-enforce list types — JSON can come back as None from PG
    for list_key in ("completed_steps", "skipped_steps", "page_hints_seen"):
        if not isinstance(base.get(list_key), list):
            base[list_key] = []
    return base


# ---------------------------------------------------------------------------
# GET /api/onboarding/progress
# ---------------------------------------------------------------------------

@router.get("/onboarding/progress")
async def get_progress(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the caller's onboarding state.

    NULL in DB → returns a fresh ``status=not_started`` shape so the
    frontend always has a coherent object to render against.
    """
    user = await _load_user(db, current_user)
    progress = _normalise(user.onboarding_progress, user.role)
    return {"progress": progress}


# ---------------------------------------------------------------------------
# PATCH /api/onboarding/progress
# ---------------------------------------------------------------------------

@router.patch("/onboarding/progress")
async def update_progress(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the caller's onboarding state.

    Accepts a partial payload. The frontend calls this after every
    step transition (Next / Back / Skip step) and on tour completion.

    Body fields (all optional):
      - current_step: str            — step id the user is now on
      - mark_completed: list[str]    — step ids to append to completed_steps
      - mark_skipped: list[str]      — step ids to append to skipped_steps
      - status: str                  — "in_progress" | "completed" | "dismissed"
      - banner_dismissed: bool
    """
    user = await _load_user(db, current_user)
    progress = _normalise(user.onboarding_progress, user.role)

    # ``started_at`` is set on the first transition out of not_started.
    new_status = body.get("status")
    if (
        progress["status"] == "not_started"
        and new_status in ("in_progress", "completed")
        and not progress.get("started_at")
    ):
        progress["started_at"] = datetime.now(timezone.utc).isoformat()

    if "current_step" in body and isinstance(body["current_step"], str):
        progress["current_step"] = body["current_step"]

    if isinstance(body.get("mark_completed"), list):
        for step_id in body["mark_completed"]:
            if step_id and step_id not in progress["completed_steps"]:
                progress["completed_steps"].append(step_id)

    if isinstance(body.get("mark_skipped"), list):
        for step_id in body["mark_skipped"]:
            if step_id and step_id not in progress["skipped_steps"]:
                progress["skipped_steps"].append(step_id)

    if new_status in ("not_started", "in_progress", "completed", "dismissed"):
        progress["status"] = new_status
        if new_status == "completed" and not progress.get("completed_at"):
            progress["completed_at"] = datetime.now(timezone.utc).isoformat()
            # Sync the legacy boolean column so existing code that
            # reads ``user.onboarding_completed`` keeps working.
            user.onboarding_completed = True

    if "banner_dismissed" in body:
        progress["banner_dismissed"] = bool(body["banner_dismissed"])

    # Re-check role assignment in case the caller's role changed since
    # the last update (e.g. an invited dev got promoted to PO mid-tour).
    expected_role = _tour_role_for(user.role)
    if progress.get("role") != expected_role:
        # Reset to start of new tour — don't strand the user on a step
        # that doesn't exist for their new role.
        progress["role"] = expected_role
        progress["current_step"] = "welcome"
        progress["completed_steps"] = []
        progress["skipped_steps"] = []
        progress["status"] = "in_progress"

    user.onboarding_progress = progress
    flag_modified(user, "onboarding_progress")
    await db.commit()
    await db.refresh(user)
    return {"progress": _normalise(user.onboarding_progress, user.role)}


# ---------------------------------------------------------------------------
# POST /api/onboarding/replay
# ---------------------------------------------------------------------------

@router.post("/onboarding/replay")
async def replay_tour(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reset progress to start of the tour, preserving ``page_hints_seen``
    and bumping ``replay_count``.

    Called when the user clicks "Replay the full tour" in Settings →
    Help. The legacy ``onboarding_completed`` boolean is intentionally
    NOT reset — it's a one-way flag for older code paths that care
    about "has this user ever finished onboarding?".
    """
    user = await _load_user(db, current_user)
    progress = _normalise(user.onboarding_progress, user.role)

    progress["status"] = "in_progress"
    progress["current_step"] = "welcome"
    progress["completed_steps"] = []
    progress["skipped_steps"] = []
    progress["started_at"] = datetime.now(timezone.utc).isoformat()
    progress["completed_at"] = None
    progress["replay_count"] = int(progress.get("replay_count") or 0) + 1
    # Don't touch page_hints_seen — Settings has a separate reset for that.

    user.onboarding_progress = progress
    flag_modified(user, "onboarding_progress")
    await db.commit()
    await db.refresh(user)
    return {"progress": _normalise(user.onboarding_progress, user.role)}


# ---------------------------------------------------------------------------
# POST /api/onboarding/page-hints/seen
# ---------------------------------------------------------------------------

@router.post("/onboarding/page-hints/seen")
async def mark_page_hint_seen(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a single page-hint dismissed.

    Body: { "pathname": "/po/retro" }

    Idempotent — same path appended a second time is a no-op.
    """
    pathname = (body.get("pathname") or "").strip()
    if not pathname:
        raise HTTPException(status_code=400, detail="pathname is required")

    user = await _load_user(db, current_user)
    progress = _normalise(user.onboarding_progress, user.role)

    if pathname not in progress["page_hints_seen"]:
        progress["page_hints_seen"].append(pathname)
        user.onboarding_progress = progress
        flag_modified(user, "onboarding_progress")
        await db.commit()

    return {"ok": True, "page_hints_seen": progress["page_hints_seen"]}


# ---------------------------------------------------------------------------
# POST /api/onboarding/page-hints/reset
# ---------------------------------------------------------------------------

@router.post("/onboarding/page-hints/reset")
async def reset_page_hints(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Wipe all page-hint dismissals so they fire again on next visit.

    Triggered from Settings → Help → "Reset all page hints". Useful
    for the user's own testing workflow + for re-introducing hints
    after a UI revision.
    """
    user = await _load_user(db, current_user)
    progress = _normalise(user.onboarding_progress, user.role)
    progress["page_hints_seen"] = []
    user.onboarding_progress = progress
    flag_modified(user, "onboarding_progress")
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /api/onboarding/dismiss
# ---------------------------------------------------------------------------

@router.post("/onboarding/dismiss")
async def dismiss_tour(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently dismiss the tour. Sets ``status=dismissed`` and
    ``banner_dismissed=true``. The user can still replay from Settings.
    """
    user = await _load_user(db, current_user)
    progress = _normalise(user.onboarding_progress, user.role)
    progress["status"] = "dismissed"
    progress["banner_dismissed"] = True
    user.onboarding_progress = progress
    flag_modified(user, "onboarding_progress")
    await db.commit()
    return {"ok": True, "progress": progress}

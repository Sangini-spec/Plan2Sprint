"""
Profile router — GET / PATCH /api/me
Returns the current user's profile merged with TeamMember data (skill_tags).
Always uses real data from the database — no demo fallbacks.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.supabase import get_current_user
from ..config import settings
from ..database import get_db
from ..models.user import User
from ..models.team_member import TeamMember
from ..models.organization import Organization
from ..services.resume_skills_extractor import process_resume_upload

logger = logging.getLogger(__name__)
router = APIRouter()

# 5 MB cap — plenty for a resume, protects the model from huge files
MAX_RESUME_BYTES = 5 * 1024 * 1024
ALLOWED_RESUME_EXTS = (".pdf", ".docx", ".txt")


# ── helpers ──────────────────────────────────────────────────────────────────

def _profile_response(
    user_row: User | None,
    team_member: TeamMember | None,
    org_name: str,
    current_user: dict,
) -> dict:
    """Build a unified profile dict from DB rows + JWT fallback."""
    if user_row:
        return {
            "id": user_row.id,
            "email": user_row.email,
            "fullName": user_row.full_name,
            "avatarUrl": user_row.avatar_url,
            "role": user_row.role.lower(),
            "organizationId": user_row.organization_id,
            "organizationName": org_name,
            "onboardingCompleted": user_row.onboarding_completed,
            "createdAt": user_row.created_at.isoformat() if user_row.created_at else None,
            "skillTags": list(team_member.skill_tags) if team_member and team_member.skill_tags else [],
        }

    # JWT-only fallback (user exists in Supabase but not yet in users table)
    return {
        "id": current_user.get("sub", ""),
        "email": current_user.get("email", ""),
        "fullName": current_user.get("full_name", current_user.get("user_metadata", {}).get("full_name", "")),
        "avatarUrl": None,
        "role": current_user.get("role", current_user.get("user_metadata", {}).get("role", "developer")),
        "organizationId": current_user.get("organization_id", ""),
        "organizationName": org_name or current_user.get("organization_name", ""),
        "onboardingCompleted": current_user.get("onboarding_completed", False),
        "createdAt": None,
        "skillTags": [],
    }


# ── GET /api/me ──────────────────────────────────────────────────────────────

@router.get("/me")
async def get_my_profile(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's profile merged with team-member data."""
    sub = current_user.get("sub") or current_user.get("id", "")
    org_id = current_user.get("organization_id", "")

    # Look up User row
    user_row: User | None = None
    if sub:
        result = await db.execute(
            select(User).where(User.supabase_user_id == sub)
        )
        user_row = result.scalar_one_or_none()

    # Look up matching TeamMember (by email + org)
    email = user_row.email if user_row else current_user.get("email", "")
    team_member: TeamMember | None = None
    if email and org_id:
        result = await db.execute(
            select(TeamMember).where(
                TeamMember.email == email,
                TeamMember.organization_id == org_id,
            )
        )
        team_member = result.scalar_one_or_none()

    # Org name — always fetch from DB
    org_name = ""
    if user_row and user_row.organization_id:
        result = await db.execute(
            select(Organization.name).where(Organization.id == user_row.organization_id)
        )
        row = result.scalar_one_or_none()
        if row:
            org_name = row
    elif org_id:
        # Fallback: try with org_id from JWT
        result = await db.execute(
            select(Organization.name).where(Organization.id == org_id)
        )
        row = result.scalar_one_or_none()
        if row:
            org_name = row

    return _profile_response(user_row, team_member, org_name, current_user)


# ── PATCH /api/me ────────────────────────────────────────────────────────────

@router.patch("/me")
async def update_my_profile(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's own profile fields."""
    sub = current_user.get("sub") or current_user.get("id", "")
    org_id = current_user.get("organization_id", "")

    # Find User row
    result = await db.execute(
        select(User).where(User.supabase_user_id == sub)
    )
    user_row = result.scalar_one_or_none()

    # Also try to find TeamMember by email (for team_member-only users)
    email_from_jwt = current_user.get("email", "")
    team_member: TeamMember | None = None
    if email_from_jwt and org_id:
        tm_result = await db.execute(
            select(TeamMember).where(
                TeamMember.email == email_from_jwt,
                TeamMember.organization_id == org_id,
            )
        )
        team_member = tm_result.scalar_one_or_none()

    if not user_row and not team_member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User record not found. Please ensure your account is fully set up.",
        )

    # Apply allowed fields to User row if it exists
    if user_row:
        if "fullName" in body:
            user_row.full_name = str(body["fullName"]).strip()
        if "email" in body:
            new_email = str(body["email"]).strip().lower()
            if "@" not in new_email:
                raise HTTPException(status_code=400, detail="Invalid email format")
            user_row.email = new_email

    # Apply to TeamMember if it exists
    if team_member:
        if "fullName" in body:
            team_member.display_name = str(body["fullName"]).strip()

    # Skill tags — developers only
    role = ((user_row.role if user_row else None) or (team_member.role if team_member else None) or "").lower()
    if "skillTags" in body and role == "developer":
        tags = body["skillTags"]
        if not isinstance(tags, list):
            raise HTTPException(status_code=400, detail="skillTags must be a list")
        if team_member:
            team_member.skill_tags = [str(t).strip() for t in tags if str(t).strip()]

    await db.commit()
    if user_row:
        await db.refresh(user_row)

    # Re-fetch team member for response
    lookup_email = (user_row.email if user_row else email_from_jwt) or ""
    if org_id and lookup_email:
        tm_result2 = await db.execute(
            select(TeamMember).where(
                TeamMember.email == lookup_email,
                TeamMember.organization_id == org_id,
            )
        )
        team_member = tm_result2.scalar_one_or_none()

    # Org name
    org_name = ""
    effective_org = (user_row.organization_id if user_row else None) or org_id
    if effective_org:
        result = await db.execute(
            select(Organization.name).where(Organization.id == effective_org)
        )
        row = result.scalar_one_or_none()
        if row:
            org_name = row

    return _profile_response(user_row, team_member, org_name, current_user)


# ── POST /api/me/resume ──────────────────────────────────────────────────────

@router.post("/me/resume")
async def upload_resume_for_skills(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a developer resume (PDF/DOCX/TXT) and extract skills via AI.

    The extracted skills are persisted to the current user's TeamMember.skill_tags
    (creating a TeamMember row if one doesn't exist yet). Developer-only.
    """
    # ---- 1. Auth / role gating ----------------------------------------------
    sub = current_user.get("sub") or current_user.get("id", "")
    email = (current_user.get("email") or "").lower()
    org_id = current_user.get("organization_id", "")

    user_row: User | None = None
    if sub:
        result = await db.execute(select(User).where(User.supabase_user_id == sub))
        user_row = result.scalar_one_or_none()

    role = (
        (user_row.role if user_row else current_user.get("role", "")) or ""
    ).lower()
    if role != "developer":
        raise HTTPException(
            status_code=403,
            detail="Resume-based skill extraction is available for developers only.",
        )

    if not email or not org_id:
        raise HTTPException(
            status_code=400,
            detail="Account is missing email or organization.",
        )

    # ---- 2. File validation --------------------------------------------------
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    lower = filename.lower()
    if not lower.endswith(ALLOWED_RESUME_EXTS):
        raise HTTPException(
            status_code=400,
            detail="Please upload a PDF, DOCX, or TXT resume.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="File is too large (max 5 MB).")

    # ---- 3. Extract text + infer skills via Grok -----------------------------
    try:
        skills = await process_resume_upload(filename, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("Resume skill extraction failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="We couldn't analyze this resume. Please try a different file.",
        )

    if not skills:
        return {"skills": [], "message": "No skills were found in the resume."}

    # ---- 4. Persist to TeamMember.skill_tags ---------------------------------
    tm_result = await db.execute(
        select(TeamMember).where(
            TeamMember.email == email,
            TeamMember.organization_id == org_id,
        )
    )
    team_member = tm_result.scalar_one_or_none()

    if team_member is None:
        # Synthetic external_id since this TeamMember isn't tied to a tool source.
        # The unique constraint is on (organization_id, external_id) — "self:<email>"
        # guarantees uniqueness per dev within the org.
        team_member = TeamMember(
            organization_id=org_id,
            external_id=f"self:{email}",
            email=email,
            display_name=(user_row.full_name if user_row else email.split("@")[0]),
            role="developer",
            skill_tags=[],
        )
        db.add(team_member)
        await db.flush()

    team_member.skill_tags = skills
    await db.commit()

    return {"skills": skills}

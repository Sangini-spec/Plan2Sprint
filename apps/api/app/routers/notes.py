"""
Smart Notes — private notebook per user.

Endpoints:
  GET    /api/notes                     — list current user's notes (optional project filter, search)
  POST   /api/notes                     — create a new note
  PATCH  /api/notes/{id}                — update content / category / color / pin / tags
  DELETE /api/notes/{id}                — delete
  POST   /api/notes/{id}/expand         — AI expand a short scribble into a structured note
  POST   /api/notes/{id}/share-to-channel — share to Slack/Teams project channel
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.supabase import get_current_user
from ..config import settings
from ..database import get_db
from ..models.note import Note
from ..models.imported_project import ImportedProject

logger = logging.getLogger(__name__)
router = APIRouter()


# Valid categories — kept loose so users can extend via tags
VALID_CATEGORIES = {"idea", "bug", "feature", "decision", "question", "note"}

# Palette the color auto-cycles through if the user doesn't pick one
COLOR_PALETTE = ["blue", "teal", "mint", "sage", "sky"]


def _serialize(n: Note) -> dict:
    return {
        "id": n.id,
        "content": n.content,
        "category": n.category,
        "color": n.color,
        "pinned": n.pinned,
        "tags": list(n.tags) if n.tags else [],
        "projectId": n.imported_project_id,
        "authorEmail": n.author_email,
        "authorName": n.author_name,
        "createdAt": n.created_at.isoformat() if n.created_at else None,
        "updatedAt": n.updated_at.isoformat() if n.updated_at else None,
    }


# ---------------------------------------------------------------------------
# GET /api/notes
# ---------------------------------------------------------------------------

@router.get("/notes")
async def list_notes(
    project_id: str | None = Query(None, alias="projectId"),
    q: str | None = Query(None),
    category: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's notes. Pinned first, then newest first."""
    org_id = current_user.get("organization_id", "demo-org")
    email = (current_user.get("email") or "").lower()

    stmt = select(Note).where(
        Note.organization_id == org_id,
        Note.author_email == email,
    )
    if project_id:
        stmt = stmt.where(Note.imported_project_id == project_id)
    if category:
        stmt = stmt.where(Note.category == category.lower())
    if q:
        term = f"%{q.strip().lower()}%"
        stmt = stmt.where(Note.content.ilike(term))

    stmt = stmt.order_by(Note.pinned.desc(), Note.updated_at.desc()).limit(200)
    rows = (await db.execute(stmt)).scalars().all()
    return {"notes": [_serialize(n) for n in rows]}


# ---------------------------------------------------------------------------
# POST /api/notes
# ---------------------------------------------------------------------------

@router.post("/notes")
async def create_note(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new note. Auto-attaches to projectId if provided."""
    org_id = current_user.get("organization_id", "demo-org")
    email = (current_user.get("email") or "").lower()

    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Note content cannot be empty")

    category = (body.get("category") or "idea").lower()
    if category not in VALID_CATEGORIES:
        category = "idea"

    # Auto-pick a color if not provided
    color = body.get("color")
    if color not in {"blue", "teal", "mint", "sage", "sky", "amber"}:
        # Deterministic pseudo-random based on hash of email + timestamp-ish for variety
        import hashlib
        idx = int(hashlib.md5(f"{email}{content[:20]}".encode()).hexdigest(), 16) % len(COLOR_PALETTE)
        color = COLOR_PALETTE[idx]

    project_id = body.get("projectId") or None
    tags = body.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    note = Note(
        organization_id=org_id,
        author_email=email,
        author_name=current_user.get("full_name") or email.split("@")[0],
        imported_project_id=project_id,
        content=content,
        category=category,
        color=color,
        pinned=bool(body.get("pinned", False)),
        tags=[str(t).strip() for t in tags if str(t).strip()],
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return {"note": _serialize(note)}


# ---------------------------------------------------------------------------
# PATCH /api/notes/{id}
# ---------------------------------------------------------------------------

@router.patch("/notes/{note_id}")
async def update_note(
    note_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a note. Only the author can modify."""
    org_id = current_user.get("organization_id", "demo-org")
    email = (current_user.get("email") or "").lower()

    result = await db.execute(
        select(Note).where(
            Note.id == note_id,
            Note.organization_id == org_id,
            Note.author_email == email,
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if "content" in body:
        c = (body["content"] or "").strip()
        if c:
            note.content = c
    if "category" in body:
        cat = (body["category"] or "").lower()
        if cat in VALID_CATEGORIES:
            note.category = cat
    if "color" in body and body["color"]:
        note.color = str(body["color"])[:20]
    if "pinned" in body:
        note.pinned = bool(body["pinned"])
    if "tags" in body and isinstance(body["tags"], list):
        note.tags = [str(t).strip() for t in body["tags"] if str(t).strip()]
    if "projectId" in body:
        note.imported_project_id = body["projectId"] or None

    await db.commit()
    await db.refresh(note)
    return {"note": _serialize(note)}


# ---------------------------------------------------------------------------
# DELETE /api/notes/{id}
# ---------------------------------------------------------------------------

@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a note. Only the author can delete."""
    org_id = current_user.get("organization_id", "demo-org")
    email = (current_user.get("email") or "").lower()

    result = await db.execute(
        select(Note).where(
            Note.id == note_id,
            Note.organization_id == org_id,
            Note.author_email == email,
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    await db.delete(note)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /api/notes/{id}/expand — AI expansion via Grok
# ---------------------------------------------------------------------------

EXPAND_SYSTEM = (
    "You are an expert product engineer helping a product owner or developer turn "
    "a rough scribble into a well-structured note. Keep the original intent. Do "
    "not invent requirements the user didn't imply. Be concise — notes are for "
    "thinking, not specs."
)

EXPAND_PROMPT = """\
Expand this rough note into a structured format. Output in markdown with these
sections (keep each section 1-3 sentences unless the source clearly justifies
more detail):

**Idea:** [one-sentence restatement of the core thought]
**Context:** [why it matters / what triggered it]
**Proposed approach:** [how it could be tackled, at a high level]
**Open questions:** [2-3 bullet questions worth clarifying before acting]

Rules:
- Preserve the author's voice. Don't turn a scribble into a PRD.
- If the note is already well-structured, return it mostly unchanged.
- No preamble, no "Here's your expanded note:" — just the markdown.

Original note:
---
%s
---
"""


@router.post("/notes/{note_id}/expand")
async def expand_note(
    note_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Use Grok to expand a short scribble into a structured note. Overwrites content."""
    org_id = current_user.get("organization_id", "demo-org")
    email = (current_user.get("email") or "").lower()

    result = await db.execute(
        select(Note).where(
            Note.id == note_id,
            Note.organization_id == org_id,
            Note.author_email == email,
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if not settings.azure_ai_api_key or not settings.azure_ai_endpoint:
        raise HTTPException(status_code=503, detail="AI service not configured")

    model = settings.azure_ai_model or "grok-4-fast-reasoning"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": EXPAND_SYSTEM},
            {"role": "user", "content": EXPAND_PROMPT % (note.content or "")},
        ],
        "max_tokens": 800,
        "temperature": 0.4,
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": settings.azure_ai_api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(settings.azure_ai_endpoint, headers=headers, json=payload)
            resp.raise_for_status()
        data = resp.json()
        expanded = (data["choices"][0]["message"]["content"] or "").strip()
        # Strip markdown code fences if the model wrapped things
        if expanded.startswith("```"):
            expanded = re.sub(r"^```(?:markdown)?\s*", "", expanded)
            expanded = re.sub(r"\s*```\s*$", "", expanded)
    except Exception as e:  # noqa: BLE001
        logger.exception("AI expand failed: %s", e)
        raise HTTPException(status_code=500, detail="AI expand failed. Try again.")

    if not expanded:
        raise HTTPException(status_code=500, detail="AI returned empty response")

    note.content = expanded
    await db.commit()
    await db.refresh(note)
    return {"note": _serialize(note)}


# ---------------------------------------------------------------------------
# POST /api/notes/{id}/share-to-channel
# ---------------------------------------------------------------------------

@router.post("/notes/{note_id}/share-to-channel")
async def share_note_to_channel(
    note_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Share a note to its project channel on Slack or Teams.

    Body: { "platform": "slack" | "teams" }
    Uses the existing post-to-channel infrastructure via a `custom_message` action.
    """
    org_id = current_user.get("organization_id", "demo-org")
    email = (current_user.get("email") or "").lower()
    platform = (body.get("platform") or "").lower()

    if platform not in ("slack", "teams"):
        raise HTTPException(status_code=400, detail="platform must be 'slack' or 'teams'")

    result = await db.execute(
        select(Note).where(
            Note.id == note_id,
            Note.organization_id == org_id,
            Note.author_email == email,
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if not note.imported_project_id:
        raise HTTPException(status_code=400, detail="Note has no project — can't share to channel")

    # Format the note body
    cat_label = note.category.capitalize() if note.category else "Note"
    message = f"💡 *{cat_label} by {note.author_name or email.split('@')[0]}*\n\n{note.content}"

    # Delegate to the existing post-to-channel endpoint via internal call
    from .integrations import _slack_channels, _teams_channels
    internal_body = {
        "projectId": note.imported_project_id,
        "type": "custom_message",
        "data": {"message": message},
    }

    try:
        if platform == "slack":
            share_result = await _slack_channels.post_to_project_channel(
                body=internal_body, current_user=current_user, db=db,
            )
        else:
            share_result = await _teams_channels.post_to_project_channel(
                body=internal_body, current_user=current_user, db=db,
            )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("Share note failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to share note")

    return {"ok": True, "result": share_result}

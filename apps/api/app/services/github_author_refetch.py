"""
Backfill ``Commit.author_email`` / ``Commit.author_name`` from the GitHub
REST API, then re-resolve ``Commit.author_id`` via the improved
``find_team_member_by_github`` matcher.

Why this exists
---------------
The original push webhook ingestion path stored only ``Commit.author_id``,
which is the result of a TeamMember-lookup heuristic that often picks the
wrong row (multi-org users have multiple TMs across roles with different
emails). The raw GitHub author email — the single most reliable identity
signal — was discarded.

When the standup engine then tries to match commits to a developer's
standup report by ``Commit.author_id IN <dev_tms>``, those misattributed
commits become invisible because their author_id points at a TM the
report's email cluster doesn't include.

Fix: re-fetch the commit detail from GitHub for every Commit row with
``author_email IS NULL`` in the caller's org, populate the missing fields,
and re-run the matcher with the now-known email. The curated standup view
then matches commits via ``LOWER(author_email) IN <report_emails>`` —
which is robust to TM-row mis-attribution.

Public surface
--------------
``refetch_orphan_authors(db, org_id)`` is callable from any context (the
admin HTTP endpoint AND the standup generator's inline path). Returns a
small summary dict for logging.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.repository import Repository
from ..models.team_member import TeamMember
from ..models.tool_connection import ToolConnection
from ..models.repository import Commit
from .encryption import decrypt_token_safe
from .github_tracker import find_team_member_by_github

logger = logging.getLogger(__name__)

# Cap per-call so a runaway org doesn't hammer GitHub or block the
# standup endpoint indefinitely. With 200ms-per-call latency this
# bounds inline refetches to ~60s wall time per org.
_MAX_REFETCH_PER_CALL = 300

GITHUB_TIMEOUT_S = 12.0


async def _resolve_github_token(db: AsyncSession, org_id: str) -> str | None:
    """Resolve the access token to use for refetch — prefers an org-level
    GitHub connection; returns None if not connected or token undecryptable.

    Two value-format gotchas I hit before this comment landed:
      1. The column is ``source_tool``, not ``tool`` (which raised
         AttributeError at class-attr access time).
      2. The value is stored UPPERCASE (``"GITHUB"``) per the existing
         ``_get_github_connection`` helper in routers/integrations/github.py;
         a lowercase compare returned no rows and the refetch logged
         ``skipped: no_github_connection`` while a valid connection
         existed. We do a case-insensitive match here to be safe.
    """
    from sqlalchemy import func as _sa_func
    conn_q = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            _sa_func.upper(ToolConnection.source_tool) == "GITHUB",
        ).limit(1)
    )
    conn = conn_q.scalar_one_or_none()
    if not conn or not conn.access_token:
        return None
    return decrypt_token_safe(conn.access_token) or None


async def refetch_orphan_authors(db: AsyncSession, org_id: str) -> dict[str, Any]:
    """Populate ``author_email`` / ``author_name`` for every commit in
    ``org_id``'s repos whose ``author_email`` is NULL.

    Idempotent — only touches rows with NULL email. Safe to call from a
    request handler or a scheduled task.

    Returns:
        {"orphansFound": N, "updated": N, "reattributed": N,
         "errors": N, "skipped": "reason" | None}
    """
    token = await _resolve_github_token(db, org_id)
    if not token:
        return {
            "orphansFound": 0, "updated": 0, "reattributed": 0,
            "errors": 0, "skipped": "no_github_connection",
        }

    orphans_q = await db.execute(
        select(Commit, Repository.full_name)
        .join(Repository, Repository.id == Commit.repository_id)
        .where(
            Repository.organization_id == org_id,
            Commit.author_email.is_(None),
        )
        .order_by(Commit.committed_at.desc())
        .limit(_MAX_REFETCH_PER_CALL)
    )
    orphans = list(orphans_q.all())
    if not orphans:
        return {
            "orphansFound": 0, "updated": 0, "reattributed": 0,
            "errors": 0, "skipped": None,
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    updated = 0
    reattributed = 0
    errors = 0

    async with httpx.AsyncClient(timeout=GITHUB_TIMEOUT_S, headers=headers) as client:
        for commit, full_name in orphans:
            try:
                url = f"https://api.github.com/repos/{full_name}/commits/{commit.sha}"
                resp = await client.get(url)
                if resp.status_code != 200:
                    errors += 1
                    continue
                payload = resp.json() or {}
                author_obj = (payload.get("commit") or {}).get("author") or {}
                login = ((payload.get("author") or {}).get("login")) or None
                a_email = author_obj.get("email") or None
                a_name = author_obj.get("name") or None

                commit.author_email = a_email
                commit.author_name = a_name
                updated += 1

                # Re-resolve author_id with the new identity info.
                tm = await find_team_member_by_github(
                    db, org_id,
                    github_username=login,
                    github_email=a_email,
                )
                if tm and commit.author_id != tm.id:
                    commit.author_id = tm.id
                    reattributed += 1
            except Exception as e:  # noqa: BLE001
                errors += 1
                logger.debug(
                    f"[Refetch] {full_name}/{commit.sha[:8]} failed: {e}"
                )

    await db.flush()
    return {
        "orphansFound": len(orphans),
        "updated": updated,
        "reattributed": reattributed,
        "errors": errors,
        "skipped": None,
    }

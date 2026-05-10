"""
GET|POST|PATCH /api/standups
Standup digest retrieval, note submission, and notes-by-date lookup.
Queries real data from StandupReport, TeamStandupDigest, BlockerFlag tables.

POST /api/standups/generate  — auto-generate standups from synced work items/PRs

Response format matches the Next.js frontend expectations:
- GET returns: id, organizationId, iterationId, digestDate, sprintPacing,
  acknowledgedPct, sprintHealth, blockerCount, summaryText, atRiskItems,
  individualReports, submittedNotes
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import date, datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models import StandupReport, TeamStandupDigest, BlockerFlag, TeamMember
from ..models.work_item import WorkItem
from ..models.repository import Commit, PullRequest, Repository
from ..services.ws_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_individual_reports(
    reports: list,
    curated_by_report_id: dict[str, dict] | None = None,
    notes_by_email: dict[str, list] | None = None,
    drop_empty: bool = True,
    ticket_title_by_ext_id: dict[str, str] | None = None,
) -> list[dict]:
    """Build individualReports array from StandupReport rows.

    Hotfix 41: each row now carries `recentActivity` (last 48-72h GitHub
    items) and `inFlight` (work items still in progress) computed by the
    caller via `_compute_curated_views`. The legacy `completed[]` and
    `inProgress[]` arrays are still returned (capped at 8/5) for backward
    compatibility with the dev-side standup page; full sprint contributions
    are fetched on demand via /api/standups/{id}/sprint-contributions.
    """
    individual_reports = []
    for r in reports:
        member_name = r.team_member.display_name if r.team_member else None

        def _humanise(desc: str | None, ticket_ref: str | None = None) -> str:
            """Make AI-detected blocker text presentable:
            - Strip the noisy `[AI Detected - <type>]` prefix the agent
              prepends — the user has flagged it as engineering jargon.
            - Replace generic "Developer" with the actual name.
            - Append the ticket reference *with its title* so the PO can see
              exactly which work item is stuck without cross-referencing.
            Hotfix 45.
            """
            import re as _re
            text = (desc or "").strip()

            # Hotfix 45: keep the reason tag (e.g. "[stalled_ticket]") but
            # strip the noisy "AI Detected -" preamble. Bare "[AI Detected]"
            # with no type collapses entirely.
            text = _re.sub(
                r"^\s*\[\s*AI\s+Detected\s*-\s*([^\]]+)\]\s*",
                r"[\1] ",
                text,
                flags=_re.IGNORECASE,
            )
            text = _re.sub(
                r"^\s*\[\s*AI\s+Detected\s*\]\s*",
                "",
                text,
                flags=_re.IGNORECASE,
            )

            if member_name:
                text = _re.sub(r"\bDeveloper\b", member_name, text, count=1)

            # Build a "(MED-2341 — Build CI pipeline)" suffix, falling back
            # to plain ticket id when title is unknown.
            if ticket_ref:
                title = (ticket_title_by_ext_id or {}).get(ticket_ref, "").strip()
                if title:
                    suffix = f"({ticket_ref} — {title})"
                else:
                    suffix = f"({ticket_ref})"
                # Don't double-append if the agent already inlined the ref.
                if ticket_ref not in text:
                    text = f"{text} {suffix}".strip() if text else f"Blocker on {suffix}"
                elif title and title not in text:
                    # Replace the bare ticket id with the enriched form.
                    text = text.replace(ticket_ref, f"{ticket_ref} — {title}", 1)
            return text.strip()

        blockers = []
        for bf in (r.blocker_flags if hasattr(r, "blocker_flags") and r.blocker_flags else []):
            # Skip resolved/closed blockers and any whose status indicates
            # they've already been actioned. The standup_generator's
            # auto-resolve marks these RESOLVED when the ticket reaches a
            # terminal status, but historical data + race conditions
            # (e.g. blocker added by the agent after generator ran) mean
            # we double-check here too.
            if (bf.status or "").upper() in ("RESOLVED", "CLOSED", "DISMISSED"):
                continue
            if bf.resolved_at is not None:
                continue
            blockers.append({
                "description": _humanise(bf.description, bf.ticket_reference),
                "status": bf.status,
                "ticketId": bf.ticket_reference,
            })

        # Also include inline blockers from the JSON field
        if isinstance(r.blockers, list):
            for b in r.blockers:
                if isinstance(b, dict):
                    blockers.append({
                        "description": _humanise(b.get("description", str(b)), b.get("ticketId")),
                        "status": b.get("status", "OPEN"),
                        "ticketId": b.get("ticketId"),
                    })
                elif isinstance(b, str):
                    blockers.append({"description": _humanise(b), "status": "OPEN"})

        completed_full = r.completed_items if isinstance(r.completed_items, list) else []
        in_progress_full = r.in_progress_items if isinstance(r.in_progress_items, list) else []

        # Cap the legacy arrays so the default response stays compact.
        completed_capped = completed_full[:8]
        in_progress_capped = in_progress_full[:5]

        curated = (curated_by_report_id or {}).get(r.id, {})
        recent_activity = curated.get("recentActivity", [])
        in_flight = curated.get("inFlight", [])

        # Recompute isInactive: nothing in any window AND no blocker.
        is_inactive = bool(r.is_inactive) and not blockers and not recent_activity and not in_flight
        # Also flip inactive back to True if every curated bucket is empty.
        if not recent_activity and not in_flight and not blockers:
            is_inactive = True

        email = (r.team_member.email if r.team_member and r.team_member.email else "") or ""

        # Hotfix 43: drop rows that have absolutely nothing to show — no
        # recent activity, no in-flight, no blocker, no historic items, no
        # developer note. Otherwise the digest fills with "0 done · 0 in
        # progress" placeholders that the user has flagged as a "dump".
        has_note = bool((notes_by_email or {}).get(email.lower()))
        if drop_empty and not (
            recent_activity
            or in_flight
            or blockers
            or completed_full
            or in_progress_full
            or has_note
        ):
            continue

        individual_reports.append({
            "id": r.id,
            "teamMemberId": r.team_member_id,
            "email": email.lower(),
            "displayName": r.team_member.display_name if r.team_member else "Unknown",
            "avatarUrl": r.team_member.avatar_url if r.team_member else None,
            "githubUsername": r.team_member.github_username if r.team_member else None,
            "acknowledged": r.acknowledged,
            "isInactive": is_inactive,
            # Curated views (Hotfix 41)
            "recentActivity": recent_activity,
            "inFlight": in_flight,
            # Legacy capped arrays (kept for backward compatibility)
            "completedCount": len(completed_full),
            "inProgressCount": len(in_progress_full),
            "blockerCount": len(blockers),
            "completed": completed_capped,
            "inProgress": in_progress_capped,
            "hasMoreSprintContributions": len(completed_full) > 8 or len(in_progress_full) > 5,
            "blockers": blockers,
            "narrativeText": r.narrative_text or "",
            "reportDate": r.report_date.isoformat() if r.report_date else None,
            "teamMember": r.team_member.display_name if r.team_member else "Unknown",
        })

    return individual_reports


# ---------------------------------------------------------------------------
# Hotfix 41 helpers — dedupe by email + compute curated views
# ---------------------------------------------------------------------------

def _dedupe_reports_by_email(
    reports: list,
    project_id: str | None,
) -> list:
    """Reduce to exactly one StandupReport per real human, MERGING content
    across that human's TM rows rather than picking one.

    Plan2Sprint accumulates multiple TeamMember rows per real human:
    - Same email, different rows (org imports, stale syncs)
    - Different emails, same display_name (e.g. work vs personal email)

    Original behaviour was "pick the highest-scoring row, drop the rest",
    which silently lost work credited to lower-scoring rows. We saw a
    user (Sangini) whose project-matched TM had 0 done / 20 stale
    in-progress items, while her *other* TM (different email, NULL
    project) had 20 freshly-closed items. The pick-one path landed on
    the empty stale TM and the PO standup looked completely empty.

    New behaviour: merge same-human reports into a single synthetic
    report that has the union of completed / in_progress / blockers /
    developer_note across all TM rows for that human. We pick a
    representative `team_member` (using the original score) so the
    response keeps a single consistent display_name + email, but the
    underlying lists carry everyone's contributions.

    Preference order for the representative TM (highest first):
      1. not excluded
      2. project-matched (project_id == imported_project_id)
      3. has github_username
      4. has report content
      5. report_date is most recent
    """
    def score(r) -> tuple:
        tm = r.team_member
        not_excluded = 1 if (not tm or (tm.role or "") != "excluded") else 0
        project_match = 1 if (tm and project_id and tm.imported_project_id == project_id) else 0
        has_gh = 1 if (tm and tm.github_username) else 0
        has_note = 1 if r.developer_note else 0
        completed_n = len(r.completed_items) if isinstance(r.completed_items, list) else 0
        in_progress_n = len(r.in_progress_items) if isinstance(r.in_progress_items, list) else 0
        blocker_n = len(r.blockers) if isinstance(r.blockers, list) else 0
        has_content = 1 if (has_note or completed_n or in_progress_n or blocker_n) else 0
        ts = r.report_date.timestamp() if r.report_date else 0
        return (not_excluded, project_match, has_gh, has_content, ts)

    def cluster_key(r) -> str:
        """Stable per-human key. Prefer display_name; fall back to email
        cluster; then the team_member_id (so identityless rows still
        survive as their own cluster instead of all collapsing)."""
        name = (
            r.team_member.display_name
            if r.team_member and r.team_member.display_name else ""
        ).strip().lower()
        if name:
            return f"name:{name}"
        email = (
            r.team_member.email if r.team_member and r.team_member.email else ""
        ).strip().lower()
        if email:
            return f"email:{email}"
        return f"id:{r.team_member_id}"

    # Group reports by human cluster, then merge.
    clusters: dict[str, list] = {}
    for r in reports:
        clusters.setdefault(cluster_key(r), []).append(r)

    def _key_of(item) -> str:
        if not isinstance(item, dict):
            return str(item)
        return (
            item.get("ticketId")
            or item.get("id")
            or (item.get("title") or "").strip().lower()
        )

    merged: list = []
    for _, members in clusters.items():
        # Single-member cluster — return as-is (no merge needed).
        if len(members) == 1:
            merged.append(members[0])
            continue

        # Pick the representative report — highest score (drives email/
        # display_name on the response). Sort ascending then take last.
        members_sorted = sorted(members, key=score)
        rep = members_sorted[-1]

        # Union completed_items / in_progress_items / blockers,
        # deduped by ticketId (or title fallback).
        seen_completed: set[str] = set()
        seen_inprog: set[str] = set()
        seen_blockers: set[str] = set()
        completed_merged: list = []
        in_progress_merged: list = []
        blockers_merged: list = []

        for m in members:
            for it in (m.completed_items if isinstance(m.completed_items, list) else []):
                k = _key_of(it)
                if k and k not in seen_completed:
                    seen_completed.add(k)
                    completed_merged.append(it)
            for it in (m.in_progress_items if isinstance(m.in_progress_items, list) else []):
                k = _key_of(it)
                if k and k not in seen_inprog:
                    seen_inprog.add(k)
                    in_progress_merged.append(it)
            for it in (m.blockers if isinstance(m.blockers, list) else []):
                k = _key_of(it)
                if k and k not in seen_blockers:
                    seen_blockers.add(k)
                    blockers_merged.append(it)

        # Concatenate developer_notes from every TM (most TMs will not
        # have one; when more than one does, keep the union with a
        # separator so neither author's note is silently dropped).
        notes = [
            (m.developer_note or "").strip()
            for m in members
            if (m.developer_note or "").strip()
        ]
        merged_note = "\n---\n".join(notes) if notes else None

        # Mutate the representative in place. SQLAlchemy lets us mutate
        # the loaded entity; we don't commit, so this is response-only.
        rep.completed_items = completed_merged
        rep.in_progress_items = in_progress_merged
        rep.blockers = blockers_merged
        if merged_note:
            rep.developer_note = merged_note

        # Rebuild the narrative from the MERGED lists. Without this,
        # the displayed sentence stays as the representative TM's
        # original narrative — which was generated before the merge
        # and reflects only that one TM's content. We've watched a
        # PO see "Sangini Tripathi has no recently completed items"
        # over a row whose merged completed_items was 20 strong,
        # because the rep TM's local narrative said "no recently
        # completed" (it had 0 done before the merge).
        disp = (
            rep.team_member.display_name if rep.team_member else None
        ) or "This developer"
        narr_parts: list[str] = []
        if completed_merged:
            titles = ", ".join(
                ((c.get("title") if isinstance(c, dict) else "") or "")[:40]
                for c in completed_merged[:3]
            )
            suffix = (
                f" and {len(completed_merged) - 3} more"
                if len(completed_merged) > 3 else ""
            )
            narr_parts.append(
                f"{disp} recently completed {titles}{suffix}."
            )
        else:
            narr_parts.append(f"{disp} has no recently completed items.")
        if in_progress_merged:
            titles = ", ".join(
                ((ip.get("title") if isinstance(ip, dict) else "") or "")[:40]
                for ip in in_progress_merged[:3]
            )
            suffix = (
                f" and {len(in_progress_merged) - 3} more"
                if len(in_progress_merged) > 3 else ""
            )
            narr_parts.append(f"Currently working on {titles}{suffix}.")
        if blockers_merged:
            n = len(blockers_merged)
            narr_parts.append(
                f"⚠ {n} blocker{'s' if n > 1 else ''} reported."
            )
        rep.narrative_text = " ".join(narr_parts)

        # Also union blocker_flags (the SQLAlchemy relationship) so the
        # response builder picks them all up. We dedupe by ticket_reference.
        seen_bf: set[str] = set()
        bf_merged: list = []
        for m in members:
            existing_bf = m.blocker_flags if hasattr(m, "blocker_flags") else []
            for bf in (existing_bf or []):
                key = (bf.ticket_reference or "") + "|" + (bf.description or "")
                if key and key not in seen_bf:
                    seen_bf.add(key)
                    bf_merged.append(bf)
        try:
            rep.blocker_flags = bf_merged
        except Exception:
            # Mutating a SQLAlchemy backref collection can fail in some
            # session states. Fall through; the inline blockers list
            # above still surfaces the relevant data.
            pass

        merged.append(rep)

    return merged


async def _compute_curated_views(
    db: AsyncSession,
    reports: list,
    org_id: str,
    project_id: str | None,
) -> dict[str, dict]:
    """For each StandupReport, compute:

      - recentActivity: last 48h (or 72h on Mondays) commits + PRs, scoped
        to the project's repos (via author_id IN project_team_members) so a
        developer in two projects only sees their selected-project work.
      - inFlight: WorkItems still IN_PROGRESS / IN_REVIEW assigned to this
        developer, scoped to the project, capped at 5.

    Returned shape: {report_id: {recentActivity: [...], inFlight: [...]}}.
    """
    if not reports:
        return {}

    now = datetime.now(timezone.utc)
    # Monday → look back 72h (so weekend GitHub work surfaces); else 48h.
    hours = 72 if now.weekday() == 0 else 48
    since = now - timedelta(hours=hours)

    # Build author-cluster: all TeamMember rows in the org sharing the same
    # email as a report's team_member. Scoping a single human's GitHub
    # activity requires hitting every TM row their commits/PRs were ever
    # attributed to. We then narrow further to the project later.
    emails = list({
        (r.team_member.email or "").lower()
        for r in reports
        if r.team_member and r.team_member.email
    })
    if not emails:
        return {r.id: {"recentActivity": [], "inFlight": []} for r in reports}

    cluster_q = select(TeamMember).where(
        TeamMember.organization_id == org_id,
        func.lower(TeamMember.email).in_(emails),
        or_(TeamMember.role.is_(None), TeamMember.role != "excluded"),
    )
    cluster_rows = (await db.execute(cluster_q)).scalars().all()

    # Map email -> [tm_id, ...] (project-scoped if project_id given)
    tms_by_email: dict[str, list[str]] = {}
    project_tm_ids_by_email: dict[str, list[str]] = {}
    for tm in cluster_rows:
        em = (tm.email or "").lower()
        tms_by_email.setdefault(em, []).append(tm.id)
        if project_id and tm.imported_project_id == project_id:
            project_tm_ids_by_email.setdefault(em, []).append(tm.id)

    # If project_id given, prefer project-scoped TM ids; else use full cluster.
    activity_tms_by_email: dict[str, list[str]] = {}
    for em in emails:
        if project_id and project_tm_ids_by_email.get(em):
            activity_tms_by_email[em] = project_tm_ids_by_email[em]
        else:
            activity_tms_by_email[em] = tms_by_email.get(em, [])

    # Bulk-fetch commits + PRs across all TM ids in one shot, then bucket.
    all_tm_ids = [tid for ids in activity_tms_by_email.values() for tid in ids]
    commits: list = []
    prs: list = []

    if all_tm_ids:
        commit_q = (
            select(Commit, Repository.name)
            .join(Repository, Commit.repository_id == Repository.id)
            .where(
                Commit.author_id.in_(all_tm_ids),
                Commit.committed_at >= since,
            )
            .order_by(Commit.committed_at.desc())
            .limit(200)
        )
        commits = (await db.execute(commit_q)).all()

        pr_q = (
            select(PullRequest, Repository.name)
            .join(Repository, PullRequest.repository_id == Repository.id)
            .where(
                PullRequest.author_id.in_(all_tm_ids),
                or_(
                    PullRequest.created_external_at >= since,
                    PullRequest.merged_at >= since,
                ),
            )
            .order_by(
                func.coalesce(PullRequest.merged_at, PullRequest.created_external_at).desc()
            )
            .limit(100)
        )
        prs = (await db.execute(pr_q)).all()

    # Index by tm_id for fast bucketing
    commits_by_tm: dict[str, list] = {}
    for c, repo_name in commits:
        commits_by_tm.setdefault(c.author_id, []).append((c, repo_name))
    prs_by_tm: dict[str, list] = {}
    for p, repo_name in prs:
        prs_by_tm.setdefault(p.author_id, []).append((p, repo_name))

    # In-flight WorkItems: assigned to this email's TM cluster, project-scoped.
    work_items_by_email: dict[str, list] = {}
    if all_tm_ids:
        # ── Hotfix 42b: shadow-done filter ──────────────────────────────
        # Plan2Sprint's WorkItem unique key is (org_id, external_id,
        # source_tool), which permits two rows for the same logical item
        # if the imports disagree on external_id. The project plan
        # dedupes on render and shows the DONE row; the standup query
        # used to surface the lingering IN_PROGRESS duplicate, making
        # finished features look unfinished here. Build the set of
        # "logical identifiers" that are already terminal somewhere in
        # this project, then drop in-flight rows whose sibling is in it.
        from ..services._planning_status import TERMINAL_STATUSES

        terminal_keys: set[str] = set()
        if project_id:
            done_q = select(WorkItem.external_id, WorkItem.title, WorkItem.status).where(
                WorkItem.imported_project_id == project_id,
            )
            done_rows = (await db.execute(done_q)).all()
            for ext_id, title, status in done_rows:
                if (status or "").upper() in TERMINAL_STATUSES:
                    if ext_id:
                        terminal_keys.add(f"ext::{ext_id}")
                    if title:
                        terminal_keys.add(f"title::{title.strip().lower()}")

        wi_q = select(WorkItem).where(
            WorkItem.assignee_id.in_(all_tm_ids),
            WorkItem.status.in_(["IN_PROGRESS", "IN_REVIEW"]),
        )
        if project_id:
            wi_q = wi_q.where(WorkItem.imported_project_id == project_id)
        wi_q = wi_q.order_by(WorkItem.updated_at.desc()).limit(200)
        wi_rows = (await db.execute(wi_q)).scalars().all()
        # Map TM ID back to email
        email_by_tm: dict[str, str] = {}
        for em, ids in activity_tms_by_email.items():
            for tid in ids:
                email_by_tm[tid] = em
        for wi in wi_rows:
            # Skip rows whose duplicate sibling is already DONE/terminal.
            ext_key = f"ext::{wi.external_id}" if wi.external_id else None
            title_key = f"title::{(wi.title or '').strip().lower()}"
            if ext_key and ext_key in terminal_keys:
                continue
            if title_key in terminal_keys:
                continue
            em = email_by_tm.get(wi.assignee_id or "", "")
            if em:
                work_items_by_email.setdefault(em, []).append(wi)

    # Assemble curated views per report, deduplicating items across the cluster
    out: dict[str, dict] = {}
    for r in reports:
        em = ((r.team_member.email if r.team_member and r.team_member.email else "") or "").lower()
        tm_ids = activity_tms_by_email.get(em, [])

        recent: list[dict] = []
        # Group commits per (repo, day) to avoid 47-line lists
        commit_groups: dict[tuple[str, str], dict] = {}
        for tid in tm_ids:
            for c, repo_name in commits_by_tm.get(tid, []):
                day = c.committed_at.date().isoformat() if c.committed_at else ""
                key = (repo_name or "", day)
                if key not in commit_groups:
                    commit_groups[key] = {
                        "type": "commits",
                        "repo": repo_name or "",
                        "day": day,
                        "count": 0,
                        "occurredAt": c.committed_at.isoformat() if c.committed_at else "",
                    }
                commit_groups[key]["count"] += 1
                # Keep the latest occurredAt for sorting
                if c.committed_at and c.committed_at.isoformat() > commit_groups[key]["occurredAt"]:
                    commit_groups[key]["occurredAt"] = c.committed_at.isoformat()

        for grp in commit_groups.values():
            recent.append({
                "type": "commits",
                "title": f"Pushed {grp['count']} commit{'s' if grp['count'] != 1 else ''} to {grp['repo']}",
                "repo": grp["repo"],
                "count": grp["count"],
                "occurredAt": grp["occurredAt"],
            })

        # PRs (each one separate — they're meaningful events)
        seen_prs: set[tuple[str, int]] = set()
        for tid in tm_ids:
            for pr, repo_name in prs_by_tm.get(tid, []):
                key = (repo_name or "", pr.number or 0)
                if key in seen_prs:
                    continue
                seen_prs.add(key)
                merged = bool(pr.merged_at)
                ts = (pr.merged_at or pr.created_external_at)
                recent.append({
                    "type": "pr",
                    "title": (
                        f"Merged PR #{pr.number} — {pr.title}"
                        if merged
                        else f"Opened PR #{pr.number} — {pr.title}"
                    ),
                    "repo": repo_name or "",
                    "prNumber": pr.number,
                    "prStatus": "MERGED" if merged else (pr.status or "OPEN"),
                    "url": pr.url,
                    "occurredAt": ts.isoformat() if ts else "",
                })

        # Sort newest-first, cap at 8
        recent.sort(key=lambda x: x.get("occurredAt", ""), reverse=True)
        recent = recent[:8]

        # In-flight work items
        in_flight: list[dict] = []
        seen_wi: set[str] = set()
        for wi in work_items_by_email.get(em, []):
            if wi.id in seen_wi:
                continue
            seen_wi.add(wi.id)
            in_flight.append({
                "id": wi.id,
                "title": wi.title,
                "ticketId": wi.external_id,
                "status": wi.status,
                "type": wi.type,
                "updatedAt": wi.updated_at.isoformat() if wi.updated_at else None,
            })
        in_flight = in_flight[:5]

        out[r.id] = {"recentActivity": recent, "inFlight": in_flight}

    return out


def _build_submitted_notes(
    reports: list,
    query_date: str,
    current_user_email: str = "",
    current_user_name: str = "",
) -> list[dict]:
    """Build submittedNotes array from reports with developer_note.

    If current_user_email matches the team member's email, use the logged-in
    user's name (from JWT) instead of the team_member.display_name, which may
    be stale or incorrectly linked.
    """
    submitted_notes = []
    for r in reports:
        if r.developer_note:
            # Determine author name: prefer the logged-in user's name if this
            # is their own report (match by email).
            author = r.team_member.display_name if r.team_member else "Unknown"
            if (
                current_user_email
                and r.team_member
                and r.team_member.email
                and r.team_member.email.lower() == current_user_email.lower()
                and current_user_name
            ):
                author = current_user_name

            submitted_notes.append({
                "id": r.id,
                "date": r.report_date.date().isoformat() if r.report_date else query_date,
                "author": author,
                "authorRole": "developer",
                "note": r.developer_note,
                "submittedAt": r.created_at.isoformat() if r.created_at else None,
            })
    return submitted_notes


# ---------------------------------------------------------------------------
# GET /api/standups — Retrieve standup digest + reports
# ---------------------------------------------------------------------------

@router.get("/standups")
async def get_standup_digest(
    date_param: str | None = Query(None, alias="date"),
    auto_generate: bool = Query(True, alias="autoGenerate"),
    force_refresh: bool = Query(False, alias="forceRefresh"),
    project_id: str | None = Query(None, alias="projectId"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")
    today = date.today()
    query_date = date_param or today.isoformat()

    # If requesting today's data and auto_generate is on, generate if needed.
    #
    # Trigger conditions for (re)generation:
    #   1. forceRefresh query param is true — explicit user click on the
    #      dashboard Refresh button. Always regenerates.
    #   2. No reports exist for today — first request of the day. Always
    #      regenerates (the original gate).
    #   3. Latest report on file is older than STALENESS_THRESHOLD_SEC.
    #      Without this, the morning's auto-gen is the only generation
    #      that ever runs — work items closed *after* that morning never
    #      surface in the dashboard until the next day. We've watched
    #      developers close half a sprint's worth of tickets and see
    #      "No standup generated" because the report_count > 0 gate
    #      blocked any refresh.
    is_today_request = query_date == today.isoformat()
    is_weekend = today.weekday() in (5, 6)
    STALENESS_THRESHOLD_SEC = 60  # regenerate if last gen older than this
    if is_today_request and auto_generate and not is_weekend:
        latest_q = await db.execute(
            select(func.max(StandupReport.report_date)).where(
                StandupReport.organization_id == org_id,
                func.date(StandupReport.report_date) == today,
            )
        )
        latest_at = latest_q.scalar()
        from datetime import datetime as _dt, timezone as _tz
        now_utc = _dt.now(_tz.utc)
        stale = (
            latest_at is None
            or (now_utc - latest_at).total_seconds() > STALENESS_THRESHOLD_SEC
        )
        if force_refresh or stale:
            # When force_refresh is on AND we have a project context,
            # pull fresh data from ADO/Jira before regenerating standups.
            # Without this, the standup generator works off whatever
            # status/assignment data was last synced — which can be days
            # stale if no PO/dev has hit the Refresh-style endpoints
            # recently. Users see "X is in progress" for items that are
            # already closed in ADO, and "no recently completed items"
            # for items they shipped yesterday.
            #
            # Best effort only: any sync error is logged and we still
            # regenerate standups from current local state.
            if force_refresh and project_id:
                try:
                    from .integrations.sync import auto_sync_project
                    sync_result = await auto_sync_project(
                        body={"projectId": project_id},
                        current_user=current_user,
                        db=db,
                    )
                    logger.info(
                        f"Pre-standup sync for project {project_id}: "
                        f"{sync_result.get('synced') if isinstance(sync_result, dict) else sync_result}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Pre-standup sync failed for project {project_id}: {e} "
                        "(continuing with stale local data)"
                    )

            try:
                from ..services.standup_generator import generate_all_standups
                result = await generate_all_standups(db, org_id)
                logger.info(
                    f"Generated standups for {org_id}: {result} "
                    f"(force={force_refresh}, stale={stale}, latest={latest_at})"
                )
            except Exception as e:
                logger.warning(f"Auto-generation failed: {e}")

    # ── Hotfix 29 — weekend fallback ──
    # On Saturday/Sunday, no new standups are generated, so showing a strict
    # "today" filter would always return an empty page. Instead, fall back to
    # the most recent weekday that actually has data so PO sees Friday's
    # digest + reports. We keep the request's logical date in the response
    # but pull rows from the fallback date.
    effective_date: date | None = None
    try:
        effective_date = date.fromisoformat(query_date)
    except ValueError:
        effective_date = today

    # Hotfix 54 — broaden the fallback condition. Previously this only
    # fired on weekends AND when ``is_today_request`` was True. But the
    # same "no reports for the requested date" hits whenever the
    # client's UTC clock is ahead of the server's UTC clock (timezone
    # skew right around midnight). For example: user in IST, just past
    # UTC-midnight, browser sends ``date=2026-05-05`` while server's
    # ``date.today()`` is still ``2026-05-04``. ``is_today_request``
    # would be False (the strings don't match) so the old weekend gate
    # never engaged and the digest stayed empty.
    #
    # New rule: trigger fallback whenever the requested date is **today
    # or later from the server's perspective** AND it's either a
    # weekend or strictly future. Past dates are NOT auto-fallback'd —
    # if a user explicitly picks an old date, respect that choice.
    needs_fallback = effective_date is not None and (
        effective_date > today
        or (effective_date == today and is_weekend)
    )
    if needs_fallback:
        latest_q = await db.execute(
            select(func.max(func.date(StandupReport.report_date)))
            .where(StandupReport.organization_id == org_id)
        )
        latest_date = latest_q.scalar()
        if latest_date is not None and latest_date != effective_date:
            logger.info(
                f"[standups] fallback: org={org_id} requested={effective_date} "
                f"server_today={today} weekend={is_weekend} → showing "
                f"data from {latest_date}"
            )
            effective_date = latest_date

    # Get digest for the effective date
    digest_query = (
        select(TeamStandupDigest)
        .where(TeamStandupDigest.organization_id == org_id)
        .order_by(TeamStandupDigest.digest_date.desc())
        .limit(1)
    )
    if effective_date is not None:
        digest_query = digest_query.where(
            func.date(TeamStandupDigest.digest_date) == effective_date
        )
    digest_result = await db.execute(digest_query)
    digest = digest_result.scalar_one_or_none()

    # Fallback: if no digest for the effective date, just take the latest one
    # the org has ever produced (covers cases where a digest row was never
    # written for that exact day).
    if digest is None:
        any_digest_q = await db.execute(
            select(TeamStandupDigest)
            .where(TeamStandupDigest.organization_id == org_id)
            .order_by(TeamStandupDigest.digest_date.desc())
            .limit(1)
        )
        digest = any_digest_q.scalar_one_or_none()

    # Get standup reports with team member info and blocker flags.
    # Hotfix 46: standup is for *developers and engineering managers* —
    # absolutely nobody else. The user has 3 TM rows for "Sangini Tripathi"
    # (developer / PO / stakeholder); previously a denylist filter let
    # PO/stakeholder rows through whenever they had any non-blocked role
    # value. Now it's a strict allowlist so the digest can never surface
    # a non-developer's row.
    DEV_ROLES = ["developer", "engineering_manager"]
    reports_query = (
        select(StandupReport)
        .join(TeamMember, StandupReport.team_member_id == TeamMember.id)
        .where(
            StandupReport.organization_id == org_id,
            TeamMember.role.in_(DEV_ROLES),
        )
        .options(
            selectinload(StandupReport.team_member),
            selectinload(StandupReport.blocker_flags),
        )
        .order_by(StandupReport.report_date.desc())
    )

    # Hotfix 46: strict project-matching when a project is selected — no
    # null-project fallback. Previously the OR-with-NULL clause kept
    # leaking non-project TMs (legacy or PO/stakeholder rows with
    # imported_project_id = NULL) into the project view. The PO has
    # confirmed every developer TM is tied to a real project.
    # Hotfix (revised): the original Hotfix 46 strict TM-level project
    # gate (TeamMember.imported_project_id == project_id) over-filtered.
    # In the wild we've seen TMs whose own `imported_project_id` is NULL
    # owning ALL the recently-closed work items for the selected
    # project (e.g. Sangini's f58e14ac TM has 20 DONE items in project
    # 2328 but its TM row's imported_project_id is NULL). Strict
    # gating drops them entirely → PO sees "0 done" for a dev who
    # actually shipped 20 tickets.
    #
    # The item-level filter further down (project_ticket_ids) already
    # scopes each report's completed/in_progress lists to the selected
    # project's tickets. Combined with drop_empty=True in
    # `_build_individual_reports`, that pair drops a TM from the
    # response when none of its items belong to this project. So the
    # TM-level gate is redundant — and harmful when the TM's own
    # imported_project_id is NULL.
    #
    # We therefore drop the TM-level project filter and rely on:
    #   (a) DEV_ROLES allowlist (already above) — keeps PO/stakeholder
    #       rows out
    #   (b) item-level project_ticket_ids filter — keeps the response
    #       scoped to the selected project's work
    #   (c) drop_empty in the response builder — drops TMs with no
    #       project-relevant items

    # Filter by effective date (may differ from requested date on weekends).
    if effective_date is not None:
        reports_query = reports_query.where(
            func.date(StandupReport.report_date) == effective_date
        )

    reports_query = reports_query.limit(50)
    reports_result = await db.execute(reports_query)
    reports = reports_result.scalars().all()

    # Dedupe by email — Hotfix 43 narrows scope: with project_id given we've
    # already restricted to project-matched TMs, so dedupe just collapses
    # any remaining duplicates (e.g. project + null-project rows).
    reports = _dedupe_reports_by_email(reports, project_id)

    # ── Project-scoped filtering ──
    # If projectId is provided, load that project's work-item ticket IDs and
    # filter each report's completed / in_progress / blockers to only include
    # items belonging to the selected project. Hotfix 42b also drops legacy
    # in_progress entries whose duplicate sibling already lives in the
    # terminal-status set — same root cause as the curated view.
    project_ticket_ids: set[str] | None = None
    project_terminal_ext_ids: set[str] = set()
    project_terminal_titles: set[str] = set()
    ticket_title_by_ext_id: dict[str, str] = {}
    if project_id:
        from ..services._planning_status import TERMINAL_STATUSES

        rows = (await db.execute(
            select(WorkItem.external_id, WorkItem.title, WorkItem.status).where(
                WorkItem.imported_project_id == project_id,
            )
        )).all()
        project_ticket_ids = {r[0] for r in rows if r[0]}
        for ext_id, title, status in rows:
            if ext_id and title and ext_id not in ticket_title_by_ext_id:
                ticket_title_by_ext_id[ext_id] = title
            if (status or "").upper() in TERMINAL_STATUSES:
                if ext_id:
                    project_terminal_ext_ids.add(ext_id)
                if title:
                    project_terminal_titles.add(title.strip().lower())
    else:
        # No project filter — fall back to org-scoped lookup so blocker text
        # still gets enriched with ticket titles in the all-projects view.
        rows = (await db.execute(
            select(WorkItem.external_id, WorkItem.title).where(
                WorkItem.organization_id == org_id,
            )
        )).all()
        for ext_id, title in rows:
            if ext_id and title and ext_id not in ticket_title_by_ext_id:
                ticket_title_by_ext_id[ext_id] = title

    def _is_already_done(item: dict) -> bool:
        """True if any duplicate sibling of this item is terminal in the project."""
        if not isinstance(item, dict):
            return False
        if item.get("ticketId") and item["ticketId"] in project_terminal_ext_ids:
            return True
        title = (item.get("title") or "").strip().lower()
        if title and title in project_terminal_titles:
            return True
        return False

    if project_ticket_ids is not None:
        for r in reports:
            if isinstance(r.completed_items, list):
                r.completed_items = [
                    item for item in r.completed_items
                    if isinstance(item, dict) and item.get("ticketId") in project_ticket_ids
                ]
            if isinstance(r.in_progress_items, list):
                r.in_progress_items = [
                    item for item in r.in_progress_items
                    if isinstance(item, dict)
                    and item.get("ticketId") in project_ticket_ids
                    and not _is_already_done(item)
                ]
            # Blockers may or may not have ticketIds — keep those that match or have no ticketId
            if isinstance(r.blockers, list):
                r.blockers = [
                    b for b in r.blockers
                    if (isinstance(b, dict) and (not b.get("ticketId") or b.get("ticketId") in project_ticket_ids))
                    or isinstance(b, str)
                ]

    # Hotfix 41: compute curated views (recentActivity + inFlight) for each
    # surviving report. Failures here should never block the digest — fall
    # back to empty curated buckets so the legacy capped lists still render.
    curated: dict[str, dict] = {}
    try:
        curated = await _compute_curated_views(db, reports, org_id, project_id)
    except Exception as e:
        logger.warning(f"[standups] _compute_curated_views failed: {e}")

    # Hotfix 43: build notes-by-email so empty-row dropper still surfaces a
    # developer who submitted a note even if their tracked activity is dry.
    notes_by_email: dict[str, list] = {}
    for r in reports:
        if r.developer_note and r.team_member and r.team_member.email:
            notes_by_email.setdefault(r.team_member.email.lower(), []).append(r)

    individual_reports = _build_individual_reports(
        reports, curated, notes_by_email,
        ticket_title_by_ext_id=ticket_title_by_ext_id,
    )

    # Resolve a "mine" pointer — the requesting user's own report.
    #
    # Real-world data: a single human (e.g. "Sangini Tripathi") often
    # has multiple TeamMember rows in the same organization because:
    #   • Different OAuth accounts (work email vs personal email)
    #   • Manual imports + ADO sync mapping by display_name
    #   • Excluded duplicates that never got cleaned up
    #
    # When work items get credited to one TM but the user logs in
    # under another email, a single-TM "mine" resolver lands on the
    # WRONG TM (the one without the work). The user sees an empty
    # standup even though they shipped 20 tickets, because all 20 are
    # under the *other* TM with the same name.
    #
    # New behaviour: collect EVERY TM-keyed report whose email or
    # displayName matches the requesting user, then merge them into a
    # single aggregated report. Dedupe items by ticketId so the same
    # work item appearing under multiple TMs (legitimate or stale)
    # only counts once.
    #
    # We aggregate the full StandupReport rows (not the post-build
    # ones), so drop_empty doesn't filter out a TM whose tracked
    # activity is empty individually but contributes to the merged
    # total.
    me_email = (current_user.get("email") or "").lower()
    me_name = ((current_user.get("full_name") or "")).strip().lower()
    mine_report: dict | None = None

    # Query directly against StandupReport — DO NOT use the
    # project-filtered `reports` list. That list applies a strict
    # `TeamMember.imported_project_id == project_id` filter, which
    # excludes TMs whose `imported_project_id` is NULL even when they
    # have work items in the project. We've verified at least one user
    # in the wild ("Sangini Tripathi") whose primary developer TM
    # f58e14ac has imported_project_id=NULL despite owning all the
    # project's recently-closed work items. The project filter on
    # `completed_items` further down (project_ticket_ids) is already
    # responsible for keeping items scoped — running TM-level project
    # gating on top of it just hides the user's own work from them.
    matching_reports: list = []
    if effective_date is not None:
        from sqlalchemy.orm import selectinload as _selectinload
        mine_q = (
            select(StandupReport)
            .join(TeamMember, StandupReport.team_member_id == TeamMember.id)
            .where(
                StandupReport.organization_id == org_id,
                func.date(StandupReport.report_date) == effective_date,
            )
            .options(
                _selectinload(StandupReport.team_member),
                _selectinload(StandupReport.blocker_flags),
            )
        )
        mine_rows = (await db.execute(mine_q)).scalars().all()
        for r in mine_rows:
            if not r.team_member:
                continue
            tm_email = (r.team_member.email or "").lower()
            tm_name = (r.team_member.display_name or "").strip().lower()
            if (me_email and tm_email == me_email) or (me_name and tm_name == me_name):
                matching_reports.append(r)

        # Apply the same item-level project filter we apply to the
        # main reports list, so the merged "mine" only counts work
        # belonging to the selected project.
        if project_ticket_ids is not None:
            for r in matching_reports:
                if isinstance(r.completed_items, list):
                    r.completed_items = [
                        it for it in r.completed_items
                        if isinstance(it, dict) and it.get("ticketId") in project_ticket_ids
                    ]
                if isinstance(r.in_progress_items, list):
                    r.in_progress_items = [
                        it for it in r.in_progress_items
                        if isinstance(it, dict)
                        and it.get("ticketId") in project_ticket_ids
                        and not _is_already_done(it)
                    ]

    if matching_reports:
        # Build per-TM views with drop_empty=False so empty TMs still
        # contribute (their inFlight / recentActivity may be present).
        per_tm = _build_individual_reports(
            matching_reports, curated, notes_by_email,
            drop_empty=False,
            ticket_title_by_ext_id=ticket_title_by_ext_id,
        )
        if per_tm:
            # Use the first TM as the structural base, then merge.
            base = dict(per_tm[0])
            seen_completed_keys: set[str] = set()
            seen_inprog_keys: set[str] = set()
            seen_blocker_keys: set[str] = set()
            seen_recent_keys: set[str] = set()
            seen_inflight_keys: set[str] = set()

            base["completed"] = []
            base["inProgress"] = []
            base["blockers"] = []
            base["recentActivity"] = []
            base["inFlight"] = []

            def _key_of(item: dict) -> str:
                return (item.get("ticketId") or item.get("id")
                        or (item.get("title") or "").strip().lower())

            total_completed = 0
            total_in_progress = 0
            total_blockers = 0
            for v in per_tm:
                for it in (v.get("completed") or []):
                    k = _key_of(it)
                    if k and k not in seen_completed_keys:
                        seen_completed_keys.add(k)
                        base["completed"].append(it)
                for it in (v.get("inProgress") or []):
                    k = _key_of(it)
                    if k and k not in seen_inprog_keys:
                        seen_inprog_keys.add(k)
                        base["inProgress"].append(it)
                for it in (v.get("blockers") or []):
                    k = _key_of(it)
                    if k and k not in seen_blocker_keys:
                        seen_blocker_keys.add(k)
                        base["blockers"].append(it)
                for it in (v.get("recentActivity") or []):
                    k = (it.get("url") or "") + "|" + (it.get("title") or "")
                    if k and k not in seen_recent_keys:
                        seen_recent_keys.add(k)
                        base["recentActivity"].append(it)
                for it in (v.get("inFlight") or []):
                    k = _key_of(it)
                    if k and k not in seen_inflight_keys:
                        seen_inflight_keys.add(k)
                        base["inFlight"].append(it)
                total_completed += int(v.get("completedCount") or 0)
                total_in_progress += int(v.get("inProgressCount") or 0)
                total_blockers += int(v.get("blockerCount") or 0)

            # Use the requesting user's auth email so the frontend's
            # legacy email-string check (older web revisions) still
            # finds the row.
            if me_email:
                base["email"] = me_email
            base["completedCount"] = len(base["completed"])
            base["inProgressCount"] = len(base["inProgress"])
            base["blockerCount"] = len(base["blockers"])

            # Rebuild the narrative on top of the merged list.
            disp = base.get("displayName") or current_user.get("full_name") or "You"
            narr_parts: list[str] = []
            if base["completed"]:
                titles = ", ".join((c.get("title") or "")[:40] for c in base["completed"][:3])
                suffix = f" and {len(base['completed']) - 3} more" if len(base["completed"]) > 3 else ""
                narr_parts.append(f"{disp} recently completed {titles}{suffix}.")
            else:
                narr_parts.append(f"{disp} has no recently completed items.")
            if base["inProgress"]:
                titles = ", ".join((ip.get("title") or "")[:40] for ip in base["inProgress"][:3])
                suffix = f" and {len(base['inProgress']) - 3} more" if len(base["inProgress"]) > 3 else ""
                narr_parts.append(f"Currently working on {titles}{suffix}.")
            if base["blockers"]:
                narr_parts.append(
                    f"⚠ {len(base['blockers'])} blocker{'s' if len(base['blockers']) > 1 else ''} reported."
                )
            base["narrativeText"] = " ".join(narr_parts)

            # isInactive: only if every bucket is empty.
            base["isInactive"] = not (
                base["completed"] or base["inProgress"]
                or base["blockers"] or base["recentActivity"]
                or base["inFlight"]
            )
            mine_report = base

    submitted_notes = _build_submitted_notes(
        reports,
        query_date,
        current_user_email=(current_user.get("email") or "").lower(),
        current_user_name=current_user.get("full_name") or "",
    )

    # If the effective date differs from the requested date (weekend
    # fallback), surface that to the frontend so it can render a "Showing
    # data from <date>" hint instead of pretending today has data.
    effective_iso = (
        effective_date.isoformat() if effective_date is not None else query_date
    )
    is_fallback = effective_iso != query_date

    # ── Hotfix 44: project-scoped header stats ──────────────────────────
    # The TeamStandupDigest row is org-wide (one per org per day), so its
    # sprint_pacing / acknowledged_pct / blocker_count / summary_text
    # numbers don't react to the project selector. When a project is
    # picked, recompute everything from the *displayed* reports + that
    # project's active iteration.
    sprint_pacing = digest.sprint_pacing if digest else 0
    acknowledged_pct = digest.acknowledged_pct if digest else 0
    sprint_health = digest.sprint_health if digest else "GREEN"
    blocker_count = digest.blocker_count if digest else 0
    summary_text = (
        digest.summary_text if digest
        else "No standup data yet. Sync project data to auto-generate standups."
    )

    if project_id:
        # Acknowledged % from the visible (filtered + dedupe'd) reports.
        total_ir = len(individual_reports)
        ack = sum(1 for ir in individual_reports if ir.get("acknowledged"))
        acknowledged_pct = int((ack / total_ir) * 100) if total_ir else 0

        # Blocker count = sum across visible reports (already project-filtered).
        blocker_count = sum(int(ir.get("blockerCount") or 0) for ir in individual_reports)

        # Sprint pacing: derive from this project's iteration the same way
        # generate_team_digest does, but scoped to this project's work
        # items only.
        from ..models.iteration import Iteration as _Iteration
        iter_q = await db.execute(
            select(_Iteration)
            .where(
                _Iteration.organization_id == org_id,
                _Iteration.state == "active",
            )
            .order_by(_Iteration.start_date.desc())
            .limit(1)
        )
        active_iter = iter_q.scalar_one_or_none()

        # Reuse the work-item rows we already fetched for the terminal-key
        # scan above (`rows` is in scope because we're inside the same
        # `if project_id:` ladder).
        from ..services._planning_status import TERMINAL_STATUSES as _TERMINAL_STATUSES
        proj_total_count = 0
        proj_done_count = 0
        for ext_id, title, status in rows:  # noqa: F821 — defined in earlier project-scoped block
            proj_total_count += 1
            if (status or "").upper() in _TERMINAL_STATUSES:
                proj_done_count += 1

        if proj_total_count == 0:
            sprint_pacing = 0
        else:
            work_pct = proj_done_count / proj_total_count
            if active_iter and active_iter.start_date and active_iter.end_date:
                total_days = max(1, (active_iter.end_date - active_iter.start_date).days)
                elapsed = max(0, (datetime.now(timezone.utc) - active_iter.start_date).days)
                time_pct = min(elapsed / total_days, 1.0)
                sprint_pacing = int((work_pct / max(time_pct, 0.01)) * 100)
                sprint_pacing = min(sprint_pacing, 120)
            else:
                sprint_pacing = int(work_pct * 100)

        # Health from project-scoped pacing.
        if sprint_pacing >= 80 and blocker_count == 0:
            sprint_health = "GREEN"
        elif sprint_pacing >= 50 or blocker_count <= 1:
            sprint_health = "AMBER"
        else:
            sprint_health = "RED"

        # Project-scoped summary string.
        total_completed = sum(int(ir.get("completedCount") or 0) for ir in individual_reports)
        total_in_progress = sum(int(ir.get("inProgressCount") or 0) for ir in individual_reports)
        parts = [f"Team completed {total_completed} items and has {total_in_progress} in progress."]
        if blocker_count:
            parts.append(
                f"{blocker_count} blocker{'s' if blocker_count != 1 else ''} require attention."
            )
        if sprint_pacing:
            parts.append(f"Sprint pacing is at {sprint_pacing}%.")
        summary_text = " ".join(parts)

    # Build the full response matching the Next.js format
    response = {
        "id": digest.id if digest else "digest-0",
        "organizationId": org_id,
        "iterationId": digest.iteration_id if digest else None,
        "digestDate": query_date,
        "effectiveDate": effective_iso,
        "isWeekendFallback": is_fallback,
        "sprintPacing": sprint_pacing,
        "acknowledgedPct": acknowledged_pct,
        "sprintHealth": sprint_health,
        "blockerCount": blocker_count,
        "summaryText": summary_text,
        "atRiskItems": digest.at_risk_items if digest else {"items": []},
        "individualReports": individual_reports,
        # Resolved pointer to the requesting user's own report. Email
        # match first, then displayName fallback. Always present (may
        # be null) so the dev's UI can render their own row directly
        # without doing the fragile email-string match itself.
        "mine": mine_report,
        "submittedNotes": submitted_notes,
        # Backward compat
        "date": query_date,
        "digest": {
            "sprintPacing": sprint_pacing,
            "acknowledgedPct": acknowledged_pct,
            "sprintHealth": sprint_health,
            "blockerCount": blocker_count,
            "summaryText": summary_text,
        },
        "reports": individual_reports,
    }

    return response


# ---------------------------------------------------------------------------
# GET /api/standups/{report_id}/sprint-contributions — full lists on demand
# Hotfix 41: lazy-loaded for the "View full sprint contributions" expander
# so the default digest stays compact.
# ---------------------------------------------------------------------------

@router.get("/standups/{report_id}/sprint-contributions")
async def get_sprint_contributions(
    report_id: str,
    project_id: str | None = Query(None, alias="projectId"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full (uncapped) completed_items + in_progress_items for one
    StandupReport so the PO can pull up the sprint-wide picture for a single
    developer without bloating the default digest payload.

    Merge across same-human TMs: if the requested SR's TM has same-named
    sibling TMs in the org (different emails, same display_name — common
    when a developer signed up under one email but ADO sync created a
    second TM under another), merge all of their reports for the same
    date so the PO sees the human's complete contribution. Without this,
    the digest endpoint's merged narrative (e.g. "20 done") and this
    endpoint's expanded list disagree on item counts because the
    expander only reads the rep TM's row directly from DB.
    """
    org_id = current_user.get("organization_id", "demo-org")

    q = await db.execute(
        select(StandupReport)
        .where(
            StandupReport.id == report_id,
            StandupReport.organization_id == org_id,
        )
        .options(selectinload(StandupReport.team_member))
    )
    r = q.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Standup report not found")

    # Find sibling TMs (same display_name in same org) and pull their
    # SRs for the same date. The merge here mirrors the digest's
    # `_dedupe_reports_by_email` merge.
    rep_name = (
        r.team_member.display_name if r.team_member and r.team_member.display_name
        else ""
    ).strip().lower()
    sibling_reports: list = [r]
    if rep_name and r.report_date:
        from datetime import date as _date
        rep_date = (
            r.report_date.date() if hasattr(r.report_date, "date") else r.report_date
        )
        sib_q = (
            select(StandupReport)
            .join(TeamMember, StandupReport.team_member_id == TeamMember.id)
            .where(
                StandupReport.organization_id == org_id,
                StandupReport.id != r.id,
                func.lower(func.trim(TeamMember.display_name)) == rep_name,
                func.date(StandupReport.report_date) == rep_date,
            )
            .options(selectinload(StandupReport.team_member))
        )
        sib_rows = (await db.execute(sib_q)).scalars().all()
        sibling_reports.extend(sib_rows)

    # Project-scope filtering — load tickets once, reuse across TMs.
    ticket_ids: set[str] | None = None
    if project_id:
        wi_q = await db.execute(
            select(WorkItem.external_id).where(
                WorkItem.imported_project_id == project_id,
            )
        )
        ticket_ids = {row[0] for row in wi_q.all() if row[0]}

    def _key_of(item) -> str:
        if not isinstance(item, dict):
            return str(item)
        return (
            item.get("ticketId")
            or item.get("id")
            or (item.get("title") or "").strip().lower()
        )

    seen_completed: set[str] = set()
    seen_inprog: set[str] = set()
    completed: list = []
    in_progress: list = []
    for sr in sibling_reports:
        for it in (sr.completed_items if isinstance(sr.completed_items, list) else []):
            if not isinstance(it, dict):
                continue
            if ticket_ids is not None and it.get("ticketId") not in ticket_ids:
                continue
            k = _key_of(it)
            if k and k not in seen_completed:
                seen_completed.add(k)
                completed.append(it)
        for it in (sr.in_progress_items if isinstance(sr.in_progress_items, list) else []):
            if not isinstance(it, dict):
                continue
            if ticket_ids is not None and it.get("ticketId") not in ticket_ids:
                continue
            k = _key_of(it)
            if k and k not in seen_inprog:
                seen_inprog.add(k)
                in_progress.append(it)

    return {
        "reportId": r.id,
        "displayName": r.team_member.display_name if r.team_member else "Unknown",
        "completed": completed,
        "inProgress": in_progress,
        "completedCount": len(completed),
        "inProgressCount": len(in_progress),
    }


# ---------------------------------------------------------------------------
# POST /api/standups/generate — Trigger standup generation
# ---------------------------------------------------------------------------

@router.post("/standups/generate")
async def trigger_standup_generation(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger standup report generation from synced data."""
    org_id = current_user.get("organization_id", "demo-org")

    from ..services.standup_generator import generate_all_standups
    result = await generate_all_standups(db, org_id)

    # Broadcast standup generation event
    await ws_manager.broadcast(org_id, {
        "type": "standup_generated",
        "data": {
            "reportsGenerated": result.get("reports_generated", 0),
            "date": date.today().isoformat(),
        },
    })

    return {
        "ok": True,
        **result,
    }


# ---------------------------------------------------------------------------
# POST /api/standups — Submit a standup note
# ---------------------------------------------------------------------------

@router.post("/standups")
async def submit_standup_note(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    if today.weekday() in (5, 6):
        raise HTTPException(
            status_code=400,
            detail="Standup notes cannot be submitted on weekends",
        )

    note = body.get("note", "").strip()
    # Author name: prefer what the frontend sends, then JWT full_name
    author = body.get("author") or current_user.get("full_name") or "Unknown"
    author_role = body.get("authorRole") or current_user.get("role") or "developer"

    if not note:
        raise HTTPException(status_code=400, detail="Note cannot be empty")

    # Find team member for the current user (match by email, not just org)
    org_id = current_user.get("organization_id", "demo-org")
    user_email = (current_user.get("email") or "").lower()
    member_query = (
        select(TeamMember)
        .where(
            TeamMember.organization_id == org_id,
            TeamMember.email.ilike(user_email),
        )
        .limit(1)
    )
    member_result = await db.execute(member_query)
    member = member_result.scalar_one_or_none()

    # Hotfix 51 (CRIT-3) — REMOVED the "first TM in org" fallback. The
    # old code grabbed an arbitrary TeamMember when the caller's email
    # didn't match any row, silently attributing the note to a stranger.
    # If there's no email-matched TM, the caller has no business
    # submitting a standup note — return 403 instead.
    if not member:
        raise HTTPException(
            status_code=403,
            detail=(
                "No TeamMember row matches your email. Ask your PO to "
                "add you to the project before submitting standup notes."
            ),
        )

    if member:
        # Check for existing report today — append note to it
        existing_q = await db.execute(
            select(StandupReport).where(
                StandupReport.organization_id == org_id,
                StandupReport.team_member_id == member.id,
                func.date(StandupReport.report_date) == today,
            )
        )
        report = existing_q.scalar_one_or_none()

        if report:
            # Append note to existing report
            if report.developer_note:
                report.developer_note = f"{report.developer_note}\n---\n{note}"
            else:
                report.developer_note = note
            await db.commit()
            await db.refresh(report)
        else:
            report = StandupReport(
                organization_id=org_id,
                team_member_id=member.id,
                report_date=datetime.now(timezone.utc),
                completed_items=[],
                in_progress_items=[note],
                blockers=[],
                narrative_text=note,
                acknowledged=False,
                developer_note=note,
            )
            db.add(report)
            await db.commit()
            await db.refresh(report)

        # Notify PO and broadcast WebSocket event
        try:
            await ws_manager.broadcast(org_id, {
                "type": "standup_note_submitted",
                "data": {"author": author, "date": today.isoformat()},
            })
        except Exception:
            pass

        try:
            from ..services.delivery_queue import enqueue_notification
            from ..services import card_builders
            from .notifications import get_po_email

            po_email = await get_po_email(db, org_id)
            if po_email:
                await enqueue_notification(
                    org_id=org_id,
                    recipient_email=po_email,
                    notification_type="standup_report",
                    in_app_payload={
                        "title": "Standup Note Submitted",
                        "body": f"{author} submitted a standup note",
                        "type": "standup_report",
                    },
                )
        except Exception as e:
            logger.warning(f"Standup notification failed: {e}")

        return {
            "success": True,
            "entry": {
                "id": report.id,
                "note": note,
                "author": author,
                "authorRole": author_role,
                "date": today.isoformat(),
                "submittedAt": report.created_at.isoformat() if report.created_at else datetime.now(timezone.utc).isoformat(),
            },
        }

    return {
        "success": True,
        "entry": {
            "id": f"note-{int(datetime.now(timezone.utc).timestamp())}",
            "note": note,
            "author": author,
            "authorRole": author_role,
            "date": today.isoformat(),
            "submittedAt": datetime.now(timezone.utc).isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# POST /api/standups/blocker — Flag a blocker
# ---------------------------------------------------------------------------

@router.post("/standups/blocker")
async def flag_blocker(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /api/standups/blocker
    Flag a new blocker. Creates a BlockerFlag and notifies the PO via Slack/Teams.
    """
    org_id = current_user.get("organization_id", "demo-org")
    description = body.get("description", "").strip()
    ticket_ref = body.get("ticketReference", "")
    ticket_title = body.get("ticketTitle", "")
    report_id = body.get("reportId")

    if not description:
        raise HTTPException(status_code=400, detail="Blocker description is required")

    # Hotfix 51 (CRIT-4 pt 1) — match the developer by email instead of
    # picking the first TM in the org. Otherwise blockers get attributed
    # to whichever TM happens to sort first.
    user_email = (current_user.get("email") or "").strip().lower()
    member = None
    if user_email:
        member_q = await db.execute(
            select(TeamMember).where(
                TeamMember.organization_id == org_id,
                TeamMember.email.ilike(user_email),
            ).limit(1)
        )
        member = member_q.scalar_one_or_none()
    dev_name = member.display_name if member else current_user.get("full_name", "A developer")

    # Hotfix 51 (CRIT-4 pt 2) — if a reportId is supplied, verify that
    # report belongs to the caller's org (and to their own TeamMember
    # when one is resolvable). The previous code used reportId from the
    # body verbatim, letting any caller attach a blocker to ANY org's
    # standup report by guessing its id.
    if report_id:
        report_q = await db.execute(
            select(StandupReport).where(
                StandupReport.id == report_id,
                StandupReport.organization_id == org_id,
            )
        )
        report_row = report_q.scalar_one_or_none()
        if not report_row:
            raise HTTPException(
                status_code=404,
                detail="Standup report not found in your organization",
            )
        if member and report_row.team_member_id != member.id:
            raise HTTPException(
                status_code=403,
                detail="Cannot flag a blocker on another developer's standup",
            )

    # If no report_id provided, find or create a standup report for today
    if not report_id and member:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
        existing_report = await db.execute(
            select(StandupReport).where(
                StandupReport.organization_id == org_id,
                StandupReport.team_member_id == member.id,
                StandupReport.report_date >= today_start,
            ).limit(1)
        )
        report = existing_report.scalar_one_or_none()
        if report:
            report_id = report.id
        else:
            new_report = StandupReport(
                organization_id=org_id,
                team_member_id=member.id,
                report_date=datetime.now(timezone.utc),
                completed_items=[],
                in_progress_items=[],
                blockers=[description],
                narrative_text=f"Blocker flagged: {description}",
                acknowledged=False,
            )
            db.add(new_report)
            await db.flush()
            report_id = new_report.id

    if not report_id:
        raise HTTPException(status_code=400, detail="Cannot create blocker without a standup report context")

    # Create the blocker flag
    blocker = BlockerFlag(
        standup_report_id=report_id,
        description=description,
        ticket_reference=ticket_ref or None,
        status="OPEN",
    )
    db.add(blocker)
    await db.commit()
    await db.refresh(blocker)

    # ── Notification trigger: notify PO ──
    try:
        from ..services.delivery_queue import enqueue_notification
        from ..services import card_builders
        from .notifications import get_po_email

        po_email = await get_po_email(db, org_id)
        if po_email:
            await enqueue_notification(
                org_id=org_id,
                recipient_email=po_email,
                notification_type="blocker_alert",
                slack_payload=card_builders.slack_blocker_alert(
                    dev_name=dev_name,
                    ticket_key=ticket_ref or "N/A",
                    ticket_title=ticket_title or description[:50],
                    blocker_description=description,
                    days_blocked=0,
                    blocker_id=blocker.id,
                    org_id=org_id,
                ),
                teams_payload=card_builders.teams_blocker_alert(
                    dev_name=dev_name,
                    ticket_key=ticket_ref or "N/A",
                    ticket_title=ticket_title or description[:50],
                    blocker_description=description,
                    days_blocked=0,
                ),
            )
            logger.info(f"Queued blocker_alert notification -> {po_email}")
    except Exception as e:
        logger.warning(f"Notification trigger error: {e}")

    return {
        "success": True,
        "blocker": {
            "id": blocker.id,
            "description": description,
            "ticketReference": ticket_ref,
            "status": "OPEN",
            "flaggedAt": blocker.flagged_at.isoformat() if blocker.flagged_at else None,
        },
    }


# ---------------------------------------------------------------------------
# PATCH /api/standups — Get notes by date
# ---------------------------------------------------------------------------

@router.patch("/standups")
async def get_notes_by_date(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List standup notes for a date.

    Hotfix 56 (MED-1) — was returning every developer's private notes to
    any caller in the org. Now: PO/admin/owner see all org notes, anyone
    else sees only their own notes (filtered by email match).
    """
    org_id = current_user.get("organization_id", "demo-org")
    query_date = body.get("date", date.today().isoformat())
    role = (current_user.get("role") or "").lower()
    user_email = (current_user.get("email") or "").strip().lower()

    reports_query = (
        select(StandupReport)
        .join(TeamMember, StandupReport.team_member_id == TeamMember.id)
        .where(StandupReport.organization_id == org_id)
        .options(selectinload(StandupReport.team_member))
        .order_by(StandupReport.report_date.desc())
    )

    # If the caller is not PO/admin/owner, restrict to their own TM rows
    # by email. Stakeholders / developers / EMs only see THEIR notes.
    if role not in ("product_owner", "admin", "owner"):
        if not user_email:
            return {"date": query_date, "notes": []}
        reports_query = reports_query.where(
            func.lower(TeamMember.email) == user_email
        )

    # Filter by date
    try:
        filter_date = date.fromisoformat(query_date)
        reports_query = reports_query.where(
            func.date(StandupReport.report_date) == filter_date
        )
    except ValueError:
        pass

    reports_result = await db.execute(reports_query)
    reports = reports_result.scalars().all()

    notes = []
    for r in reports:
        if r.developer_note:
            notes.append({
                "id": r.id,
                "note": r.developer_note,
                "author": r.team_member.display_name if r.team_member else "Unknown",
                "authorRole": "developer",
                "date": r.report_date.date().isoformat() if r.report_date else query_date,
                "submittedAt": r.created_at.isoformat() if r.created_at else None,
            })

    return {"date": query_date, "notes": notes}


# ---------------------------------------------------------------------------
# GET /api/blockers/my — Recent blockers raised by the logged-in developer
# ---------------------------------------------------------------------------

@router.get("/blockers/my")
async def list_my_blockers(
    project_id: str | None = Query(None, alias="projectId"),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current developer's recent blockers with their live status.

    Powers the "Blocker History" list under the dev's Update About Your Blockers
    form. Status is one of OPEN / ACKNOWLEDGED / ESCALATED / RESOLVED.
    """
    org_id = current_user.get("organization_id", "demo-org")
    user_email = (current_user.get("email") or "").lower()

    # Find all TeamMember rows for this user in this org (they may have multiple — one per project)
    tm_q = await db.execute(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
            TeamMember.email.ilike(user_email),
        )
    )
    team_members = list(tm_q.scalars().all())
    if not team_members:
        return {"blockers": []}

    tm_ids = [tm.id for tm in team_members]

    # Join BlockerFlag → StandupReport to filter by team_member_id
    blockers_q = (
        select(BlockerFlag, StandupReport)
        .join(StandupReport, BlockerFlag.standup_report_id == StandupReport.id)
        .where(StandupReport.team_member_id.in_(tm_ids))
        .order_by(BlockerFlag.flagged_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(blockers_q)).all()

    # Optional project filter — include blockers from team_members that either
    # belong to the given project OR have no project assignment (self-created
    # team_members from blocker-flag path).
    project_tm_ids: set[str] | None = None
    if project_id:
        project_tm_ids = {
            tm.id for tm in team_members
            if tm.imported_project_id == project_id or tm.imported_project_id is None
        }

    blockers = []
    for b, r in rows:
        if project_tm_ids is not None and r.team_member_id not in project_tm_ids:
            continue
        blockers.append({
            "id": b.id,
            "ticket": b.ticket_reference or "",
            "description": b.description or "",
            "status": (b.status or "OPEN").upper(),
            "flaggedAt": b.flagged_at.isoformat() if b.flagged_at else None,
            "resolvedAt": b.resolved_at.isoformat() if b.resolved_at else None,
        })

    return {"blockers": blockers}

"""
Standup Generator — builds standup reports from real synced data.

For each team member it queries:
  - Work items recently moved to DONE  → "completed"
  - Work items currently IN_PROGRESS   → "in progress"
  - PRs opened / merged / in review    → added to completed or in-progress
  - Commits since last standup          → context for narrative
  - Open BlockerFlags                   → "blockers"

Then generates a narrative summary and upserts StandupReport + TeamStandupDigest.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta, date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, case, or_

from ..models.standup import StandupReport, TeamStandupDigest, BlockerFlag
from ..models.work_item import WorkItem
from ..models.team_member import TeamMember
from ..models.iteration import Iteration
from ..models.repository import PullRequest, Commit

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _since_cutoff(last_report_date: datetime | None) -> datetime:
    """Determine the cutoff time for 'recent' activity.

    Returns 72 hours ago — a rolling three-day window.

    Rationale (per product owner):
      A daily standup is fundamentally a *daily* signal. The 72h window
      is wide enough to:
        • Catch today's closes (mid-day standup sees morning work)
        • Span weekends (Monday's standup still shows Friday's work)
        • Absorb minor batching (the dev who closed 8 tickets last
          night)
      …and narrow enough to keep the dashboard meaningful: items older
      than three days belong to the sprint history / retrospective view,
      not the daily standup.

    Earlier iterations tried tighter or looser windows:
      A. `return last_report_date` (delta-since-last-regen) — combined
         with the upsert path overwriting ``completed_items``, regens
         after the morning auto-gen wiped out the morning's items.
      B. Start of today UTC — items closed yesterday dropped the moment
         UTC midnight rolled over.
      C. 7 days — too wide; surfaced stale work and pretended
         long-quiet developers had recent activity.

    72h is the chosen middle. Adjust here if needed; the curated view
    in routers/standups.py must match.
    """
    return datetime.now(timezone.utc) - timedelta(hours=72)


def _build_narrative(
    member_name: str,
    completed: list[dict],
    in_progress: list[dict],
    blockers: list[dict],
    pr_activity: list[dict],
    commit_count: int,
) -> str:
    """Build a readable narrative text from structured standup data."""
    parts: list[str] = []

    # Opening — "recently" rather than "newly" because the cutoff is
    # a rolling 72h window (Mon morning still surfaces Friday's work).
    #
    # SKIP ``isCommitSummary`` entries when picking titles for the
    # joined sentence: their ``title`` field IS the AI-written summary
    # paragraph (which already starts with the dev's name), so
    # including it produces things like:
    #   "Sangini Tripathi recently completed Sangini Tripathi fixed
    #    multiple standup, Sangini Tripathi fixed multiple standups,
    #    Sangini Tripathi fixed multiple standups."
    # The AI summary already has its own dedicated UI block; it
    # doesn't belong in this single-line preamble.
    narrative_completed = [
        c for c in completed
        if isinstance(c, dict) and not c.get("isCommitSummary")
    ]
    if narrative_completed:
        titles = ", ".join((c.get("title") or "")[:40] for c in narrative_completed[:3])
        suffix = f" and {len(narrative_completed) - 3} more" if len(narrative_completed) > 3 else ""
        parts.append(f"{member_name} recently completed {titles}{suffix}.")
    else:
        parts.append(f"{member_name} has no recently completed items.")

    # In progress
    if in_progress:
        titles = ", ".join(ip["title"][:40] for ip in in_progress[:3])
        suffix = f" and {len(in_progress) - 3} more" if len(in_progress) > 3 else ""
        parts.append(f"Currently working on {titles}{suffix}.")

    # PR activity
    if pr_activity:
        open_prs = [p for p in pr_activity if p.get("status") == "OPEN"]
        merged_prs = [p for p in pr_activity if p.get("status") == "MERGED"]
        if merged_prs:
            parts.append(f"{len(merged_prs)} PR{'s' if len(merged_prs) > 1 else ''} merged.")
        if open_prs:
            parts.append(f"{len(open_prs)} open PR{'s' if len(open_prs) > 1 else ''} awaiting review.")

    # Commits
    if commit_count > 0:
        parts.append(f"{commit_count} commit{'s' if commit_count > 1 else ''} pushed.")

    # Blockers
    if blockers:
        parts.append(f"⚠ {len(blockers)} blocker{'s' if len(blockers) > 1 else ''} reported.")

    return " ".join(parts)


def _to_standup_item(
    title: str,
    ticket_id: str | None = None,
    pr_id: str | None = None,
    pr_status: str | None = None,
    commit_sha: str | None = None,
) -> dict:
    """Build a StandupReportItem-shaped dict."""
    item: dict[str, Any] = {"title": title}
    if ticket_id:
        item["ticketId"] = ticket_id
    if pr_id:
        item["prId"] = pr_id
    if pr_status:
        item["prStatus"] = pr_status
    if commit_sha:
        item["commitSha"] = commit_sha
    return item


# Commit-message noise filter — skip these when promoting commits to
# standup items. They don't carry meaningful work signal and would
# clutter the dashboard if every "wip" / "fix typo" became a row.
_NOISE_COMMIT_PATTERNS = (
    "wip",
    "fix typo",
    "fix typos",
    "typo",
    "small fix",
    "lint",
    "format",
    "prettier",
    "ci:",
    "chore:",
    "merge branch",
    "merge pull request",
    "revert",
)


def _is_noise_commit(message: str) -> bool:
    """Return True if the first line of the commit message looks like
    pure noise that shouldn't surface as a completed standup item."""
    first_line = (message or "").splitlines()[0].strip() if message else ""
    lower = first_line.lower()
    if len(first_line) < 6:
        # Single-word or near-empty commits — "fix", "wip", ".", etc.
        return True
    return any(lower.startswith(p) or p in lower[:25] for p in _NOISE_COMMIT_PATTERNS)


def _commit_title(message: str) -> str:
    """Extract the first non-noise line of the commit message as a
    standup title. Trims to ~80 chars so long messages don't blow out
    the dashboard layout."""
    first_line = (message or "").splitlines()[0].strip() if message else "Commit"
    # Strip common prefixes that just label the commit type
    for prefix in ("feat:", "feat(", "fix:", "fix(", "refactor:", "refactor(",
                   "docs:", "docs(", "perf:", "perf(", "test:", "test("):
        if first_line.lower().startswith(prefix):
            # Keep the prefix but truncate the body — devs want to see
            # "feat: payment retries" not just "payment retries" because
            # the prefix carries useful intent.
            break
    if len(first_line) > 80:
        first_line = first_line[:77].rstrip() + "…"
    return first_line


# ---------------------------------------------------------------------------
# AI-driven commit summarisation
# ---------------------------------------------------------------------------
#
# When a developer has many commits in the window (4+), listing each
# one as its own row in the standup digest gets noisy and unreadable.
# Instead, we run the commit messages through the AI caller and get
# back a 3-4 sentence summary written in past tense from the dev's
# perspective. That single summary becomes one "completed" item the
# frontend renders as a multi-line block (no ticket badge, no SHA).
#
# Only the surfaced (un-ticketed) commits are summarised — commits
# that are already represented by a closed ticket stay in the
# completed list under that ticket.

_COMMIT_SUMMARY_SYSTEM = (
    "You are a concise engineering reporter. You summarise a "
    "developer's recent commits into a short paragraph for their "
    "daily standup digest. Write in PAST TENSE, third person, "
    "natural English. Group related commits together — don't restate "
    "every commit. Aim for 3 to 4 sentences total, ~50 to 80 words. "
    "Do NOT use bullet points, headers, or markdown. Do NOT mention "
    "commit SHAs or branch names. Do NOT add a prefix like 'Summary:'."
)


def _build_commit_summary_prompt(member_name: str, messages: list[str]) -> str:
    bulleted = "\n".join(f"- {m}" for m in messages if m.strip())
    return (
        f"Developer: {member_name}\n\n"
        f"Recent commits ({len(messages)} total):\n"
        f"{bulleted}\n\n"
        f"Write a 3-4 sentence past-tense summary of what {member_name} "
        f"accomplished. Group related commits."
    )


async def _summarize_commits_with_ai(
    commits: list[Any], member_name: str
) -> str | None:
    """Return a 3-4 sentence summary of the commits, or None if the
    AI is unconfigured/errored. Falls through to caller's
    list-individually path on None."""
    if not commits:
        return None
    try:
        from .ai_caller import call_ai
        # Use the first line of each commit message — full bodies are
        # too noisy for summarisation and waste tokens.
        first_lines = [
            (c.message or "").splitlines()[0].strip() for c in commits
        ]
        # Cap input length to keep token cost predictable.
        first_lines = [m for m in first_lines if m][:30]
        if not first_lines:
            return None
        result = await call_ai(
            messages=[
                {"role": "system", "content": _COMMIT_SUMMARY_SYSTEM},
                {"role": "user", "content": _build_commit_summary_prompt(member_name, first_lines)},
            ],
            mode="primary",
            max_tokens=220,
            temperature=0.4,
            timeout_s=20.0,
        )
        if not result:
            return None
        summary = result.strip()
        # Defensive trim — AI sometimes prefixes despite instructions.
        for prefix in ("Summary:", "summary:", "Here is", "Here's"):
            if summary.startswith(prefix):
                summary = summary[len(prefix):].lstrip(" :—-")
        # Hard cap so a misbehaving model can't blow out the dashboard.
        if len(summary) > 600:
            summary = summary[:597].rstrip() + "…"
        return summary or None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Commit AI summary failed for {member_name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Per-member generation
# ---------------------------------------------------------------------------

async def generate_member_standup(
    db: AsyncSession,
    member: TeamMember,
    org_id: str,
    since: datetime,
    active_iteration_id: str | None = None,
) -> StandupReport | None:
    """Generate or update a standup report for a single team member.

    Cluster-aware: for orgs where the same human has multiple TM rows
    (each role/project creates its own TM, often with different
    emails), this function expands ``member.id`` to a cluster of TM
    ids matching the same display_name. GitHub commits/PRs attributed
    to a sibling TM still surface in this member's standup. Work
    items are NOT cluster-expanded — those are project-scoped and
    legitimately distinct per TM.
    """
    # UTC date — see routers/standups.py for the rationale (frontend +
    # report_date column are UTC, so "today" must be UTC too).
    today = datetime.now(timezone.utc).date()

    # Build the cluster of "same human" TM ids — every dev TM in the
    # org with the same display_name. Without this, commits attributed
    # to a sibling TM (e.g. the one with the user's work email) never
    # surface in this TM's standup (e.g. the one with the user's
    # signup email).
    cluster_tm_ids: list[str] = [member.id]
    if member.display_name:
        sibling_q = await db.execute(
            select(TeamMember.id).where(
                TeamMember.organization_id == org_id,
                func.lower(func.trim(TeamMember.display_name))
                    == member.display_name.strip().lower(),
                TeamMember.id != member.id,
            )
        )
        cluster_tm_ids.extend([row[0] for row in sibling_q.all()])

    # ── 1. Completed items: work items moved to DONE since last standup ──
    done_query = (
        select(WorkItem)
        .where(
            WorkItem.assignee_id == member.id,
            WorkItem.status == "DONE",
            WorkItem.updated_at >= since,
        )
        .order_by(WorkItem.updated_at.desc())
        .limit(20)
    )
    done_result = await db.execute(done_query)
    done_items = done_result.scalars().all()

    completed = [
        _to_standup_item(
            title=wi.title,
            ticket_id=wi.external_id,
        )
        for wi in done_items
    ]

    # ── 2. In-progress items ──
    ip_query = (
        select(WorkItem)
        .where(
            WorkItem.assignee_id == member.id,
            WorkItem.status.in_(["IN_PROGRESS", "IN_REVIEW"]),
        )
        .order_by(WorkItem.priority.asc(), WorkItem.updated_at.desc())
        .limit(20)
    )
    ip_result = await db.execute(ip_query)
    ip_items = ip_result.scalars().all()

    in_progress = [
        _to_standup_item(
            title=wi.title,
            ticket_id=wi.external_id,
        )
        for wi in ip_items
    ]

    # ── 3. PR activity ──
    # Cluster-expanded — picks up PRs attributed to any of this
    # human's TM rows (different roles/emails generate separate TM
    # rows but the human is the same).
    pr_query = (
        select(PullRequest)
        .where(
            PullRequest.author_id.in_(cluster_tm_ids),
            PullRequest.created_external_at >= since,
        )
        .order_by(PullRequest.created_external_at.desc())
        .limit(10)
    )
    pr_result = await db.execute(pr_query)
    prs = pr_result.scalars().all()

    pr_activity: list[dict] = []
    for pr in prs:
        pr_item = {
            "title": pr.title,
            "number": pr.number,
            "status": pr.status,
            "url": pr.url,
        }
        pr_activity.append(pr_item)

        # Merged PRs → add to completed
        if pr.status == "MERGED" or pr.merged_at:
            completed.append(_to_standup_item(
                title=f"PR #{pr.number}: {pr.title}",
                pr_id=str(pr.number),
                pr_status="MERGED",
            ))
        # Open PRs → add to in-progress
        elif pr.status in ("OPEN", "AWAITING_REVIEW", "CHANGES_REQUESTED"):
            in_progress.append(_to_standup_item(
                title=f"PR #{pr.number}: {pr.title}",
                pr_id=str(pr.number),
                pr_status=pr.status,
            ))

    # ── 4. Commits ──
    # Cluster-expanded query — fetches commits attributed to ANY of
    # this human's TM rows. Single-TM-per-human orgs collapse to the
    # original ``author_id == member.id`` behaviour because the
    # cluster has size 1. Multi-TM orgs (the same human has separate
    # TMs for different roles/projects/email-types) finally see their
    # commits in their standup regardless of which TM they're logged
    # in as.
    commits_query = (
        select(Commit)
        .where(
            Commit.author_id.in_(cluster_tm_ids),
            Commit.committed_at >= since,
        )
        .order_by(Commit.committed_at.desc())
        .limit(50)
    )
    commits_result = await db.execute(commits_query)
    commits = list(commits_result.scalars().all())
    commit_count = len(commits)

    # Build a set of external IDs already represented in ``completed``
    # so we don't double-count "PR #42: Fix login" + "Fix login commit
    # for JIRA-42".
    completed_ticket_ids = {c.get("ticketId") for c in completed if c.get("ticketId")}

    # First pass — collect surfaceable commits (skip noise + duplicates
    # of already-in-completed tickets). We need the full list to decide
    # whether to call AI for a summary; just collect into a temp list.
    surfaced_commit_objs: list[Any] = []
    skipped_noise = 0
    skipped_dedup = 0
    for c in commits:
        if _is_noise_commit(c.message):
            skipped_noise += 1
            continue
        linked = list(c.linked_ticket_ids or [])
        if linked and any(t in completed_ticket_ids for t in linked):
            skipped_dedup += 1
            continue
        surfaced_commit_objs.append(c)

    logger.info(
        f"[Standup Gen] member={member.email!r} display={member.display_name!r} "
        f"cluster_tm_ids_count={len(cluster_tm_ids)} "
        f"commits_returned={commit_count} surfaced={len(surfaced_commit_objs)} "
        f"skipped_noise={skipped_noise} skipped_dedup={skipped_dedup}"
    )

    # Decision: if the developer has 4+ surfaced commits, listing each
    # one clutters the standup digest. Instead, run them through the AI
    # caller and replace the list with a single 3-4 sentence summary
    # item (marked ``isCommitSummary=true`` so the frontend can render
    # it as a paragraph rather than a row of titles + SHA badges).
    # Under 4 commits → fall through to the individual-item path
    # because a 1-2 line list is more skimmable than a paragraph.
    if len(surfaced_commit_objs) >= 4:
        logger.info(
            f"[Standup Gen] member={member.email!r}: calling AI "
            f"summarizer on {len(surfaced_commit_objs[:30])} commit(s)"
        )
        summary = await _summarize_commits_with_ai(
            surfaced_commit_objs[:30], member.display_name
        )
        if summary:
            logger.info(
                f"[Standup Gen] member={member.email!r}: AI summary "
                f"OK ({len(summary)} chars) — adding isCommitSummary item"
            )
            completed.append({
                "title": summary,
                "isCommitSummary": True,
                "commitCount": len(surfaced_commit_objs),
            })
        else:
            logger.warning(
                f"[Standup Gen] member={member.email!r}: AI summary "
                f"returned None — falling back to per-commit list"
            )
            # AI unavailable / failed — fall back to listing the top 10
            # so the dev still sees their work.
            for c in surfaced_commit_objs[:10]:
                linked = list(c.linked_ticket_ids or [])
                completed.append(_to_standup_item(
                    title=_commit_title(c.message),
                    ticket_id=linked[0] if linked else None,
                    commit_sha=c.sha[:8] if c.sha else None,
                ))
    else:
        # Few commits — list each individually for skimmability.
        for c in surfaced_commit_objs:
            linked = list(c.linked_ticket_ids or [])
            completed.append(_to_standup_item(
                title=_commit_title(c.message),
                ticket_id=linked[0] if linked else None,
                commit_sha=c.sha[:8] if c.sha else None,
            ))

    # ── 5. Blockers ──
    # Check for any open blocker flags from recent standup reports.
    #
    # Auto-resolution: when the underlying work item has since moved to
    # a terminal status (DONE/CLOSED/RESOLVED), the blocker is no longer
    # real — but BlockerFlag rows weren't being closed when their ticket
    # got closed elsewhere in ADO. Result: stale "stalled_ticket" /
    # "review_bottleneck" blockers persisted in the dashboard for items
    # the developer had already shipped. We now auto-resolve those rows
    # on the fly: set resolved_at + status="RESOLVED" so they don't show
    # up in this report or any subsequent fetch.
    blocker_query = (
        select(BlockerFlag)
        .join(StandupReport, BlockerFlag.standup_report_id == StandupReport.id)
        .where(
            StandupReport.team_member_id == member.id,
            StandupReport.organization_id == org_id,
            BlockerFlag.status.in_(["OPEN", "ACKNOWLEDGED", "ESCALATED"]),
        )
        .limit(20)
    )
    blocker_result = await db.execute(blocker_query)
    blocker_flags = list(blocker_result.scalars().all())

    # Look up current status of every referenced ticket in one query.
    ticket_refs = {
        bf.ticket_reference for bf in blocker_flags if bf.ticket_reference
    }
    terminal_ext_ids: set[str] = set()
    if ticket_refs:
        from ._planning_status import TERMINAL_STATUSES
        wi_status_rows = (
            await db.execute(
                select(WorkItem.external_id, WorkItem.status).where(
                    WorkItem.organization_id == org_id,
                    WorkItem.external_id.in_(ticket_refs),
                )
            )
        ).all()
        terminal_ext_ids = {
            ext for ext, status in wi_status_rows
            if (status or "").upper() in TERMINAL_STATUSES
        }

    blockers: list[dict] = []
    now_utc = datetime.now(timezone.utc)
    for bf in blocker_flags:
        if bf.ticket_reference and bf.ticket_reference in terminal_ext_ids:
            # Underlying ticket is now done. Auto-resolve the flag and
            # skip it for this standup. The next regen won't even see
            # it because the WHERE clause filters by status.
            bf.status = "RESOLVED"
            bf.resolved_at = now_utc
            continue
        blockers.append({
            "description": bf.description,
            "ticketId": bf.ticket_reference,
            "status": bf.status,
        })

    # ── Skip if no activity at all ──
    if not completed and not in_progress and not blockers and commit_count == 0:
        # Mark member as inactive for the day
        return None

    # ── 6. Build narrative ──
    narrative = _build_narrative(
        member_name=member.display_name,
        completed=completed,
        in_progress=in_progress,
        blockers=blockers,
        pr_activity=pr_activity,
        commit_count=commit_count,
    )

    # ── 7. Upsert StandupReport ──
    # Check if report exists for today
    existing_query = (
        select(StandupReport)
        .where(
            StandupReport.organization_id == org_id,
            StandupReport.team_member_id == member.id,
            func.date(StandupReport.report_date) == today,
        )
    )
    existing_result = await db.execute(existing_query)
    report = existing_result.scalar_one_or_none()

    if report:
        # Update existing report with generated data
        report.completed_items = completed
        report.in_progress_items = in_progress
        report.blockers = blockers
        report.narrative_text = narrative
        report.iteration_id = active_iteration_id
    else:
        report = StandupReport(
            organization_id=org_id,
            team_member_id=member.id,
            iteration_id=active_iteration_id,
            report_date=datetime.now(timezone.utc),
            completed_items=completed,
            in_progress_items=in_progress,
            blockers=blockers,
            narrative_text=narrative,
            acknowledged=False,
            is_inactive=False,
        )
        db.add(report)

    return report


# ---------------------------------------------------------------------------
# Team digest generation
# ---------------------------------------------------------------------------

async def generate_team_digest(
    db: AsyncSession,
    org_id: str,
    reports: list[StandupReport],
    active_iteration_id: str | None = None,
) -> TeamStandupDigest:
    """Generate or update the team standup digest for today."""
    now = datetime.now(timezone.utc)
    today = now.date()  # UTC date — matches report_date storage

    # Compute metrics
    total_reports = len(reports)
    acknowledged = sum(1 for r in reports if r.acknowledged)
    ack_pct = int((acknowledged / total_reports) * 100) if total_reports > 0 else 0

    total_blockers = 0
    for r in reports:
        if isinstance(r.blockers, list):
            total_blockers += len(r.blockers)

    # Sprint pacing: compute from active iteration
    sprint_pacing = 0.0
    if active_iteration_id:
        # Count done vs total in the iteration
        total_q = await db.execute(
            select(func.count()).select_from(WorkItem)
            .where(WorkItem.iteration_id == active_iteration_id)
        )
        total_items = total_q.scalar() or 1

        done_q = await db.execute(
            select(func.count()).select_from(WorkItem)
            .where(
                WorkItem.iteration_id == active_iteration_id,
                WorkItem.status == "DONE",
            )
        )
        done_items = done_q.scalar() or 0

        # Also factor in time elapsed
        iter_result = await db.execute(
            select(Iteration).where(Iteration.id == active_iteration_id)
        )
        iteration = iter_result.scalar_one_or_none()
        if iteration and iteration.start_date and iteration.end_date:
            total_days = (iteration.end_date - iteration.start_date).days or 1
            elapsed = (now - iteration.start_date).days
            time_pct = min(elapsed / total_days, 1.0)
            work_pct = done_items / total_items
            sprint_pacing = int((work_pct / max(time_pct, 0.01)) * 100)
            sprint_pacing = min(sprint_pacing, 120)
        else:
            sprint_pacing = int((done_items / total_items) * 100)

    # Sprint health
    if sprint_pacing >= 80 and total_blockers == 0:
        sprint_health = "GREEN"
    elif sprint_pacing >= 50 or total_blockers <= 1:
        sprint_health = "AMBER"
    else:
        sprint_health = "RED"

    # At-risk items: items overdue or blocked
    at_risk_items: list[dict] = []
    at_risk_q = await db.execute(
        select(WorkItem)
        .where(
            WorkItem.organization_id == org_id,
            WorkItem.status.in_(["IN_PROGRESS", "TODO"]),
        )
        .order_by(WorkItem.priority.asc())
        .limit(5)
    )
    for wi in at_risk_q.scalars().all():
        # Flag items that are high priority and not done
        if wi.priority <= 2:
            at_risk_items.append({
                "workItemId": wi.external_id,
                "reason": f"High priority ({wi.type}) still {wi.status.lower().replace('_', ' ')}",
            })

    # Summary text
    summary_parts: list[str] = []
    total_completed = sum(
        len(r.completed_items) if isinstance(r.completed_items, list) else 0
        for r in reports
    )
    total_in_progress = sum(
        len(r.in_progress_items) if isinstance(r.in_progress_items, list) else 0
        for r in reports
    )
    summary_parts.append(f"Team completed {total_completed} items and has {total_in_progress} in progress.")
    if total_blockers > 0:
        summary_parts.append(f"{total_blockers} blocker{'s' if total_blockers > 1 else ''} require attention.")
    if sprint_pacing > 0:
        summary_parts.append(f"Sprint pacing is at {sprint_pacing}%.")

    summary_text = " ".join(summary_parts)

    # Upsert digest
    existing_q = await db.execute(
        select(TeamStandupDigest).where(
            TeamStandupDigest.organization_id == org_id,
            func.date(TeamStandupDigest.digest_date) == today,
        )
    )
    digest = existing_q.scalar_one_or_none()

    if digest:
        digest.sprint_pacing = sprint_pacing
        digest.acknowledged_pct = ack_pct
        digest.sprint_health = sprint_health
        digest.at_risk_items = {"items": at_risk_items}
        digest.blocker_count = total_blockers
        digest.summary_text = summary_text
        digest.iteration_id = active_iteration_id
    else:
        digest = TeamStandupDigest(
            organization_id=org_id,
            iteration_id=active_iteration_id,
            digest_date=now,
            sprint_pacing=sprint_pacing,
            acknowledged_pct=ack_pct,
            sprint_health=sprint_health,
            at_risk_items={"items": at_risk_items},
            blocker_count=total_blockers,
            summary_text=summary_text,
        )
        db.add(digest)

    return digest


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def generate_all_standups(
    db: AsyncSession,
    org_id: str,
) -> dict:
    """Generate standup reports for all team members in the org + team digest.

    Returns a summary dict with counts.
    """
    # UTC date — see standups.py for the TZ-consistency rationale.
    today = datetime.now(timezone.utc).date()

    # Skip weekends
    if today.weekday() in (5, 6):
        return {"generated": 0, "skipped": "weekend"}

    # Find all team members — only developers and engineering managers
    # generate standup reports. Hotfix 46: strict allowlist prevents PO /
    # stakeholder TM rows (which the user has confirmed exist for the same
    # human) from ever creating a StandupReport in the first place.
    DEV_ROLES = ("developer", "engineering_manager")
    member_result = await db.execute(
        select(TeamMember)
        .where(
            TeamMember.organization_id == org_id,
            TeamMember.role.in_(DEV_ROLES),
        )
        .order_by(TeamMember.display_name)
    )
    members = member_result.scalars().all()

    if not members:
        return {"generated": 0, "skipped": "no_team_members"}

    # ── Orphan-commit backfill (repo-owner matching) ──
    # The GitHub push matcher historically only checked
    # ``team_members.external_id``, so most past commits were stored
    # with ``author_id = NULL``. The improved matcher in
    # github_tracker.py fixes new commits going forward, but past
    # orphans need a retroactive pass. We don't have the author email
    # on the Commit row (never stored it), so we use the next-best
    # signal: the repo's GitHub owner segment (``Sangini-spec`` from
    # ``Sangini-spec/Plan2Sprint``).
    #
    # For each repo with at least one orphan commit:
    #   1. Parse the owner segment from ``Repository.full_name``.
    #   2. Try to find a TeamMember whose ``github_username``,
    #      ``external_id``, ``email`` LIKE, or first-word-of-display-name
    #      matches the owner.
    #   3. If found, attribute every orphan in that repo to them.
    #
    # Falls back to single-dev-org attribution when matching fails
    # but the org has exactly one developer TM.
    try:
        from sqlalchemy import update as _update
        from ..models.repository import Repository as _Repo
        from ..models.team_member import TeamMember as _TM

        # ── Author-email backfill via GitHub API ──
        # If this org has commits whose ``author_email`` is NULL, the
        # curated standup view's email-bridge match path can't fire
        # for them. Run a one-shot refetch against GitHub to populate
        # the missing identity fields BEFORE we run the per-member
        # loop. Best effort — silent failure leaves the commits orphan
        # but doesn't block standup generation.
        try:
            null_email_count_q = await db.execute(
                select(func.count(Commit.id))
                .join(_Repo, _Repo.id == Commit.repository_id)
                .where(
                    _Repo.organization_id == org_id,
                    Commit.author_email.is_(None),
                )
            )
            null_email_count = null_email_count_q.scalar() or 0
            if null_email_count > 0:
                logger.info(
                    f"[Standup Gen] Org={org_id} has {null_email_count} "
                    f"commit(s) without author_email — triggering inline "
                    f"GitHub API refetch to populate identity fields."
                )
                from .github_author_refetch import refetch_orphan_authors
                refetch_result = await refetch_orphan_authors(db, org_id)
                logger.info(
                    f"[Standup Gen] Refetch complete: {refetch_result}"
                )
        except Exception as e:
            logger.warning(
                f"[Standup Gen] Inline author refetch failed for "
                f"{org_id}: {e}"
            )

        # Diagnostic: how many Repository rows belong to THIS org, vs total.
        # Multi-org users (the founder has accounts across multiple
        # orgs) sometimes have their GitHub repo linked to a different
        # org than the one their JWT scopes to — the standup digest
        # for the JWT org never sees those commits.
        total_repos_q = await db.execute(
            select(func.count(_Repo.id)).where(_Repo.organization_id == org_id)
        )
        total_repos_in_org = total_repos_q.scalar() or 0
        total_commits_q = await db.execute(
            select(func.count(Commit.id))
            .join(_Repo, _Repo.id == Commit.repository_id)
            .where(_Repo.organization_id == org_id)
        )
        total_commits_in_org = total_commits_q.scalar() or 0
        # Also count NULL-author across ALL orgs so we can detect the
        # cross-org case (commits exist somewhere but not here).
        global_orphan_q = await db.execute(
            select(func.count(Commit.id)).where(Commit.author_id.is_(None))
        )
        global_orphan_count = global_orphan_q.scalar() or 0
        logger.info(
            f"[Standup Gen] Org={org_id} state: "
            f"repos={total_repos_in_org}, commits_in_org={total_commits_in_org}, "
            f"global_null_author_commits={global_orphan_count}"
        )

        # Deep diagnostic — dump distinct (author_email, author_id, author_name)
        # tuples for the org's commits along with each dev TM's
        # (email, display_name, id). This is the exact data the curated
        # view's match uses. Once we can see what's there vs what's
        # being matched, the gap is obvious.
        try:
            sample_q = await db.execute(
                select(
                    Commit.author_email,
                    Commit.author_name,
                    Commit.author_id,
                    func.count(Commit.id).label("n"),
                )
                .join(_Repo, _Repo.id == Commit.repository_id)
                .where(_Repo.organization_id == org_id)
                .group_by(Commit.author_email, Commit.author_name, Commit.author_id)
                .limit(20)
            )
            for row in sample_q.all():
                logger.info(
                    f"[Standup Gen] DIAG commit-author group: "
                    f"email={row.author_email!r}, name={row.author_name!r}, "
                    f"tm_id={row.author_id!r}, count={row.n}"
                )
            dev_tms_q = await db.execute(
                select(_TM.id, _TM.email, _TM.display_name, _TM.role, _TM.github_username)
                .where(
                    _TM.organization_id == org_id,
                    _TM.role.in_(DEV_ROLES),
                )
                .limit(10)
            )
            for tm_row in dev_tms_q.all():
                logger.info(
                    f"[Standup Gen] DIAG dev TM: "
                    f"id={tm_row.id}, email={tm_row.email!r}, "
                    f"display={tm_row.display_name!r}, "
                    f"role={tm_row.role!r}, gh={tm_row.github_username!r}"
                )
        except Exception as e:
            logger.warning(f"[Standup Gen] DIAG dump failed: {e}")

        # Repos in this org with at least one NULL-author commit
        repos_with_orphans_q = await db.execute(
            select(_Repo)
            .join(Commit, Commit.repository_id == _Repo.id)
            .where(
                _Repo.organization_id == org_id,
                Commit.author_id.is_(None),
            )
            .distinct()
        )
        repos_with_orphans = list(repos_with_orphans_q.scalars().all())
        logger.info(
            f"[Standup Gen] Orphan backfill scan for org={org_id}: "
            f"{len(repos_with_orphans)} repo(s) have NULL-author commits"
        )

        # ── Misattribution detection ──
        # Even when 0 commits are technically "orphan" (NULL author),
        # they may all be attributed to a TM in this org whose role is
        # NOT in DEV_ROLES (e.g. the same human's PO TM row, or a
        # stakeholder TM). The curated digest view filters by emails
        # belonging to dev TMs only — non-dev attributions are
        # invisible in the digest even though the rows exist. Detect
        # by checking whether the author TMs are in the dev set; if
        # not, re-attribute to the right dev TM.
        if total_commits_in_org > 0 and len(members) > 0:
            dev_tm_ids_q = await db.execute(
                select(_TM.id).where(
                    _TM.organization_id == org_id,
                    _TM.role.in_(DEV_ROLES),
                )
            )
            dev_tm_ids = {row[0] for row in dev_tm_ids_q.all()}
            mis_q = await db.execute(
                select(func.count(Commit.id))
                .join(_Repo, _Repo.id == Commit.repository_id)
                .where(
                    _Repo.organization_id == org_id,
                    Commit.author_id.isnot(None),
                    ~Commit.author_id.in_(list(dev_tm_ids)) if dev_tm_ids else Commit.author_id.is_(None),
                )
            )
            mis_count = mis_q.scalar() or 0
            if mis_count:
                logger.warning(
                    f"[Standup Gen] MISATTRIBUTION: {mis_count} commit(s) "
                    f"in org={org_id}'s repos are attributed to non-DEV "
                    f"TMs (likely the same human's PO/stakeholder TM row). "
                    f"Resetting them so the lookup-table path can "
                    f"re-attribute to the correct dev TM."
                )
                await db.execute(
                    _update(Commit)
                    .where(
                        Commit.repository_id.in_(
                            select(_Repo.id).where(_Repo.organization_id == org_id)
                        ),
                        Commit.author_id.isnot(None),
                        ~Commit.author_id.in_(list(dev_tm_ids)),
                    )
                    .values(author_id=None)
                )
                # Re-scan
                repos_with_orphans_q = await db.execute(
                    select(_Repo)
                    .join(Commit, Commit.repository_id == _Repo.id)
                    .where(
                        _Repo.organization_id == org_id,
                        Commit.author_id.is_(None),
                    )
                    .distinct()
                )
                repos_with_orphans = list(repos_with_orphans_q.scalars().all())
                logger.info(
                    f"[Standup Gen] After misattribution reset: "
                    f"{len(repos_with_orphans)} repo(s) now have orphans"
                )

        # Cross-org safety net — if this org has commits but the
        # author_id points to a TM in a DIFFERENT org, the standup
        # generator's per-member query (Commit.author_id == this_tm.id)
        # will miss them. List the distinct author_ids on this org's
        # commits and check whether any are NOT in this org's TM set.
        if total_commits_in_org > 0:
            cross_org_q = await db.execute(
                select(func.count(Commit.id.distinct()))
                .join(_Repo, _Repo.id == Commit.repository_id)
                .where(
                    _Repo.organization_id == org_id,
                    Commit.author_id.isnot(None),
                    ~Commit.author_id.in_(
                        select(_TM.id).where(_TM.organization_id == org_id)
                    ),
                )
            )
            cross_org_attributed = cross_org_q.scalar() or 0
            if cross_org_attributed:
                logger.warning(
                    f"[Standup Gen] CROSS-ORG ATTRIBUTION DETECTED: "
                    f"{cross_org_attributed} commit(s) in org={org_id}'s "
                    f"repos are attributed to TMs in DIFFERENT orgs. "
                    f"Re-attributing to TMs in this org."
                )
                # Treat these as orphans for re-attribution purposes
                # so the lookup-table path below picks them up. We do
                # this by NULL-ing their author_id temporarily, then
                # the backfill flow assigns them to the right TM.
                # Safe because the original attribution was wrong by
                # construction — those TMs can't appear in this org's
                # standup digest anyway.
                from sqlalchemy import update as _u2
                await db.execute(
                    _u2(Commit)
                    .where(
                        Commit.repository_id.in_(
                            select(_Repo.id).where(_Repo.organization_id == org_id)
                        ),
                        Commit.author_id.isnot(None),
                        ~Commit.author_id.in_(
                            select(_TM.id).where(_TM.organization_id == org_id)
                        ),
                    )
                    .values(author_id=None)
                )
                # Re-query repos_with_orphans now that we created some.
                repos_with_orphans_q = await db.execute(
                    select(_Repo)
                    .join(Commit, Commit.repository_id == _Repo.id)
                    .where(
                        _Repo.organization_id == org_id,
                        Commit.author_id.is_(None),
                    )
                    .distinct()
                )
                repos_with_orphans = list(repos_with_orphans_q.scalars().all())
                logger.info(
                    f"[Standup Gen] After cross-org reset: "
                    f"{len(repos_with_orphans)} repo(s) now have orphans"
                )

        if repos_with_orphans:
            # ALL TMs in the org, not just DEV_ROLES — a commit author
            # might be a PO/admin whose TM row has a non-dev role yet
            # is the actual GitHub committer. Filtering by DEV_ROLES
            # here would exclude the very person who needs to be
            # matched. Generated standups still filter by DEV_ROLES
            # separately — this lookup is only for resolving commit
            # attribution.
            all_tms_q = await db.execute(
                select(_TM).where(
                    _TM.organization_id == org_id,
                    or_(_TM.role.is_(None), _TM.role != "excluded"),
                )
            )
            all_tms_raw = list(all_tms_q.scalars().all())
            # Bias toward DEV_ROLES: insert non-dev TMs FIRST then
            # dev TMs LAST so dev TMs overwrite duplicate keys (same
            # human's dev TM + PO TM share display-name first-word
            # "sangini" → the dev one wins). The standup digest is
            # only meaningful when commits attribute to dev TMs (the
            # only ones with StandupReport rows).
            non_dev = [t for t in all_tms_raw if (t.role or "").lower() not in DEV_ROLES]
            dev = [t for t in all_tms_raw if (t.role or "").lower() in DEV_ROLES]
            all_tms = non_dev + dev
            logger.info(
                f"[Standup Gen] Orphan backfill lookup table: "
                f"{len(all_tms)} TM candidate(s) "
                f"(non_dev={len(non_dev)}, dev={len(dev)})"
            )
            lookup: dict[str, _TM] = {}
            for tm in all_tms:
                if tm.github_username:
                    lookup[tm.github_username.lower()] = tm
                if tm.external_id:
                    lookup[tm.external_id.lower()] = tm
                if tm.email:
                    lookup[tm.email.lower()] = tm
                    # local part of email — owners often use @user-handle
                    local = tm.email.split("@", 1)[0].lower()
                    lookup.setdefault(local, tm)
                if tm.display_name:
                    # first word of display name, lowercased (e.g.
                    # "Sangini Tripathi" → "sangini") to catch the
                    # common case of "First-spec" repo owners.
                    first = tm.display_name.split()[0].lower()
                    lookup.setdefault(first, tm)

            total_attributed = 0
            for repo in repos_with_orphans:
                full = (repo.full_name or "")
                owner = full.split("/", 1)[0].strip().lower() if "/" in full else ""
                if not owner:
                    logger.warning(
                        f"[Standup Gen] Repo {repo.id} has no parseable "
                        f"owner from full_name='{full}'; skipping"
                    )
                    continue
                # Try exact owner match against any TM signal.
                tm = lookup.get(owner)
                match_path = "owner_exact"
                if not tm:
                    # Owner might be "Sangini-spec" but the TM key is
                    # "sangini" — try the owner's first hyphen-separated
                    # segment (e.g. "Sangini-spec" → "sangini").
                    owner_prefix = owner.split("-", 1)[0]
                    tm = lookup.get(owner_prefix)
                    if tm:
                        match_path = f"owner_prefix({owner_prefix})"
                if not tm:
                    # Try substring containment — owner "sangini-spec"
                    # contains a TM's display first-word "sangini" or
                    # vice versa. Helps when the owner has a suffix
                    # like "-spec" that isn't separated by a hyphen
                    # in the prefix slice.
                    for key, candidate in lookup.items():
                        if key and (key in owner or owner in key):
                            tm = candidate
                            match_path = f"substring({key})"
                            break
                if not tm and len(all_tms) == 1:
                    # Single-TM-org fallback when owner-based match
                    # fails. All orphan commits in this org's repos
                    # must belong to the lone TM.
                    tm = all_tms[0]
                    match_path = "single_tm_org"
                if not tm:
                    logger.warning(
                        f"[Standup Gen] No TM match for repo "
                        f"'{repo.full_name}' (owner='{owner}'); "
                        f"lookup_keys={sorted(lookup.keys())[:10]}…; "
                        f"orphan commits stay attribution-less."
                    )
                    continue

                upd = await db.execute(
                    _update(Commit)
                    .where(
                        Commit.repository_id == repo.id,
                        Commit.author_id.is_(None),
                    )
                    .values(author_id=tm.id)
                )
                n = upd.rowcount or 0
                if n:
                    total_attributed += n
                    logger.info(
                        f"[Standup Gen] Orphan backfill MATCH "
                        f"(path={match_path}): attributed {n} commit(s) "
                        f"in repo '{repo.full_name}' (owner='{owner}') → "
                        f"TM {tm.email} (id={tm.id}, role={tm.role})"
                    )
            if total_attributed:
                await db.flush()
                logger.info(
                    f"[Standup Gen] Orphan backfill complete for "
                    f"org={org_id}: {total_attributed} commit(s) attributed."
                )
    except Exception as e:
        logger.warning(f"Orphan commit backfill failed for {org_id}: {e}")

    # Find active iteration
    iter_result = await db.execute(
        select(Iteration)
        .where(
            Iteration.organization_id == org_id,
            Iteration.state == "active",
        )
        .order_by(Iteration.start_date.desc())
        .limit(1)
    )
    active_iter = iter_result.scalar_one_or_none()
    active_iteration_id = active_iter.id if active_iter else None

    # Determine "since" cutoff — last generated report for the org
    last_report_q = await db.execute(
        select(StandupReport.report_date)
        .where(StandupReport.organization_id == org_id)
        .order_by(StandupReport.report_date.desc())
        .limit(1)
    )
    last_report_row = last_report_q.scalar_one_or_none()
    since = _since_cutoff(last_report_row)

    # Generate per-member reports
    reports: list[StandupReport] = []
    generated = 0
    inactive = 0

    for member in members:
        try:
            report = await generate_member_standup(
                db=db,
                member=member,
                org_id=org_id,
                since=since,
                active_iteration_id=active_iteration_id,
            )
            if report:
                reports.append(report)
                generated += 1
            else:
                # Create inactive placeholder
                existing_q = await db.execute(
                    select(StandupReport).where(
                        StandupReport.organization_id == org_id,
                        StandupReport.team_member_id == member.id,
                        func.date(StandupReport.report_date) == today,
                    )
                )
                existing = existing_q.scalar_one_or_none()
                if not existing:
                    placeholder = StandupReport(
                        organization_id=org_id,
                        team_member_id=member.id,
                        iteration_id=active_iteration_id,
                        report_date=datetime.now(timezone.utc),
                        completed_items=[],
                        in_progress_items=[],
                        blockers=[],
                        narrative_text=f"{member.display_name} has no recent activity.",
                        acknowledged=False,
                        is_inactive=True,
                    )
                    db.add(placeholder)
                    reports.append(placeholder)
                inactive += 1
        except Exception as e:
            logger.warning(f"Failed to generate standup for {member.display_name}: {e}")

    # Generate team digest
    try:
        digest = await generate_team_digest(
            db=db,
            org_id=org_id,
            reports=reports,
            active_iteration_id=active_iteration_id,
        )
    except Exception as e:
        logger.warning(f"Failed to generate team digest: {e}")

    await db.commit()

    return {
        "generated": generated,
        "inactive": inactive,
        "totalMembers": len(members),
        "digestGenerated": True,
    }

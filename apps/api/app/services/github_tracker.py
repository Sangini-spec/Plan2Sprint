"""
GitHub Activity Tracker — the CORE engine that maps developer code activity
to sprint progress tracking.

This is what differentiates Plan2Sprint from Jira/ADO:
  - Developers just write code (commits, PRs, merges)
  - The platform automatically tracks everything via GitHub webhooks
  - No manual board updates needed — code activity IS the tracking

Status Transition Rules:
  ┌─────────────────────────────────────────────────────────┐
  │  Commit pushed (with ticket ref)  →  TODO → IN_PROGRESS │
  │  PR opened   (with ticket ref)    →  stays IN_PROGRESS  │
  │  PR review approved               →  IN_PROGRESS → IN_REVIEW │
  │  PR merged   (with ticket ref)    →  → DONE             │
  └─────────────────────────────────────────────────────────┘

After any status change, the sprint completion service checks if all items
in the sprint are Done — and auto-completes the sprint if so.
"""

from __future__ import annotations

import re
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.base import generate_cuid
from ..models.work_item import WorkItem
from ..models.team_member import TeamMember
from ..models.repository import Repository, PullRequest, Commit
from ..models.activity import ActivityEvent

logger = logging.getLogger(__name__)

# Statuses considered "not yet started" — eligible for auto-transition
BACKLOG_STATUSES = {"BACKLOG", "TODO", "New", "To Do"}
# Statuses eligible for review transition
IN_PROGRESS_STATUSES = {"IN_PROGRESS", "Active", "In Progress"}
# Statuses considered "done" — no further transitions
DONE_STATUSES = {"DONE", "Closed", "CLOSED", "Done", "Resolved"}

# Regex patterns for extracting ticket references from commit messages / PR titles
TICKET_PATTERNS = [
    re.compile(r"[A-Z]+-\d+"),        # Jira-style: PROJ-123
    re.compile(r"#(\d+)"),            # GitHub-style: #123
    re.compile(r"AB#(\d+)"),          # ADO-style: AB#123
]


def extract_ticket_refs(text: str) -> list[str]:
    """Extract all ticket references from a commit message or PR title."""
    refs: list[str] = []
    if not text:
        return refs
    for pattern in TICKET_PATTERNS:
        refs.extend(pattern.findall(text))
    return list(set(refs))  # deduplicate


async def find_work_items_by_refs(
    db: AsyncSession,
    org_id: str,
    ticket_refs: list[str],
) -> list[WorkItem]:
    """
    Find WorkItems matching ticket references.

    Matches against:
      - work_item.external_id (the ID from ADO/Jira, e.g., "12345")
      - work_item.external_id variants (e.g., ref "AB#123" matches external_id "123")
    """
    if not ticket_refs:
        return []

    # Build a list of possible external_id values
    # "AB#123" → "123", "PROJ-201" → "PROJ-201", "#456" → "456"
    possible_ids = set()
    for ref in ticket_refs:
        possible_ids.add(ref)
        # Strip common prefixes
        if ref.startswith("AB#"):
            possible_ids.add(ref[3:])
        elif "#" in ref:
            possible_ids.add(ref.lstrip("#"))

    result = await db.execute(
        select(WorkItem).where(
            WorkItem.organization_id == org_id,
            WorkItem.external_id.in_(list(possible_ids)),
        )
    )
    return list(result.scalars().all())


async def find_team_member_by_github(
    db: AsyncSession,
    org_id: str,
    github_username: str | None = None,
    github_email: str | None = None,
) -> TeamMember | None:
    """Find a TeamMember by their GitHub username or email.

    Lookup order (each falls through to the next on miss):
      1. ``team_members.github_username`` — the dedicated GitHub-handle
         column populated when a developer links their personal GitHub.
      2. ``team_members.external_id`` — the ADO/Jira id, which on some
         orgs coincidentally equals the GitHub handle.
      3. ``team_members.email`` LIKE ``%{github_username}%``.
      4. ``team_members.email`` case-insensitive match against the
         commit author email.
      5. **User-link fallback** — find a ``users`` row whose email
         matches the commit author email, then look up any TM in this
         org with the same email. Covers the case where the developer
         signed up with ``personal@gmail.com``, but their TM row in
         the PO's ADO-synced org has a different email entirely —
         the User row is the only bridge between the two identities.

    Without these fallbacks the matcher returned ``None`` for almost
    every developer whose ADO id ≠ GitHub handle (i.e. most devs).
    Their commits got ingested with ``author_id = NULL`` and never
    appeared in the standup digest, even after the push webhook
    successfully stored them.
    """
    if not github_username and not github_email:
        return None

    conditions = []
    if github_username:
        conditions.append(TeamMember.github_username.ilike(github_username))
        conditions.append(TeamMember.external_id == github_username)
        conditions.append(TeamMember.email.ilike(f"%{github_username}%"))
    if github_email:
        conditions.append(TeamMember.email.ilike(github_email))

    result = await db.execute(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
            or_(*conditions),
        ).limit(1)
    )
    tm = result.scalar_one_or_none()
    if tm:
        return tm

    # Step 5 — User-link fallback. Bridge identities by email through
    # the User table when the TM row's email isn't a direct match.
    if github_email:
        from ..models.user import User as _User
        u_row = (await db.execute(
            select(_User).where(_User.email.ilike(github_email))
        )).scalar_one_or_none()
        if u_row:
            tm = (await db.execute(
                select(TeamMember).where(
                    TeamMember.organization_id == org_id,
                    TeamMember.email.ilike(u_row.email),
                ).limit(1)
            )).scalar_one_or_none()
            if tm:
                return tm

    return None


async def backfill_orphan_commits(
    db: AsyncSession,
    org_id: str,
    repository_id: str,
    resolved_member: TeamMember,
) -> int:
    """Attribute past commits in this repo that have ``author_id=NULL``
    to ``resolved_member``.

    Triggered when a webhook successfully matches an author for a
    newly-arrived commit. If a dev's first webhook arrival just
    resolved their TM, every prior commit in the same repo with a
    NULL author was almost certainly also theirs (small/single-dev
    repos), so we backfill them now. This makes the standup digest
    surface those earlier commits the moment the matcher catches up,
    instead of leaving them orphaned forever.

    For multi-dev repos this is best-effort and may misattribute,
    but the standup generator already caps surfaced commits per
    member at 10/day so the blast radius is limited. The alternative
    (orphan commits never surface for anyone) is strictly worse.

    Returns the number of rows updated.
    """
    from sqlalchemy import update as _update
    res = await db.execute(
        _update(Commit)
        .where(
            Commit.repository_id == repository_id,
            Commit.author_id.is_(None),
        )
        .values(author_id=resolved_member.id)
    )
    return res.rowcount or 0


# ---------------------------------------------------------------------------
# PUSH EVENT HANDLER — Commit-based tracking
# ---------------------------------------------------------------------------

async def process_push_event(
    db: AsyncSession,
    org_id: str,
    payload: dict,
) -> dict[str, Any]:
    """
    Process a GitHub push event (webhook).

    For each commit:
      1. Parse ticket references from commit message
      2. Find matching WorkItems in the database
      3. Transition TODO/BACKLOG → IN_PROGRESS
      4. Record activity event
      5. Store commit in DB
    """
    repo_name = payload.get("repository", {}).get("full_name", "")
    branch = (payload.get("ref", "")).replace("refs/heads/", "")
    commits = payload.get("commits", [])
    pusher = payload.get("pusher", {})

    items_updated = []
    commits_processed = 0
    activity_events_created = 0
    # Track every TeamMember whose commits appear in this push, so the
    # webhook caller can regen their standup live (the developer's
    # "completed today" section should reflect their pushes the moment
    # they land, not on next scheduled standup gen).
    affected_member_ids: set[str] = set()

    # Find the repository in our DB
    repo = None
    if repo_name:
        result = await db.execute(
            select(Repository).where(
                Repository.organization_id == org_id,
                Repository.full_name == repo_name,
            )
        )
        repo = result.scalar_one_or_none()

    # Find the team member (pusher)
    member = await find_team_member_by_github(
        db, org_id,
        github_username=pusher.get("name"),
        github_email=pusher.get("email"),
    )

    for commit_data in commits:
        message = commit_data.get("message", "")
        sha = commit_data.get("id", "")
        timestamp_str = commit_data.get("timestamp", "")
        author_info = commit_data.get("author", {})

        # If we couldn't find member from pusher, try commit author
        if not member:
            member = await find_team_member_by_github(
                db, org_id,
                github_username=author_info.get("username"),
                github_email=author_info.get("email"),
            )

        # Parse ticket refs from commit message
        ticket_refs = extract_ticket_refs(message)

        # Find matching work items
        work_items = await find_work_items_by_refs(db, org_id, ticket_refs)

        # Transition status: TODO/BACKLOG → IN_PROGRESS
        for wi in work_items:
            if wi.status in BACKLOG_STATUSES:
                old_status = wi.status
                wi.status = "IN_PROGRESS"
                wi.source_status = "In Progress"
                items_updated.append({
                    "workItemId": wi.id,
                    "externalId": wi.external_id,
                    "title": wi.title,
                    "oldStatus": old_status,
                    "newStatus": "IN_PROGRESS",
                    "trigger": "commit",
                    "commitSha": sha[:8],
                    "commitMessage": message[:100],
                })
                logger.info(
                    f"[GitHub Tracker] Commit {sha[:8]} → "
                    f"WorkItem '{wi.title}' ({wi.external_id}): "
                    f"{old_status} → IN_PROGRESS"
                )

        # Store commit in DB (if we have a repo)
        if repo:
            try:
                committed_at = datetime.fromisoformat(
                    timestamp_str.replace("Z", "+00:00")
                ) if timestamp_str else datetime.now(timezone.utc)

                existing = await db.execute(
                    select(Commit).where(
                        Commit.repository_id == repo.id,
                        Commit.sha == sha,
                    )
                )
                if not existing.scalar_one_or_none():
                    new_commit = Commit(
                        id=generate_cuid(),
                        repository_id=repo.id,
                        sha=sha,
                        message=message[:500],
                        author_id=member.id if member else None,
                        branch=branch,
                        linked_ticket_ids=ticket_refs,
                        files_changed=len(commit_data.get("modified", []))
                        + len(commit_data.get("added", []))
                        + len(commit_data.get("removed", [])),
                        committed_at=committed_at,
                    )
                    db.add(new_commit)
                    commits_processed += 1
                    if member and member.id:
                        affected_member_ids.add(member.id)
                        # Opportunistic backfill — if this is the first
                        # successfully-attributed commit for the repo,
                        # mop up the earlier orphans. Cheap to run once
                        # per author resolution and dramatically
                        # improves the dev's first standup view.
                        try:
                            await backfill_orphan_commits(
                                db, org_id, repo.id, member
                            )
                        except Exception as e:
                            logger.warning(
                                f"Orphan commit backfill failed for "
                                f"{repo.full_name} → {member.email}: {e}"
                            )
            except Exception as e:
                logger.warning(f"Failed to store commit {sha[:8]}: {e}")

        # Record activity event
        if member:
            try:
                occurred_at = datetime.now(timezone.utc)
                if timestamp_str:
                    try:
                        occurred_at = datetime.fromisoformat(
                            timestamp_str.replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass

                from .activity_engine import record_activity
                await record_activity(
                    db=db,
                    org_id=org_id,
                    team_member_id=member.id,
                    event_type="push",
                    source_tool="github",
                    occurred_at=occurred_at,
                    external_id=sha[:8],
                    linked_ticket_id=ticket_refs[0] if ticket_refs else None,
                    metadata={
                        "branch": branch,
                        "message": message[:200],
                        "repo": repo_name,
                        "ticketRefs": ticket_refs,
                    },
                )
                activity_events_created += 1
            except Exception as e:
                logger.warning(f"Failed to record push activity: {e}")

    await db.flush()

    summary = {
        "event": "push",
        "repo": repo_name,
        "branch": branch,
        "commitsProcessed": commits_processed,
        "itemsUpdated": len(items_updated),
        "activityEvents": activity_events_created,
        "transitions": items_updated,
        # IDs of TeamMembers whose commits landed in this push — the
        # webhook handler uses these to trigger a live standup regen
        # so the dev's dashboard reflects the new commits without a
        # manual refresh.
        "affectedMemberIds": sorted(affected_member_ids),
    }

    if items_updated:
        logger.info(
            f"[GitHub Tracker] Push to {repo_name}/{branch}: "
            f"{len(items_updated)} work items moved to IN_PROGRESS"
        )

    return summary


# ---------------------------------------------------------------------------
# PULL REQUEST EVENT HANDLER
# ---------------------------------------------------------------------------

async def process_pull_request_event(
    db: AsyncSession,
    org_id: str,
    payload: dict,
) -> dict[str, Any]:
    """
    Process a GitHub pull_request event (webhook).

    Actions:
      - opened: Link PR to work items, record activity
      - review_requested: Flag work item as "in review"
      - closed+merged: Transition linked work items → DONE
      - closed (not merged): No status change (PR rejected)
    """
    action = payload.get("action", "")
    pr_data = payload.get("pull_request", {})
    repo_data = payload.get("repository", {})

    repo_name = repo_data.get("full_name", "")
    pr_number = pr_data.get("number", 0)
    pr_title = pr_data.get("title", "")
    pr_body = pr_data.get("body", "") or ""
    pr_state = pr_data.get("state", "")
    is_merged = pr_data.get("merged", False)
    merged_at = pr_data.get("merged_at")
    pr_url = pr_data.get("html_url", "")
    pr_user = pr_data.get("user", {})
    head_branch = pr_data.get("head", {}).get("ref", "")

    items_updated = []

    # Find the repository
    repo = None
    if repo_name:
        result = await db.execute(
            select(Repository).where(
                Repository.organization_id == org_id,
                Repository.full_name == repo_name,
            )
        )
        repo = result.scalar_one_or_none()

    # Find the team member (PR author)
    member = await find_team_member_by_github(
        db, org_id,
        github_username=pr_user.get("login"),
    )

    # Parse ticket refs from PR title + body + branch name
    all_text = f"{pr_title} {pr_body} {head_branch}"
    ticket_refs = extract_ticket_refs(all_text)

    # Find matching work items
    work_items = await find_work_items_by_refs(db, org_id, ticket_refs)

    # ── Action: PR Merged → Mark linked items as DONE ──
    if action == "closed" and is_merged:
        for wi in work_items:
            if wi.status not in DONE_STATUSES:
                old_status = wi.status
                wi.status = "DONE"
                wi.source_status = "Done"
                items_updated.append({
                    "workItemId": wi.id,
                    "externalId": wi.external_id,
                    "title": wi.title,
                    "oldStatus": old_status,
                    "newStatus": "DONE",
                    "trigger": "pr_merged",
                    "prNumber": pr_number,
                    "prTitle": pr_title,
                })
                logger.info(
                    f"[GitHub Tracker] PR #{pr_number} merged → "
                    f"WorkItem '{wi.title}' ({wi.external_id}): "
                    f"{old_status} → DONE"
                )

    # ── Action: PR Opened → Move to IN_PROGRESS (if still in backlog) ──
    elif action == "opened":
        for wi in work_items:
            if wi.status in BACKLOG_STATUSES:
                old_status = wi.status
                wi.status = "IN_PROGRESS"
                wi.source_status = "In Progress"
                items_updated.append({
                    "workItemId": wi.id,
                    "externalId": wi.external_id,
                    "title": wi.title,
                    "oldStatus": old_status,
                    "newStatus": "IN_PROGRESS",
                    "trigger": "pr_opened",
                    "prNumber": pr_number,
                    "prTitle": pr_title,
                })

    # ── Action: Review submitted (approved) → Move to IN_REVIEW ──
    elif action == "submitted":
        review = payload.get("review", {})
        review_state = review.get("state", "")
        if review_state == "approved":
            for wi in work_items:
                if wi.status in IN_PROGRESS_STATUSES:
                    old_status = wi.status
                    wi.status = "IN_REVIEW"
                    wi.source_status = "In Review"
                    items_updated.append({
                        "workItemId": wi.id,
                        "externalId": wi.external_id,
                        "title": wi.title,
                        "oldStatus": old_status,
                        "newStatus": "IN_REVIEW",
                        "trigger": "review_approved",
                        "prNumber": pr_number,
                    })

    # ── Update or create PullRequest record in DB ──
    if repo:
        try:
            existing_pr = await db.execute(
                select(PullRequest).where(
                    PullRequest.repository_id == repo.id,
                    PullRequest.external_id == str(pr_data.get("id", "")),
                )
            )
            pr_record = existing_pr.scalar_one_or_none()

            pr_status = "MERGED" if is_merged else (
                "CLOSED" if pr_state == "closed" else "OPEN"
            )

            # Link to first matching work item
            linked_wi_id = work_items[0].id if work_items else None

            if pr_record:
                pr_record.status = pr_status
                pr_record.linked_work_item_id = (
                    linked_wi_id or pr_record.linked_work_item_id
                )
                if merged_at:
                    pr_record.merged_at = datetime.fromisoformat(
                        merged_at.replace("Z", "+00:00")
                    )
            else:
                created_at_str = pr_data.get("created_at", "")
                new_pr = PullRequest(
                    id=generate_cuid(),
                    repository_id=repo.id,
                    external_id=str(pr_data.get("id", "")),
                    number=pr_number,
                    title=pr_title[:500],
                    status=pr_status,
                    author_id=member.id if member else None,
                    reviewers=[],
                    ci_status="UNKNOWN",
                    linked_work_item_id=linked_wi_id,
                    url=pr_url,
                    created_external_at=(
                        datetime.fromisoformat(
                            created_at_str.replace("Z", "+00:00")
                        )
                        if created_at_str
                        else datetime.now(timezone.utc)
                    ),
                    merged_at=(
                        datetime.fromisoformat(
                            merged_at.replace("Z", "+00:00")
                        )
                        if merged_at
                        else None
                    ),
                )
                db.add(new_pr)
        except Exception as e:
            logger.warning(f"Failed to upsert PR #{pr_number}: {e}")

    # Record activity event
    if member:
        try:
            event_type = {
                "opened": "pull_request",
                "closed": "pull_request_merged" if is_merged else "pull_request_closed",
                "submitted": "review",
            }.get(action, f"pull_request_{action}")

            from .activity_engine import record_activity
            await record_activity(
                db=db,
                org_id=org_id,
                team_member_id=member.id,
                event_type=event_type,
                source_tool="github",
                occurred_at=datetime.now(timezone.utc),
                external_id=str(pr_number),
                linked_ticket_id=ticket_refs[0] if ticket_refs else None,
                metadata={
                    "action": action,
                    "prNumber": pr_number,
                    "prTitle": pr_title[:200],
                    "repo": repo_name,
                    "merged": is_merged,
                    "ticketRefs": ticket_refs,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to record PR activity: {e}")

    await db.flush()

    summary = {
        "event": "pull_request",
        "action": action,
        "repo": repo_name,
        "prNumber": pr_number,
        "prTitle": pr_title,
        "isMerged": is_merged,
        "itemsUpdated": len(items_updated),
        "transitions": items_updated,
        "ticketRefs": ticket_refs,
    }

    if items_updated:
        logger.info(
            f"[GitHub Tracker] PR #{pr_number} ({action}): "
            f"{len(items_updated)} work items updated"
        )

    return summary


# ---------------------------------------------------------------------------
# CHECK RUN / CHECK SUITE EVENT HANDLER
# ---------------------------------------------------------------------------

async def process_check_event(
    db: AsyncSession,
    org_id: str,
    payload: dict,
) -> dict[str, Any]:
    """
    Process check_run or check_suite events to update CI status on PRs.
    """
    check_run = payload.get("check_run") or payload.get("check_suite", {})
    conclusion = check_run.get("conclusion", "")
    status = check_run.get("status", "")

    # Map GitHub conclusions to our CI status
    ci_status = "UNKNOWN"
    if conclusion == "success":
        ci_status = "PASSING"
    elif conclusion in ("failure", "timed_out"):
        ci_status = "FAILING"
    elif status in ("queued", "in_progress"):
        ci_status = "PENDING"

    # Find associated PRs from check_run.pull_requests
    prs_updated = 0
    for pr_ref in check_run.get("pull_requests", []):
        pr_number = pr_ref.get("number")
        if pr_number:
            result = await db.execute(
                select(PullRequest).where(
                    PullRequest.number == pr_number,
                )
            )
            pr_record = result.scalar_one_or_none()
            if pr_record:
                pr_record.ci_status = ci_status
                prs_updated += 1

    await db.flush()

    return {
        "event": "check",
        "conclusion": conclusion,
        "ciStatus": ci_status,
        "prsUpdated": prs_updated,
    }

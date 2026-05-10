"""
GitHub API endpoints.

GET  /api/github           – Pull-request list (developer dashboard)
GET  /api/github/overview  – Aggregate stats: repos, open PRs, merged PRs, commits
GET  /api/github/activity  – Activity feed with developer / type / time-range filters
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query as Q
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Date, column
from sqlalchemy.orm import selectinload

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models import (
    PullRequest,
    Repository,
    Commit,
    TeamMember,
    Iteration,
    ActivityEvent,
)
from ..models.work_item import WorkItem

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_active_sprint_dates(
    db: AsyncSession,
    org_id: str,
) -> tuple[datetime, datetime, Optional[str]]:
    """Return (start, end, name) for the active sprint, or 14-day fallback."""
    result = await db.execute(
        select(Iteration)
        .where(
            Iteration.organization_id == org_id,
            Iteration.state == "active",
        )
        .order_by(Iteration.start_date.desc())
        .limit(1)
    )
    sprint = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if sprint:
        return sprint.start_date, sprint.end_date, sprint.name
    return now - timedelta(days=14), now, None


def _format_event_description(event: ActivityEvent) -> str:
    """Human-readable description from event_type + metadata JSON."""
    meta = event.metadata_ or {}
    et = (event.event_type or "").lower()

    if et in ("push", "commit_pushed"):
        count = meta.get("commit_count", 1)
        branch = meta.get("branch", "")
        suffix = f" to {branch}" if branch else ""
        return f"Pushed {count} commit{'s' if count != 1 else ''}{suffix}"

    if et in ("pull_request", "pr_opened"):
        title = meta.get("title", "")
        return f"Opened PR: {title}" if title else "Opened a pull request"

    if et == "pr_merged":
        title = meta.get("title", "")
        return f"Merged PR: {title}" if title else "Merged a pull request"

    if et in ("review", "pr_reviewed"):
        title = meta.get("title", "")
        pr_num = meta.get("pr_number", "")
        if title:
            return f"Reviewed PR: {title}"
        if pr_num:
            return f"Submitted review on PR #{pr_num}"
        return "Reviewed a pull request"

    if et == "comment":
        context = meta.get("context", "an item")
        return f"Commented on {context}"

    if et == "create":
        ref_type = meta.get("ref_type", "branch")
        ref = meta.get("ref", "")
        return f"Created {ref_type}: {ref}" if ref else f"Created a {ref_type}"

    if et == "delete":
        ref_type = meta.get("ref_type", "branch")
        ref = meta.get("ref", "")
        return f"Deleted {ref_type}: {ref}" if ref else f"Deleted a {ref_type}"

    if et == "release":
        tag = meta.get("tag_name", "")
        return f"Published release {tag}" if tag else "Published a release"

    return meta.get("description", f"{event.event_type} event")


# ---------------------------------------------------------------------------
# GET /github/project-developers
# ---------------------------------------------------------------------------

@router.get("/github/project-developers")
async def get_project_developers(
    project_id: Optional[str] = Q(None, description="ImportedProject ID"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return developers for a project with their GitHub link status.

    Hotfix 39 — back to project-scoped developers. The PO wants the
    dropdown to show only developers on the currently-selected project.
    But we ALSO promote a GitHub link from another project of the same
    person: if a dev linked GitHub on Plan2Sprint and they're also a
    TeamMember on MediCare, MediCare's GitHub Monitoring should still
    show their link as connected (the link is a property of the person,
    not the row). We do this by:
      1. Scoping the visible developer list by ``imported_project_id``.
      2. For each row, checking the GitHub link on ANY TeamMember row in
         the same org that shares this email — if any row is linked,
         the displayed row is shown as linked.
    """
    org_id = current_user.get("organization_id", "demo-org")

    filters = [
        TeamMember.organization_id == org_id,
        TeamMember.role != "excluded",
    ]
    if project_id:
        filters.append(TeamMember.imported_project_id == project_id)

    result = await db.execute(
        select(TeamMember)
        .where(*filters)
        .order_by(TeamMember.display_name)
    )
    members = result.scalars().all()

    # Hotfix 39 — promote cross-project GitHub link by email. Build an
    # email → (github_username, github_access_token) lookup over the
    # ENTIRE org so a person whose link lives on another project is
    # still shown as linked here. Without this, switching projects
    # would falsely show "not linked" for a dev who's already
    # connected.
    org_members_q = await db.execute(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
        )
    )
    link_by_email: dict[str, tuple[str | None, str | None]] = {}
    for tm in org_members_q.scalars().all():
        if not tm.email or not tm.github_username:
            continue
        key = tm.email.lower()
        if key not in link_by_email or not link_by_email[key][0]:
            link_by_email[key] = (tm.github_username, tm.github_access_token)

    developers = []
    seen_emails: set[str] = set()
    for m in members:
        email_key = (m.email or "").lower()
        # Dedupe within this project by email — same person across
        # multiple iterations shouldn't appear twice.
        if email_key and email_key in seen_emails:
            continue
        if email_key:
            seen_emails.add(email_key)
        # Prefer this row's own link, fall back to any same-email row
        # in the org that has a link.
        gh_username = m.github_username
        gh_token = m.github_access_token
        if (not gh_username or not gh_token) and email_key in link_by_email:
            promoted = link_by_email[email_key]
            gh_username = gh_username or promoted[0]
            gh_token = gh_token or promoted[1]
        developers.append({
            "id": m.id,
            "name": m.display_name,
            "avatarUrl": m.avatar_url,
            "email": m.email,
            "githubUsername": gh_username,
            "githubLinked": bool(gh_username and gh_token),
        })

    # Linked devs first, then by name.
    developers.sort(key=lambda d: (not d["githubLinked"], (d["name"] or "").lower()))
    return {"developers": developers}


# ---------------------------------------------------------------------------
# GET /github/overview
# ---------------------------------------------------------------------------

@router.get("/github/overview")
async def get_github_overview(
    developer: Optional[str] = Q(None, description="TeamMember ID to scope stats to"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import httpx
    from ..models.tool_connection import ToolConnection

    org_id = current_user.get("organization_id", "demo-org")
    now = datetime.now(timezone.utc)

    sprint_start, sprint_end, sprint_name = await _get_active_sprint_dates(db, org_id)

    # Check for per-developer token
    dev_token: str | None = None
    dev_username: str | None = None
    if developer:
        dev_result = await db.execute(
            select(TeamMember).where(TeamMember.id == developer)
        )
        dev_member = dev_result.scalar_one_or_none()
        if dev_member and dev_member.github_access_token:
            dev_token = dev_member.github_access_token
            dev_username = dev_member.github_username

    # 1. Repos count (from DB)
    repo_count = (
        await db.execute(
            select(func.count())
            .select_from(Repository)
            .where(Repository.organization_id == org_id)
        )
    ).scalar() or 0

    # Auto-sync: if no repos in DB but linked repos exist, trigger sync
    if repo_count == 0:
        import logging
        _conn_check = await db.execute(
            select(ToolConnection).where(
                ToolConnection.organization_id == org_id,
                ToolConnection.source_tool == "GITHUB",
            )
        )
        _gh_check = _conn_check.scalar_one_or_none()
        if _gh_check and (_gh_check.config or {}).get("linked_repos"):
            logging.getLogger(__name__).info(f"Auto-triggering GitHub sync for org {org_id}")
            try:
                await _run_github_sync(db, org_id)
                repo_count = (
                    await db.execute(
                        select(func.count())
                        .select_from(Repository)
                        .where(Repository.organization_id == org_id)
                    )
                ).scalar() or 0
            except Exception as e:
                logging.getLogger(__name__).warning(f"Auto-sync failed: {e}")

    # 2-4. Try live GitHub data for PRs + commits
    open_prs = 0
    merged_prs = 0
    commits_7d = 0

    conn_result = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == "GITHUB",
        )
    )
    gh_conn = conn_result.scalar_one_or_none()

    # Use per-developer token if available, else fall back to org-level
    overview_token = dev_token or (gh_conn.access_token if gh_conn else None)

    if overview_token:
        config = gh_conn.config if gh_conn else {}
        linked_repos: list[str] = (config or {}).get("linked_repos", [])

        # Fallback to Repository table
        if not linked_repos:
            repo_result = await db.execute(
                select(Repository.full_name).where(
                    Repository.organization_id == org_id
                )
            )
            linked_repos = [r[0] for r in repo_result.all() if r[0]]

        # Use linked repos count as the real repo count when live
        if linked_repos:
            repo_count = len(linked_repos)
            gh_headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"Bearer {overview_token}",
            }
            seven_days_ago = now - timedelta(days=7)

            async with httpx.AsyncClient(timeout=20.0) as client:
                for repo_full_name in linked_repos:
                    try:
                        # Fetch PRs
                        pr_res = await client.get(
                            f"https://api.github.com/repos/{repo_full_name}/pulls",
                            params={"state": "all", "per_page": 50, "sort": "updated", "direction": "desc"},
                            headers=gh_headers,
                        )
                        if pr_res.is_success:
                            for pr in pr_res.json():
                                state = pr.get("state", "")
                                merged = pr.get("merged_at")
                                if state == "open":
                                    open_prs += 1
                                elif merged:
                                    try:
                                        merged_dt = datetime.fromisoformat(merged.replace("Z", "+00:00"))
                                        if merged_dt >= sprint_start:
                                            merged_prs += 1
                                    except (ValueError, TypeError):
                                        pass

                        # Fetch commits (last 7 days)
                        commit_res = await client.get(
                            f"https://api.github.com/repos/{repo_full_name}/commits",
                            params={"since": seven_days_ago.isoformat(), "per_page": 100},
                            headers=gh_headers,
                        )
                        if commit_res.is_success:
                            commits_7d += len(commit_res.json())
                    except httpx.RequestError:
                        continue
    else:
        # DB fallback (original code)
        open_prs = (
            await db.execute(
                select(func.count())
                .select_from(PullRequest)
                .join(Repository, PullRequest.repository_id == Repository.id)
                .where(
                    Repository.organization_id == org_id,
                    PullRequest.status.in_(
                        ["OPEN", "AWAITING_REVIEW", "CHANGES_REQUESTED", "APPROVED"]
                    ),
                    PullRequest.created_external_at >= sprint_start,
                    PullRequest.created_external_at <= sprint_end,
                )
            )
        ).scalar() or 0

        merged_prs = (
            await db.execute(
                select(func.count())
                .select_from(PullRequest)
                .join(Repository, PullRequest.repository_id == Repository.id)
                .where(
                    Repository.organization_id == org_id,
                    PullRequest.status == "MERGED",
                    PullRequest.merged_at >= sprint_start,
                    PullRequest.merged_at <= sprint_end,
                )
            )
        ).scalar() or 0

        seven_days_ago = now - timedelta(days=7)
        commits_7d = (
            await db.execute(
                select(func.count())
                .select_from(Commit)
                .join(Repository, Commit.repository_id == Repository.id)
                .where(
                    Repository.organization_id == org_id,
                    Commit.committed_at >= seven_days_ago,
                )
            )
        ).scalar() or 0

    return {
        "repos": repo_count,
        "openPrs": open_prs,
        "mergedPrs": merged_prs,
        "commitsLast7d": commits_7d,
        "sprintName": sprint_name,
        "sprintStart": sprint_start.isoformat(),
        "sprintEnd": sprint_end.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /github/activity
# ---------------------------------------------------------------------------

@router.get("/github/activity")
async def get_github_activity(
    developer: Optional[str] = Q(None, description="TeamMember ID filter"),
    type: Optional[str] = Q(None, description="Event type filter"),
    timeRange: str = Q("7d", description="Time range: today | 7d | 30d | sprint"),
    project_id: Optional[str] = Q(None, description="Filter by project"),
    limit: int = Q(50, ge=1, le=200),
    offset: int = Q(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activity feed that fetches LIVE from GitHub API using stored token.

    Falls back to the ActivityEvent DB table if no stored token exists.
    """
    import httpx
    from ..models.tool_connection import ToolConnection
    from ..models.repository import Repository

    org_id = current_user.get("organization_id", "demo-org")
    now = datetime.now(timezone.utc)

    # Resolve time range for filtering
    if timeRange == "today":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif timeRange == "30d":
        since = now - timedelta(days=30)
    elif timeRange == "sprint":
        since, _, _ = await _get_active_sprint_dates(db, org_id)
    else:  # default "7d"
        since = now - timedelta(days=7)

    # Hotfix 39 — back to project-scoped activity. PO wants
    # developers + their commits/PRs filtered to the current project.
    member_filters = [
        TeamMember.organization_id == org_id,
        TeamMember.role != "excluded",
    ]
    if project_id:
        member_filters.append(TeamMember.imported_project_id == project_id)

    members_result = await db.execute(
        select(TeamMember)
        .where(*member_filters)
        .order_by(TeamMember.display_name)
    )
    members = members_result.scalars().all()
    team_members_resp = [
        {"id": m.id, "name": m.display_name, "avatarUrl": m.avatar_url}
        for m in members
    ]

    # Build a name/login → TeamMember lookup
    name_to_member: dict[str, TeamMember] = {}
    for m in members:
        if m.display_name:
            name_to_member[m.display_name.lower()] = m
        if m.external_id:
            name_to_member[m.external_id.lower()] = m
        if m.email:
            name_to_member[m.email.lower()] = m
        if getattr(m, "github_username", None):
            name_to_member[m.github_username.lower()] = m

    # Get developer name filter if filtering by developer ID
    filter_dev_name = ""
    selected_member: TeamMember | None = None
    if developer:
        for m in members:
            if m.id == developer:
                filter_dev_name = (m.display_name or "").lower()
                selected_member = m
                # Also add github_username to the lookup
                if m.github_username:
                    name_to_member[m.github_username.lower()] = m
                break

    # Determine which token and repos to use:
    # Priority: per-developer token > org-level token
    use_token: str | None = None
    linked_repos: list[str] = []
    developer_not_linked = False

    if selected_member and selected_member.github_access_token:
        # Per-developer token — fetch their repos dynamically
        use_token = selected_member.github_access_token
        # We'll fetch repos from their account below
    elif selected_member and not selected_member.github_access_token:
        # Developer hasn't linked GitHub
        developer_not_linked = True

    # Fallback to org-level connection
    conn_result = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == "GITHUB",
        )
    )
    gh_conn = conn_result.scalar_one_or_none()

    if not use_token and gh_conn and gh_conn.access_token:
        use_token = gh_conn.access_token
        config = gh_conn.config or {}
        # Hotfix 6 — prefer the selected developer's per-user repo bucket
        # if we have one. Falls back to the org-wide union otherwise.
        repos_by_user = config.get("linked_repos_by_user") or {}
        if (
            selected_member
            and selected_member.github_username
            and selected_member.github_username in repos_by_user
        ):
            linked_repos = list(repos_by_user[selected_member.github_username])
        else:
            linked_repos = config.get("linked_repos", [])

    # If specific developer selected but not linked, return early
    if developer_not_linked and not use_token:
        return {
            "events": [],
            "teamMembers": team_members_resp,
            "totalCount": 0,
            "developerNotLinked": True,
        }

    if use_token:
        # Get linked repos from config or from Repository table
        config = gh_conn.config if gh_conn else {}
        if not linked_repos:
            # Hotfix 6 — prefer per-user bucket here too, in the per-
            # developer-token branch (use_token came from selected_member).
            repos_by_user = (config or {}).get("linked_repos_by_user") or {}
            if (
                selected_member
                and selected_member.github_username
                and selected_member.github_username in repos_by_user
            ):
                linked_repos = list(
                    repos_by_user[selected_member.github_username]
                )
            else:
                linked_repos = (config or {}).get("linked_repos", [])

        # Map GitHub login from ToolConnection to a team member
        gh_user_login = config.get("user_login", "")
        gh_user_name = config.get("user_name", "")
        if gh_user_login and gh_user_login.lower() not in name_to_member:
            # Try matching by the stored display name from GitHub
            matched = None
            if gh_user_name:
                matched = name_to_member.get(gh_user_name.lower())
            if matched:
                name_to_member[gh_user_login.lower()] = matched

        # Also get repos from Repository table as fallback
        if not linked_repos:
            repo_result = await db.execute(
                select(Repository.full_name).where(
                    Repository.organization_id == org_id
                )
            )
            linked_repos = [r[0] for r in repo_result.all() if r[0]]

        # If using per-developer token and no linked repos, fetch their repos
        if selected_member and selected_member.github_access_token and not linked_repos:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=15.0) as _client:
                try:
                    _resp = await _client.get(
                        "https://api.github.com/user/repos",
                        params={"per_page": 50, "affiliation": "owner,collaborator,organization_member"},
                        headers={"Accept": "application/vnd.github.v3+json", "Authorization": f"Bearer {use_token}"},
                    )
                    if _resp.is_success:
                        linked_repos = [r["full_name"] for r in _resp.json() if r.get("full_name")]
                except Exception:
                    pass

        if linked_repos:
            all_events: list[dict] = []
            seen_ids: set[str] = set()  # dedup between events + commits
            gh_headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"Bearer {use_token}",
            }

            # Helper to resolve actor → developer info
            def _resolve_dev(login: str, avatar: str = ""):
                member = name_to_member.get(login.lower()) if login else None
                return {
                    "id": member.id if member else "",
                    "name": member.display_name if member else login,
                    "avatar": (member.avatar_url if member and member.avatar_url else avatar),
                }

            # Helper to compute time flags
            def _time_flags(iso: str):
                try:
                    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                    return dt.hour < 8 or dt.hour >= 20, dt.weekday() >= 5
                except (ValueError, TypeError, AttributeError):
                    return False, False

            # Helper to check time range
            def _in_range(iso: str) -> bool:
                if not iso:
                    return True
                try:
                    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                    return dt >= since
                except (ValueError, TypeError):
                    return True

            async with httpx.AsyncClient(timeout=30.0) as client:
                for repo_full_name in linked_repos:
                    # ---- 1) Fetch COMMITS (most reliable for activity) ----
                    try:
                        commit_res = await client.get(
                            f"https://api.github.com/repos/{repo_full_name}/commits",
                            params={"since": since.isoformat(), "per_page": 100},
                            headers=gh_headers,
                        )
                        if commit_res.is_success:
                            for c in commit_res.json():
                                sha = c.get("sha", "")
                                cid = f"commit-{sha[:12]}"
                                if cid in seen_ids:
                                    continue
                                seen_ids.add(cid)

                                commit_data = c.get("commit") or {}
                                author_info = c.get("author") or {}
                                committer_info = commit_data.get("author") or {}
                                login = author_info.get("login", "")
                                avatar = author_info.get("avatar_url", "")
                                name = committer_info.get("name", login)
                                message = commit_data.get("message", "")
                                date = committer_info.get("date", "")

                                if not _in_range(date):
                                    continue
                                if type and type != "push":
                                    continue

                                dev = _resolve_dev(login or name, avatar)

                                if developer and dev["id"] != developer:
                                    if filter_dev_name and (login or name).lower() != filter_dev_name:
                                        continue

                                after_h, weekend = _time_flags(date)
                                first_line = message.split("\n")[0][:120]

                                all_events.append({
                                    "id": cid,
                                    "eventType": "push",
                                    "developerId": dev["id"],
                                    "developerName": dev["name"],
                                    "developerAvatar": dev["avatar"],
                                    "description": f"Committed: {first_line}",
                                    "repo": repo_full_name,
                                    "metadata": {
                                        "sha": sha[:7],
                                        "rawType": "Commit",
                                        "branch": "",
                                        "actor": login or name,
                                    },
                                    "occurredAt": date,
                                    "isAfterHours": after_h,
                                    "isWeekend": weekend,
                                })
                    except httpx.RequestError:
                        pass

                    # ---- 2) Fetch EVENTS (PRs, reviews, branches etc.) ----
                    try:
                        res = await client.get(
                            f"https://api.github.com/repos/{repo_full_name}/events",
                            params={"per_page": 50},
                            headers=gh_headers,
                        )
                        if res.is_error:
                            continue
                        data = res.json()

                        for event in data:
                            eid = str(event.get("id", ""))
                            if eid in seen_ids:
                                continue

                            payload = event.get("payload") or {}
                            raw_type = event.get("type", "Unknown")
                            actor = event.get("actor") or {}
                            actor_login = actor.get("login", "Unknown")
                            actor_avatar = actor.get("avatar_url", "")
                            created_at = event.get("created_at", "")
                            branch = (payload.get("ref") or "").replace(
                                "refs/heads/", ""
                            )

                            # Skip PushEvents — we already have individual commits
                            if raw_type == "PushEvent":
                                continue

                            event_type = "other"
                            description = ""

                            if raw_type == "PullRequestEvent":
                                pr = payload.get("pull_request") or {}
                                action = payload.get("action", "updated")
                                description = f"{action} PR #{pr.get('number')}: {pr.get('title', '')}"
                                event_type = "pull_request"
                            elif raw_type == "CreateEvent":
                                description = f"Created {payload.get('ref_type', 'ref')} {payload.get('ref', '')}"
                                event_type = "create"
                            elif raw_type == "DeleteEvent":
                                description = f"Deleted {payload.get('ref_type', 'ref')} {payload.get('ref', '')}"
                                event_type = "delete"
                            elif raw_type == "IssueCommentEvent":
                                issue = payload.get("issue") or {}
                                description = f"Commented on #{issue.get('number')}: {issue.get('title', '')}"
                                event_type = "comment"
                            elif raw_type == "PullRequestReviewEvent":
                                pr = payload.get("pull_request") or {}
                                review = payload.get("review") or {}
                                description = f"Reviewed PR #{pr.get('number')}: {review.get('state', '')}"
                                event_type = "review"
                            elif raw_type == "ReleaseEvent":
                                release = payload.get("release") or {}
                                description = f"Published release {release.get('tag_name', '')}"
                                event_type = "release"
                            else:
                                description = raw_type.replace("Event", "") if raw_type else "Activity"

                            if not _in_range(created_at):
                                continue
                            if type and event_type != type:
                                continue

                            dev = _resolve_dev(actor_login, actor_avatar)

                            if developer and dev["id"] != developer:
                                if filter_dev_name and actor_login.lower() != filter_dev_name:
                                    continue

                            after_h, weekend = _time_flags(created_at)
                            seen_ids.add(eid)

                            all_events.append({
                                "id": eid,
                                "eventType": event_type,
                                "developerId": dev["id"],
                                "developerName": dev["name"],
                                "developerAvatar": dev["avatar"],
                                "description": description,
                                "repo": repo_full_name,
                                "metadata": {
                                    "rawType": raw_type,
                                    "branch": branch,
                                    "actor": actor_login,
                                },
                                "occurredAt": created_at,
                                "isAfterHours": after_h,
                                "isWeekend": weekend,
                            })
                    except httpx.RequestError:
                        continue

            # Filter events to only include project members when project_id is set
            if project_id:
                project_member_ids = {m.id for m in members}
                all_events = [
                    e for e in all_events
                    if e.get("developerId") in project_member_ids
                    or e.get("developerId") == "unknown"
                ]

            # Sort by date descending
            all_events.sort(
                key=lambda x: x.get("occurredAt") or "", reverse=True
            )

            # Apply offset + limit
            paged = all_events[offset : offset + limit]

            return {
                "events": paged,
                "teamMembers": team_members_resp,
                "totalCount": len(all_events),
            }

    # ---- Fallback: read from ActivityEvent DB table ----
    query = (
        select(ActivityEvent)
        .where(
            ActivityEvent.organization_id == org_id,
            ActivityEvent.source_tool == "GITHUB",
            ActivityEvent.occurred_at >= since,
        )
        .options(selectinload(ActivityEvent.team_member))
        .order_by(ActivityEvent.occurred_at.desc())
    )

    if developer:
        query = query.where(ActivityEvent.team_member_id == developer)
    if type:
        query = query.where(ActivityEvent.event_type == type)

    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    events = result.scalars().all()

    return {
        "events": [
            {
                "id": e.id,
                "eventType": e.event_type,
                "developerId": e.team_member_id,
                "developerName": (
                    e.team_member.display_name if e.team_member else "Unknown"
                ),
                "developerAvatar": (
                    e.team_member.avatar_url if e.team_member else None
                ),
                "description": _format_event_description(e),
                "repo": (e.metadata_ or {}).get("repo", ""),
                "metadata": e.metadata_,
                "occurredAt": (
                    e.occurred_at.isoformat() if e.occurred_at else None
                ),
                "isAfterHours": e.is_after_hours,
                "isWeekend": e.is_weekend,
            }
            for e in events
        ],
        "teamMembers": team_members_resp,
        "totalCount": len(events),
    }


# ---------------------------------------------------------------------------
# GET /github  (existing – PR list for developer dashboard)
# ---------------------------------------------------------------------------

@router.get("/github")
async def get_github_prs(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")

    query = (
        select(PullRequest)
        .join(Repository, PullRequest.repository_id == Repository.id)
        .where(Repository.organization_id == org_id)
        .options(
            selectinload(PullRequest.author),
            selectinload(PullRequest.repository),
        )
        .order_by(PullRequest.created_external_at.desc())
        .limit(20)
    )
    result = await db.execute(query)
    prs = result.scalars().all()

    pr_list = []
    for pr in prs:
        pr_list.append({
            "id": pr.id,
            "number": pr.number,
            "title": pr.title,
            "status": pr.status,
            "author": pr.author.display_name if pr.author else "Unknown",
            "repo": pr.repository.name if pr.repository else "unknown",
            "ciStatus": pr.ci_status,
            "reviewers": pr.reviewers or [],
            "createdAt": pr.created_external_at.isoformat() if pr.created_external_at else None,
        })

    return {"pullRequests": pr_list}


# ---------------------------------------------------------------------------
# POST /github/sync  — Pull commits, PRs, repos from GitHub API → persist to DB
# ---------------------------------------------------------------------------

async def _run_github_sync(db: AsyncSession, org_id: str) -> dict:
    """Core sync logic — fetch commits, PRs, repos from GitHub API → persist to DB."""
    import httpx
    import logging
    from ..models.tool_connection import ToolConnection
    from ..models.base import generate_cuid
    from ..services.activity_engine import record_activity

    logger = logging.getLogger(__name__)

    conn_result = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == "GITHUB",
        )
    )
    gh_conn = conn_result.scalar_one_or_none()
    if not gh_conn or not gh_conn.access_token:
        return {"ok": False, "error": "GitHub not connected"}

    config = gh_conn.config or {}
    linked_repos: list[str] = config.get("linked_repos", [])
    if not linked_repos:
        return {"ok": False, "error": "No repos linked"}

    token = gh_conn.access_token
    gh_headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
    }

    members_result = await db.execute(
        select(TeamMember).where(TeamMember.organization_id == org_id)
    )
    all_members = members_result.scalars().all()
    gh_user_map: dict[str, TeamMember] = {}
    name_map: dict[str, TeamMember] = {}
    for m in all_members:
        if m.github_username:
            gh_user_map[m.github_username.lower()] = m
        name_map[m.display_name.lower()] = m

    stats = {"repos": 0, "commits": 0, "prs": 0, "events": 0}
    now = datetime.now(timezone.utc)
    since_date = now - timedelta(days=90)

    async with httpx.AsyncClient(timeout=30.0) as client:
        for repo_full_name in linked_repos:
            try:
                # ── 1. Upsert Repository record ──
                repo_api_res = await client.get(
                    f"https://api.github.com/repos/{repo_full_name}",
                    headers=gh_headers,
                )
                if not repo_api_res.is_success:
                    logger.warning(f"GitHub sync: failed to fetch repo {repo_full_name}: {repo_api_res.status_code}")
                    continue

                repo_data = repo_api_res.json()
                ext_id = str(repo_data["id"])

                existing_repo = await db.execute(
                    select(Repository).where(
                        Repository.organization_id == org_id,
                        Repository.external_id == ext_id,
                    )
                )
                repo_record = existing_repo.scalar_one_or_none()
                if not repo_record:
                    repo_record = Repository(
                        id=generate_cuid(),
                        organization_id=org_id,
                        external_id=ext_id,
                        name=repo_data.get("name", repo_full_name.split("/")[-1]),
                        full_name=repo_full_name,
                        default_branch=repo_data.get("default_branch", "main"),
                        url=repo_data.get("html_url", f"https://github.com/{repo_full_name}"),
                    )
                    db.add(repo_record)
                    await db.flush()
                stats["repos"] += 1

                # ── 2. Fetch and persist commits ──
                page = 1
                while page <= 5:  # Max 5 pages (500 commits)
                    commit_res = await client.get(
                        f"https://api.github.com/repos/{repo_full_name}/commits",
                        params={"since": since_date.isoformat(), "per_page": 100, "page": page},
                        headers=gh_headers,
                    )
                    if not commit_res.is_success:
                        break
                    commits_data = commit_res.json()
                    if not commits_data:
                        break

                    for c in commits_data:
                        sha = c.get("sha", "")
                        if not sha:
                            continue

                        # Check if commit already exists
                        existing_commit = await db.execute(
                            select(Commit).where(
                                Commit.repository_id == repo_record.id,
                                Commit.sha == sha,
                            )
                        )
                        if existing_commit.scalar_one_or_none():
                            continue  # Already synced

                        # Match author to TeamMember
                        author_login = (c.get("author") or {}).get("login", "")
                        commit_info = c.get("commit", {})
                        author_name = (commit_info.get("author") or {}).get("name", "")
                        committed_at_str = (commit_info.get("author") or {}).get("date", "")

                        member = gh_user_map.get(author_login.lower()) if author_login else None
                        if not member and author_name:
                            member = name_map.get(author_name.lower())

                        try:
                            committed_at = datetime.fromisoformat(committed_at_str.replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            committed_at = now

                        commit_record = Commit(
                            id=generate_cuid(),
                            repository_id=repo_record.id,
                            sha=sha,
                            message=(commit_info.get("message") or "")[:500],
                            author_id=member.id if member else None,
                            branch=repo_record.default_branch,
                            linked_ticket_ids=[],
                            files_changed=0,
                            committed_at=committed_at,
                        )
                        db.add(commit_record)
                        stats["commits"] += 1

                        # Create ActivityEvent for team health tracking
                        if member:
                            await record_activity(
                                db=db,
                                org_id=org_id,
                                team_member_id=member.id,
                                event_type="push",
                                source_tool="github",
                                occurred_at=committed_at,
                                external_id=sha[:12],
                                metadata={
                                    "repo": repo_full_name,
                                    "message": (commit_info.get("message") or "")[:200],
                                    "author": author_login or author_name,
                                },
                            )
                            stats["events"] += 1

                    page += 1

                # ── 3. Fetch and persist PRs ──
                pr_res = await client.get(
                    f"https://api.github.com/repos/{repo_full_name}/pulls",
                    params={"state": "all", "per_page": 100, "sort": "updated", "direction": "desc"},
                    headers=gh_headers,
                )
                if pr_res.is_success:
                    for pr_data in pr_res.json():
                        pr_ext_id = str(pr_data["id"])

                        existing_pr = await db.execute(
                            select(PullRequest).where(
                                PullRequest.repository_id == repo_record.id,
                                PullRequest.external_id == pr_ext_id,
                            )
                        )
                        if existing_pr.scalar_one_or_none():
                            continue

                        pr_author_login = (pr_data.get("user") or {}).get("login", "")
                        pr_member = gh_user_map.get(pr_author_login.lower()) if pr_author_login else None

                        pr_state = pr_data.get("state", "open")
                        merged_at = pr_data.get("merged_at")
                        if merged_at:
                            status = "MERGED"
                        elif pr_state == "closed":
                            status = "CLOSED"
                        else:
                            status = "OPEN"

                        try:
                            created_at = datetime.fromisoformat(pr_data["created_at"].replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            created_at = now

                        try:
                            merged_dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00")) if merged_at else None
                        except (ValueError, TypeError):
                            merged_dt = None

                        pr_record = PullRequest(
                            id=generate_cuid(),
                            repository_id=repo_record.id,
                            external_id=pr_ext_id,
                            number=pr_data.get("number", 0),
                            title=(pr_data.get("title") or "")[:500],
                            status=status,
                            author_id=pr_member.id if pr_member else None,
                            reviewers=[],
                            ci_status="UNKNOWN",
                            url=pr_data.get("html_url", ""),
                            created_external_at=created_at,
                            merged_at=merged_dt,
                        )
                        db.add(pr_record)
                        stats["prs"] += 1

                        # Create activity event for PR
                        if pr_member:
                            event_type = "pr_merged" if status == "MERGED" else "pull_request"
                            await record_activity(
                                db=db,
                                org_id=org_id,
                                team_member_id=pr_member.id,
                                event_type=event_type,
                                source_tool="github",
                                occurred_at=merged_dt or created_at,
                                external_id=pr_ext_id,
                                metadata={
                                    "repo": repo_full_name,
                                    "title": (pr_data.get("title") or "")[:200],
                                    "number": pr_data.get("number"),
                                    "status": status,
                                },
                            )
                            stats["events"] += 1

            except httpx.RequestError as e:
                logger.warning(f"GitHub sync: request error for {repo_full_name}: {e}")
                continue

    await db.commit()

    logger.info(f"GitHub sync complete for org {org_id}: {stats}")
    return {"ok": True, "stats": stats}


@router.post("/github/sync")
async def sync_github_data(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /github/sync — Pull commits, PRs, repos from GitHub API → persist to DB."""
    org_id = current_user.get("organization_id", "demo-org")
    return await _run_github_sync(db, org_id)


# ---------------------------------------------------------------------------
# GET /github/sprint-overview — Hotfix 40
#
# Project-scoped sprint dashboard for the GitHub Monitoring page's
# "Sprint" tab. Combines:
#   * Story-PR linkage table  — each work_item in the active sprint paired
#                                with its matching PR(s) (linked_work_item_id
#                                or external_id mention in title/body).
#   * Daily commit heatmap    — day-by-day commit counts across the sprint
#                                window, scoped to repos this project's
#                                developers commit to.
#   * AI insights             — 3-5 short bullets generated from the data
#                                ("3 stories without a PR", "2 PRs idle in
#                                review > 3 days", etc.) using the same
#                                ai_caller failover that handles the rest.
# ---------------------------------------------------------------------------

@router.get("/github/sprint-overview")
async def get_github_sprint_overview(
    project_id: Optional[str] = Q(None, description="ImportedProject ID"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import re
    from collections import defaultdict
    org_id = current_user.get("organization_id", "demo-org")

    # ── 1. Resolve the active sprint (project-scoped if possible) ─────────
    iter_q = select(Iteration).where(Iteration.organization_id == org_id)
    if project_id:
        iter_q = iter_q.where(Iteration.imported_project_id == project_id)
    iter_q = iter_q.where(Iteration.state == "active").order_by(
        Iteration.start_date.desc()
    ).limit(1)
    iteration = (await db.execute(iter_q)).scalar_one_or_none()
    if not iteration:
        # Fall back to most-recent iteration so we still show *something*
        recent_q = select(Iteration).where(Iteration.organization_id == org_id)
        if project_id:
            recent_q = recent_q.where(Iteration.imported_project_id == project_id)
        recent_q = recent_q.order_by(Iteration.start_date.desc()).limit(1)
        iteration = (await db.execute(recent_q)).scalar_one_or_none()

    if not iteration:
        return {
            "sprint": None,
            "stories": [],
            "dailyCommits": [],
            "insights": [],
        }

    sprint_start = iteration.start_date
    sprint_end = iteration.end_date

    # ── 2. Stories in this sprint (filtered to project) ───────────────────
    wi_q = (
        select(WorkItem)
        .where(
            WorkItem.organization_id == org_id,
            WorkItem.iteration_id == iteration.id,
        )
    )
    if project_id:
        wi_q = wi_q.where(WorkItem.imported_project_id == project_id)
    wi_q = wi_q.order_by(WorkItem.priority.asc(), WorkItem.created_at.asc())
    stories = (await db.execute(wi_q)).scalars().all()
    story_external_ids = [s.external_id for s in stories if s.external_id]
    story_id_map: dict[str, WorkItem] = {s.id: s for s in stories}

    # ── 3. PRs from this org's developers in the sprint window ────────────
    # Match PRs to stories by:
    #   (a) PR.linked_work_item_id == story.id  (direct FK link), or
    #   (b) regex match of story.external_id in PR.title (case-insensitive).
    pr_q = (
        select(PullRequest, Repository)
        .join(Repository, PullRequest.repository_id == Repository.id)
        .where(
            Repository.organization_id == org_id,
            PullRequest.created_external_at >= sprint_start - timedelta(days=2),
        )
        .order_by(PullRequest.created_external_at.desc())
    )
    pr_rows = (await db.execute(pr_q)).all()

    # Build PR-to-story matching (story_id -> list of PRs)
    story_to_prs: dict[str, list[dict]] = defaultdict(list)
    if story_external_ids:
        # Compile a single regex that matches any story external_id
        # surrounded by word boundaries (e.g., "MED-12", but not "MED-123")
        pattern = re.compile(
            r"\b(" + "|".join(re.escape(ext_id) for ext_id in story_external_ids) + r")\b",
            re.IGNORECASE,
        )
    else:
        pattern = None

    now = datetime.now(timezone.utc)
    for pr, repo in pr_rows:
        # Direct FK link wins
        if pr.linked_work_item_id and pr.linked_work_item_id in story_id_map:
            story = story_id_map[pr.linked_work_item_id]
        elif pattern:
            m = pattern.search(pr.title or "")
            if not m:
                continue
            matched_ext = m.group(1).upper()
            story = next(
                (s for s in stories if s.external_id and s.external_id.upper() == matched_ext),
                None,
            )
            if not story:
                continue
        else:
            continue

        age_days = max(0, (now - pr.created_external_at).days) if pr.created_external_at else 0
        story_to_prs[story.id].append({
            "number": pr.number,
            "title": pr.title,
            "status": pr.status,
            "url": pr.url,
            "ageDays": age_days,
            "merged": bool(pr.merged_at),
            "ciStatus": pr.ci_status,
            "repoName": repo.name if repo else "",
        })

    # ── 4. Build the per-story output rows ────────────────────────────────
    story_rows: list[dict] = []
    counts = {"done": 0, "in_review": 0, "in_progress": 0, "no_pr": 0}
    for s in stories:
        prs = story_to_prs.get(s.id, [])
        merged_pr = next((p for p in prs if p["merged"]), None)
        open_pr = next((p for p in prs if p["status"].upper() == "OPEN" and not p["merged"]), None)

        if (s.status or "").upper() == "DONE" or merged_pr:
            badge = "done"
            counts["done"] += 1
        elif open_pr:
            badge = "in_review"
            counts["in_review"] += 1
        elif (s.status or "").upper() == "IN_PROGRESS":
            badge = "in_progress"
            counts["in_progress"] += 1
        else:
            badge = "no_pr"
            counts["no_pr"] += 1

        story_rows.append({
            "id": s.id,
            "externalId": s.external_id,
            "title": s.title,
            "type": s.type,
            "status": s.status,
            "storyPoints": s.story_points,
            "badge": badge,
            "prs": prs,
        })

    # ── 5. Daily commit heatmap ───────────────────────────────────────────
    # Org-scoped commits in the sprint window. Filter by author_id IN
    # this project's team_members so a multi-project org doesn't pollute
    # one project's heatmap with another project's commits.
    proj_tm_q = select(TeamMember.id).where(TeamMember.organization_id == org_id)
    if project_id:
        proj_tm_q = proj_tm_q.where(TeamMember.imported_project_id == project_id)
    project_tm_ids = [row[0] for row in (await db.execute(proj_tm_q)).all()]

    daily_commits: list[dict] = []
    if project_tm_ids:
        # Use cast(Date) so PostgreSQL groups consistently across SELECT / GROUP BY / ORDER BY.
        day_expr = cast(Commit.committed_at, Date).label("day")
        commit_q = (
            select(
                day_expr,
                func.count().label("cnt"),
            )
            .join(Repository, Commit.repository_id == Repository.id)
            .where(
                Repository.organization_id == org_id,
                Commit.author_id.in_(project_tm_ids),
                Commit.committed_at >= sprint_start,
                Commit.committed_at < sprint_end + timedelta(days=1),
            )
            .group_by(cast(Commit.committed_at, Date))
            .order_by(cast(Commit.committed_at, Date))
        )
        rows = (await db.execute(commit_q)).all()
        commits_by_day = {}
        for row in rows:
            d = row[0]
            iso = d.isoformat() if hasattr(d, "isoformat") else str(d)
            commits_by_day[iso] = row[1]
    else:
        commits_by_day = {}

    cursor = sprint_start.date()
    end_cursor = sprint_end.date()
    while cursor <= end_cursor:
        iso = cursor.isoformat()
        daily_commits.append({
            "date": iso,
            "count": int(commits_by_day.get(iso, 0)),
            "isToday": cursor == now.date(),
        })
        cursor = cursor + timedelta(days=1)

    # ── 6. AI insights — short bullets from the data ──────────────────────
    insights: list[str] = []
    # Static rule-based insights first (cheap, deterministic)
    total_commits = sum(d["count"] for d in daily_commits)
    days_into_sprint = max(0, (now.date() - sprint_start.date()).days)
    days_since_commit = 0
    for d in reversed(daily_commits):
        if d["count"] > 0:
            break
        days_since_commit += 1

    if total_commits == 0 and days_into_sprint > 1:
        insights.append(f"⚠ No commits yet in this sprint (day {days_into_sprint + 1}).")
    elif days_since_commit >= 3:
        insights.append(f"⚠ No commits in the last {days_since_commit} days.")

    if counts["no_pr"] > 0:
        no_pr_titles = [
            r["externalId"] or r["title"][:30]
            for r in story_rows[:3]
            if r["badge"] == "no_pr"
        ]
        suffix = f" ({', '.join(no_pr_titles)})" if no_pr_titles else ""
        insights.append(
            f"⚠ {counts['no_pr']} stor{'y' if counts['no_pr'] == 1 else 'ies'} without a PR yet{suffix}."
        )

    stale_review = [
        p for r in story_rows for p in r["prs"]
        if p["status"].upper() == "OPEN" and not p["merged"] and p["ageDays"] >= 3
    ]
    if stale_review:
        insights.append(
            f"⏳ {len(stale_review)} PR{'s' if len(stale_review) > 1 else ''} idle in review > 3 days."
        )

    if counts["done"] > 0:
        insights.append(f"✓ {counts['done']} stor{'y' if counts['done'] == 1 else 'ies'} delivered this sprint.")

    if not insights:
        insights.append("No notable signals — sprint is on track.")

    return {
        "sprint": {
            "id": iteration.id,
            "name": iteration.name,
            "startDate": sprint_start.isoformat(),
            "endDate": sprint_end.isoformat(),
            "state": iteration.state,
        },
        "stories": story_rows,
        "counts": counts,
        "dailyCommits": daily_commits,
        "totalCommits": total_commits,
        "insights": insights,
    }

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
from sqlalchemy import select, func
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
# GET /github/overview
# ---------------------------------------------------------------------------

@router.get("/github/overview")
async def get_github_overview(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import httpx
    from ..models.tool_connection import ToolConnection

    org_id = current_user.get("organization_id", "demo-org")
    now = datetime.now(timezone.utc)

    sprint_start, sprint_end, sprint_name = await _get_active_sprint_dates(db, org_id)

    # 1. Repos count (from DB)
    repo_count = (
        await db.execute(
            select(func.count())
            .select_from(Repository)
            .where(Repository.organization_id == org_id)
        )
    ).scalar() or 0

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

    if gh_conn and gh_conn.access_token:
        config = gh_conn.config or {}
        linked_repos: list[str] = config.get("linked_repos", [])

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
                "Authorization": f"Bearer {gh_conn.access_token}",
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

    # Team members for the developer dropdown + login→member mapping
    members_result = await db.execute(
        select(TeamMember)
        .where(TeamMember.organization_id == org_id)
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

    # Get developer name filter if filtering by developer ID
    filter_dev_name = ""
    if developer:
        for m in members:
            if m.id == developer:
                filter_dev_name = (m.display_name or "").lower()
                break

    # ---- Try LIVE fetch from GitHub API ----
    conn_result = await db.execute(
        select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == "GITHUB",
        )
    )
    gh_conn = conn_result.scalar_one_or_none()

    if gh_conn and gh_conn.access_token:
        # Get linked repos from config or from Repository table
        config = gh_conn.config or {}
        linked_repos: list[str] = config.get("linked_repos", [])

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

        if linked_repos:
            all_events: list[dict] = []
            seen_ids: set[str] = set()  # dedup between events + commits
            access_token = gh_conn.access_token
            gh_headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"Bearer {access_token}",
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

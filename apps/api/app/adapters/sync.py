"""
Sync service — upsert normalised records into the database.

All functions take a list of normalised dicts (output of normalizers.py)
and upsert them using INSERT ... ON CONFLICT DO UPDATE logic.

Foreign key resolution:
  - external_id lookups are done in-transaction to resolve
    _assigned_to_name → team_member.id, _sprint_id → iteration.id, etc.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..models.base import generate_cuid
from ..models.work_item import WorkItem
from ..models.iteration import Iteration
from ..models.team_member import TeamMember
from ..models.repository import Repository, PullRequest, Commit
from ..models.imported_project import ImportedProject

logger = logging.getLogger(__name__)


# =====================================================================
# TEAM MEMBERS
# =====================================================================

async def upsert_team_members(
    db: AsyncSession,
    members: list[dict],
    org_id: str,
) -> dict[str, str]:
    """
    Upsert team members and return a mapping of external_id → internal id.
    This mapping is used by subsequent upserts for FK resolution.
    """
    ext_to_id: dict[str, str] = {}

    for m in members:
        external_id = m["external_id"]
        if not external_id:
            continue

        # Check for existing
        result = await db.execute(
            select(TeamMember).where(
                TeamMember.organization_id == org_id,
                TeamMember.external_id == external_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update mutable fields
            existing.display_name = m.get("display_name") or existing.display_name
            existing.email = m.get("email") or existing.email
            if m.get("avatar_url"):
                existing.avatar_url = m["avatar_url"]
            ext_to_id[external_id] = existing.id
        else:
            member = TeamMember(
                id=generate_cuid(),
                organization_id=org_id,
                external_id=external_id,
                email=m.get("email", ""),
                display_name=m.get("display_name", ""),
                avatar_url=m.get("avatar_url"),
                skill_tags=m.get("skill_tags", []),
                default_capacity=m.get("default_capacity", 40.0),
            )
            db.add(member)
            ext_to_id[external_id] = member.id

    await db.flush()
    return ext_to_id


# =====================================================================
# ITERATIONS
# =====================================================================

async def upsert_iterations(
    db: AsyncSession,
    iterations: list[dict],
    org_id: str,
    project_id: str | None = None,
) -> dict[str, str]:
    """
    Upsert iterations and return mapping of external_id → internal id.
    """
    ext_to_id: dict[str, str] = {}

    for it in iterations:
        external_id = it["external_id"]
        source_tool = it.get("source_tool", "ADO")

        if not external_id:
            continue

        result = await db.execute(
            select(Iteration).where(
                Iteration.organization_id == org_id,
                Iteration.external_id == external_id,
                Iteration.source_tool == source_tool,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.name = it.get("name") or existing.name
            existing.goal = it.get("goal") or existing.goal
            if it.get("start_date"):
                existing.start_date = it["start_date"]
            if it.get("end_date"):
                existing.end_date = it["end_date"]
            # Fix degenerate case: if start == end (0-day sprint), default to 2 weeks
            if existing.start_date and existing.end_date:
                if existing.end_date <= existing.start_date:
                    existing.end_date = existing.start_date + timedelta(days=14)
            existing.state = it.get("state") or existing.state
            if project_id:
                existing.imported_project_id = project_id
            ext_to_id[external_id] = existing.id
        else:
            # Ensure start_date and end_date are set (required columns).
            # Default to a 2-week sprint starting today if dates are missing
            # (common for ADO iterations not configured with date ranges).
            start_date = it.get("start_date") or datetime.now(timezone.utc)
            end_date = it.get("end_date") or (start_date + timedelta(days=14))

            iteration = Iteration(
                id=generate_cuid(),
                organization_id=org_id,
                external_id=external_id,
                source_tool=source_tool,
                name=it.get("name", ""),
                goal=it.get("goal"),
                start_date=start_date,
                end_date=end_date,
                state=it.get("state", "active"),
                imported_project_id=project_id,
            )
            db.add(iteration)
            ext_to_id[external_id] = iteration.id

    await db.flush()
    return ext_to_id


# =====================================================================
# WORK ITEMS
# =====================================================================

async def upsert_work_items(
    db: AsyncSession,
    items: list[dict],
    org_id: str,
    member_map: dict[str, str] | None = None,
    iteration_map: dict[str, str] | None = None,
    project_id: str | None = None,
) -> list[str]:
    """
    Upsert work items with FK resolution.

    member_map: external_id → internal TeamMember.id
    iteration_map: external_id → internal Iteration.id
    project_id: imported_project.id — scopes work items to a project

    Returns list of internal IDs for upserted items.
    """
    member_map = member_map or {}
    iteration_map = iteration_map or {}
    upserted_ids: list[str] = []

    # Also build a name-based member lookup for ADO (where we get display_name not external_id)
    name_to_id: dict[str, str] = {}
    if member_map:
        result = await db.execute(
            select(TeamMember.display_name, TeamMember.id).where(
                TeamMember.organization_id == org_id,
            )
        )
        for row in result.all():
            name_to_id[row[0].lower()] = row[1]

    for wi in items:
        external_id = wi["external_id"]
        source_tool = wi.get("source_tool", "ADO")

        if not external_id:
            continue

        # Resolve assignee FK
        assignee_id = None
        if wi.get("_assigned_to_name"):
            # ADO: look up by display name
            assignee_id = name_to_id.get(wi["_assigned_to_name"].lower())
        if wi.get("_assignee_account_id"):
            # Jira: look up by external accountId
            assignee_id = member_map.get(wi["_assignee_account_id"])

        # Resolve iteration FK
        iteration_id = None
        if wi.get("_sprint_id"):
            # Jira: sprint.id → iteration external_id
            iteration_id = iteration_map.get(str(wi["_sprint_id"]))
        if wi.get("_iteration_path"):
            # ADO: try to match iteration by path suffix
            iter_path = wi["_iteration_path"]
            for ext_id, int_id in iteration_map.items():
                # Match the last segment of the iteration path
                if ext_id == iter_path or iter_path.endswith(f"\\{ext_id}"):
                    iteration_id = int_id
                    break
            if not iteration_id:
                # Try looking up by iteration path in DB
                result = await db.execute(
                    select(Iteration).where(
                        Iteration.organization_id == org_id,
                        Iteration.source_tool == source_tool,
                    )
                )
                for it in result.scalars().all():
                    if it.name and iter_path.endswith(it.name):
                        iteration_id = it.id
                        break

        # Check for existing
        result = await db.execute(
            select(WorkItem).where(
                WorkItem.organization_id == org_id,
                WorkItem.external_id == external_id,
                WorkItem.source_tool == source_tool,
            )
        )
        existing = result.scalar_one_or_none()

        # Strip private metadata keys (prefixed with _)
        clean_data = {k: v for k, v in wi.items() if not k.startswith("_")}

        if existing:
            # Update mutable fields
            existing.title = clean_data.get("title") or existing.title
            existing.description = clean_data.get("description") or existing.description
            existing.status = clean_data.get("status") or existing.status
            existing.story_points = clean_data.get("story_points")
            existing.priority = clean_data.get("priority", existing.priority)
            existing.type = clean_data.get("type") or existing.type
            existing.labels = clean_data.get("labels", existing.labels)
            existing.acceptance_criteria = clean_data.get("acceptance_criteria") or existing.acceptance_criteria
            if assignee_id:
                existing.assignee_id = assignee_id
            if iteration_id:
                existing.iteration_id = iteration_id
            if project_id:
                existing.imported_project_id = project_id
            upserted_ids.append(existing.id)
        else:
            item = WorkItem(
                id=generate_cuid(),
                organization_id=org_id,
                external_id=external_id,
                source_tool=source_tool,
                title=clean_data.get("title", "Untitled"),
                description=clean_data.get("description"),
                status=clean_data.get("status", "TODO"),
                story_points=clean_data.get("story_points"),
                priority=clean_data.get("priority", 2),
                type=clean_data.get("type", "story"),
                labels=clean_data.get("labels", []),
                acceptance_criteria=clean_data.get("acceptance_criteria"),
                assignee_id=assignee_id,
                iteration_id=iteration_id,
                imported_project_id=project_id,
            )
            db.add(item)
            upserted_ids.append(item.id)

    await db.flush()
    return upserted_ids


# =====================================================================
# REPOSITORIES
# =====================================================================

async def upsert_repositories(
    db: AsyncSession,
    repos: list[dict],
    org_id: str,
) -> dict[str, str]:
    """
    Upsert repositories and return mapping of external_id → internal id.
    """
    ext_to_id: dict[str, str] = {}

    for r in repos:
        external_id = r["external_id"]
        if not external_id:
            continue

        result = await db.execute(
            select(Repository).where(
                Repository.organization_id == org_id,
                Repository.external_id == external_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.name = r.get("name") or existing.name
            existing.full_name = r.get("full_name") or existing.full_name
            existing.default_branch = r.get("default_branch") or existing.default_branch
            existing.url = r.get("url") or existing.url
            ext_to_id[external_id] = existing.id
        else:
            repo = Repository(
                id=generate_cuid(),
                organization_id=org_id,
                external_id=external_id,
                name=r.get("name", ""),
                full_name=r.get("full_name", ""),
                default_branch=r.get("default_branch", "main"),
                url=r.get("url", ""),
            )
            db.add(repo)
            ext_to_id[external_id] = repo.id

    await db.flush()
    return ext_to_id


# =====================================================================
# PULL REQUESTS
# =====================================================================

async def upsert_pull_requests(
    db: AsyncSession,
    prs: list[dict],
    org_id: str,
    repo_map: dict[str, str] | None = None,
    member_map: dict[str, str] | None = None,
) -> list[str]:
    """
    Upsert pull requests with FK resolution.
    """
    repo_map = repo_map or {}
    member_map = member_map or {}
    upserted_ids: list[str] = []

    for pr in prs:
        external_id = pr["external_id"]
        if not external_id:
            continue

        # Resolve repo FK
        repository_id = pr.get("repository_id")
        if not repository_id and pr.get("_repo_full_name"):
            # Look up repo by full_name
            result = await db.execute(
                select(Repository).where(
                    Repository.organization_id == org_id,
                    Repository.full_name == pr["_repo_full_name"],
                )
            )
            repo = result.scalar_one_or_none()
            if repo:
                repository_id = repo.id

        if not repository_id:
            logger.warning(f"Skipping PR {external_id}: no repository_id")
            continue

        # Resolve author FK
        author_id = None
        if pr.get("_author_id") and pr["_author_id"] in member_map:
            author_id = member_map[pr["_author_id"]]
        elif pr.get("_author_login"):
            # Look up by external_id matching login
            result = await db.execute(
                select(TeamMember).where(
                    TeamMember.organization_id == org_id,
                    TeamMember.external_id == pr["_author_login"],
                )
            )
            member = result.scalar_one_or_none()
            if member:
                author_id = member.id

        # Clean metadata keys
        clean_data = {k: v for k, v in pr.items() if not k.startswith("_")}

        # Check for existing (by repo + external_id)
        result = await db.execute(
            select(PullRequest).where(
                PullRequest.repository_id == repository_id,
                PullRequest.external_id == external_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.title = clean_data.get("title") or existing.title
            existing.status = clean_data.get("status") or existing.status
            existing.ci_status = clean_data.get("ci_status") or existing.ci_status
            existing.reviewers = clean_data.get("reviewers", existing.reviewers)
            if author_id:
                existing.author_id = author_id
            if clean_data.get("merged_at"):
                existing.merged_at = clean_data["merged_at"]
            upserted_ids.append(existing.id)
        else:
            pull = PullRequest(
                id=generate_cuid(),
                repository_id=repository_id,
                external_id=external_id,
                number=clean_data.get("number", 0),
                title=clean_data.get("title", "Untitled PR"),
                status=clean_data.get("status", "OPEN"),
                author_id=author_id,
                reviewers=clean_data.get("reviewers", []),
                ci_status=clean_data.get("ci_status", "UNKNOWN"),
                linked_work_item_id=clean_data.get("linked_work_item_id"),
                url=clean_data.get("url", ""),
                created_external_at=clean_data.get("created_external_at") or datetime.now(timezone.utc),
                merged_at=clean_data.get("merged_at"),
            )
            db.add(pull)
            upserted_ids.append(pull.id)

    await db.flush()
    return upserted_ids


# =====================================================================
# COMMITS
# =====================================================================

async def upsert_commits(
    db: AsyncSession,
    commits: list[dict],
    org_id: str,
    repo_id: str,
    member_map: dict[str, str] | None = None,
) -> list[str]:
    """
    Upsert commits for a specific repository.
    """
    member_map = member_map or {}
    upserted_ids: list[str] = []

    for c in commits:
        sha = c.get("sha", "")
        if not sha:
            continue

        # Resolve author FK
        author_id = None
        if c.get("_author_id") and c["_author_id"] in member_map:
            author_id = member_map[c["_author_id"]]
        elif c.get("_author_login"):
            result = await db.execute(
                select(TeamMember).where(
                    TeamMember.organization_id == org_id,
                    TeamMember.external_id == c["_author_login"],
                )
            )
            member = result.scalar_one_or_none()
            if member:
                author_id = member.id

        # Check for existing
        result = await db.execute(
            select(Commit).where(
                Commit.repository_id == repo_id,
                Commit.sha == sha,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Commits are immutable, skip update
            upserted_ids.append(existing.id)
        else:
            commit = Commit(
                id=generate_cuid(),
                repository_id=repo_id,
                sha=sha,
                message=c.get("message", "")[:500],
                author_id=author_id,
                branch=c.get("branch", ""),
                linked_ticket_ids=c.get("linked_ticket_ids", []),
                files_changed=c.get("files_changed", 0),
                committed_at=c.get("committed_at") or datetime.now(timezone.utc),
            )
            db.add(commit)
            upserted_ids.append(commit.id)

    await db.flush()
    return upserted_ids


# =====================================================================
# FULL PROJECT SYNC (orchestrator)
# =====================================================================

async def sync_project_data(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    source_tool: str,
    *,
    raw_iterations: list[dict] | None = None,
    raw_members: list[dict] | None = None,
    raw_work_items: list[dict] | None = None,
) -> dict:
    """
    Orchestrate a full sync for one project. Caller provides raw API responses;
    this function normalizes, resolves FKs, and upserts everything.

    Returns summary: { "iterations": N, "members": N, "work_items": N }
    """
    from .normalizers import (
        normalize_ado_iteration,
        normalize_ado_team_member,
        normalize_ado_work_item,
        normalize_jira_sprint,
        normalize_jira_member,
        normalize_jira_issue,
    )

    counts = {"iterations": 0, "members": 0, "work_items": 0}

    # 1. Normalise & upsert team members first (needed for FK resolution)
    member_map: dict[str, str] = {}
    if raw_members:
        if source_tool.upper() == "ADO":
            normed = [normalize_ado_team_member(m, org_id) for m in raw_members]
        else:
            normed = [normalize_jira_member(m, org_id) for m in raw_members]
        member_map = await upsert_team_members(db, normed, org_id)
        counts["members"] = len(normed)

    # 2. Normalise & upsert iterations (needed for FK resolution)
    iter_map: dict[str, str] = {}
    if raw_iterations:
        if source_tool.upper() == "ADO":
            normed = [normalize_ado_iteration(i, org_id) for i in raw_iterations]
        else:
            normed = [normalize_jira_sprint(s, org_id) for s in raw_iterations]
        iter_map = await upsert_iterations(db, normed, org_id, project_id)
        counts["iterations"] = len(normed)

    # 3. Normalise & upsert work items (with FK resolution + project scoping)
    if raw_work_items:
        if source_tool.upper() == "ADO":
            normed = [normalize_ado_work_item(wi, org_id) for wi in raw_work_items]
        else:
            normed = [normalize_jira_issue(wi, org_id) for wi in raw_work_items]
        await upsert_work_items(db, normed, org_id, member_map, iter_map, project_id)
        counts["work_items"] = len(normed)

    # 4. Update ImportedProject synced_at timestamp
    result = await db.execute(
        select(ImportedProject).where(ImportedProject.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project:
        project.synced_at = datetime.now(timezone.utc)

    await db.commit()

    logger.info(
        f"Sync complete for project {project_id} ({source_tool}): "
        f"{counts['members']} members, {counts['iterations']} iterations, "
        f"{counts['work_items']} work items"
    )

    return counts

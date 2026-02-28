"""
Pure normalizer functions — convert raw tool API responses into
dicts matching SQLAlchemy model columns (ready for upsert).

Every function returns a dict whose keys are *snake_case column names*
exactly matching the model (not camelCase, not prefixed IDs).

Foreign key columns (iteration_id, assignee_id, etc.) are left as None
by the normalizer — they are resolved later during upsert by looking up
external_id → internal id in the database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .status_maps import (
    map_ado_status,
    map_ado_type,
    map_ado_priority,
    map_jira_status,
    map_jira_type,
    map_github_pr_status,
    map_github_ci_status,
    ADO_ITERATION_STATE,
)


# =====================================================================
# UTILITIES
# =====================================================================

def _parse_iso(value: str | None) -> datetime | None:
    """Safely parse an ISO-8601 string to a timezone-aware datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _safe_float(value: Any) -> float | None:
    """Safely convert to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> int:
    """Safely convert to int, defaulting to 0."""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _extract_tags(raw_tags: str | None) -> list[str]:
    """Parse ADO-style '; '-separated tags into a list."""
    if not raw_tags:
        return []
    return [t.strip() for t in raw_tags.split(";") if t.strip()]


# =====================================================================
# AZURE DEVOPS
# =====================================================================

def normalize_ado_work_item(raw: dict, org_id: str) -> dict:
    """
    Normalize a raw ADO work-item dict (from /_apis/wit/workitems response).

    The raw dict has a `fields` sub-object with System.* / Microsoft.* keys.
    Example:
        { "id": 1001, "fields": { "System.Title": "...", "System.State": "Active", ... } }
    """
    fields: dict = raw.get("fields") or {}
    wi_id = raw.get("id", "")

    assigned_to = fields.get("System.AssignedTo") or {}
    assigned_name = assigned_to.get("displayName") if isinstance(assigned_to, dict) else assigned_to

    return {
        "organization_id": org_id,
        "external_id": str(wi_id),
        "source_tool": "ADO",
        "title": fields.get("System.Title", "Untitled"),
        "description": fields.get("System.Description"),
        "status": map_ado_status(fields.get("System.State", "New")),
        "story_points": _safe_float(
            fields.get("Microsoft.VSTS.Scheduling.StoryPoints")
            or fields.get("Microsoft.VSTS.Scheduling.Effort")
        ),
        "priority": map_ado_priority(fields.get("Microsoft.VSTS.Common.Priority")),
        "type": map_ado_type(fields.get("System.WorkItemType", "User Story")),
        "labels": _extract_tags(fields.get("System.Tags")),
        "acceptance_criteria": fields.get("Microsoft.VSTS.Common.AcceptanceCriteria"),
        "epic_id": None,  # resolved during upsert via parent link
        # FK placeholders — resolved during sync
        "iteration_id": None,
        "assignee_id": None,
        # Pass-through metadata for FK resolution
        "_iteration_path": fields.get("System.IterationPath"),
        "_assigned_to_name": assigned_name,
        "_area_path": fields.get("System.AreaPath"),
        "_created_date": fields.get("System.CreatedDate"),
        "_changed_date": fields.get("System.ChangedDate"),
    }


def normalize_ado_iteration(raw: dict, org_id: str) -> dict:
    """
    Normalize a raw ADO iteration dict (from teamsettings/iterations API).

    Example:
        { "id": "guid", "name": "Sprint 24", "path": "...",
          "attributes": { "startDate": "...", "finishDate": "...", "timeFrame": "current" } }
    """
    attrs = raw.get("attributes") or {}
    return {
        "organization_id": org_id,
        "external_id": str(raw.get("id", "")),
        "source_tool": "ADO",
        "name": raw.get("name", ""),
        "goal": None,
        "start_date": _parse_iso(attrs.get("startDate")),
        "end_date": _parse_iso(attrs.get("finishDate")),
        "state": ADO_ITERATION_STATE.get(
            (attrs.get("timeFrame") or "current").lower(), "active"
        ),
        # metadata
        "_path": raw.get("path"),
    }


def normalize_ado_team_member(raw: dict, org_id: str) -> dict:
    """
    Normalize a raw ADO team member dict.

    The ADO /teams/{id}/members endpoint wraps the identity:
        { "identity": { "id": "...", "displayName": "...", "uniqueName": "..." } }

    Or flat format:
        { "id": "...", "displayName": "...", "uniqueName": "..." }
    """
    identity = raw.get("identity") or raw
    return {
        "organization_id": org_id,
        "external_id": str(identity.get("id", "")),
        "email": identity.get("uniqueName", ""),
        "display_name": identity.get("displayName", ""),
        "avatar_url": identity.get("imageUrl"),
        "skill_tags": [],
        "default_capacity": 40.0,
    }


# =====================================================================
# JIRA
# =====================================================================

def normalize_jira_issue(raw: dict, org_id: str) -> dict:
    """
    Normalize a raw Jira issue dict (from /search or /issue endpoints).

    Example:
        { "id": "10001", "key": "PROJ-201",
          "fields": {
            "summary": "...", "status": { "name": "In Progress", "statusCategory": { "key": "indeterminate" } },
            "issuetype": { "name": "Story" },
            "assignee": { "accountId": "...", "displayName": "..." },
            "customfield_10016": 8,  # story points
            ...
          } }
    """
    fields: dict = raw.get("fields") or {}
    status_obj = fields.get("status") or {}
    status_category = (status_obj.get("statusCategory") or {}).get("key", "")
    issue_type_obj = fields.get("issuetype") or {}
    assignee_obj = fields.get("assignee") or {}
    sprint_obj = fields.get("sprint") or {}  # Jira Agile sprint field

    # Try common story point custom fields
    story_points = (
        _safe_float(fields.get("customfield_10016"))   # Jira Cloud default
        or _safe_float(fields.get("customfield_10028"))  # Common alternative
        or _safe_float(fields.get("story_points"))
    )

    labels = fields.get("labels") or []

    return {
        "organization_id": org_id,
        "external_id": raw.get("key") or str(raw.get("id", "")),
        "source_tool": "JIRA",
        "title": fields.get("summary", "Untitled"),
        "description": fields.get("description"),
        "status": map_jira_status(
            status_obj.get("name", ""),
            status_category,
        ),
        "story_points": story_points,
        "priority": _safe_int((fields.get("priority") or {}).get("id", 2)),
        "type": map_jira_type(issue_type_obj.get("name", "Story")),
        "labels": labels if isinstance(labels, list) else [],
        "acceptance_criteria": None,  # Jira doesn't have a standard AC field
        "epic_id": None,  # resolved during upsert via epic link
        # FK placeholders
        "iteration_id": None,
        "assignee_id": None,
        # metadata for FK resolution
        "_assignee_account_id": assignee_obj.get("accountId"),
        "_assignee_display_name": assignee_obj.get("displayName"),
        "_sprint_id": sprint_obj.get("id"),
        "_sprint_name": sprint_obj.get("name"),
        "_epic_key": fields.get("epic", {}).get("key") if isinstance(fields.get("epic"), dict) else fields.get("epic"),
        "_created": fields.get("created"),
        "_updated": fields.get("updated"),
    }


def normalize_jira_sprint(raw: dict, org_id: str) -> dict:
    """
    Normalize a raw Jira sprint dict (from agile/board/{id}/sprint API).

    Example:
        { "id": 123, "name": "Sprint 24", "state": "active",
          "startDate": "2026-02-09T...", "endDate": "2026-02-23T..." }
    """
    return {
        "organization_id": org_id,
        "external_id": str(raw.get("id", "")),
        "source_tool": "JIRA",
        "name": raw.get("name", ""),
        "goal": raw.get("goal"),
        "start_date": _parse_iso(raw.get("startDate")),
        "end_date": _parse_iso(raw.get("endDate")),
        "state": (raw.get("state") or "active").lower(),
    }


def normalize_jira_member(raw: dict, org_id: str) -> dict:
    """
    Normalize a raw Jira user dict (from /user/search or /project/{key}/assignable).

    Example:
        { "accountId": "abc123", "displayName": "Alex Kim",
          "emailAddress": "alex@demo.com", "avatarUrls": { "48x48": "..." } }
    """
    avatars = raw.get("avatarUrls") or {}
    return {
        "organization_id": org_id,
        "external_id": raw.get("accountId", ""),
        "email": raw.get("emailAddress", ""),
        "display_name": raw.get("displayName", ""),
        "avatar_url": avatars.get("48x48") or avatars.get("32x32"),
        "skill_tags": [],
        "default_capacity": 40.0,
    }


# =====================================================================
# GITHUB
# =====================================================================

def normalize_github_repo(raw: dict, org_id: str) -> dict:
    """
    Normalize a raw GitHub repository dict (from /user/repos or /orgs/{org}/repos).

    Example:
        { "id": 123456, "name": "my-repo", "full_name": "owner/my-repo",
          "default_branch": "main", "html_url": "https://github.com/..." }
    """
    return {
        "organization_id": org_id,
        "external_id": str(raw.get("id", "")),
        "name": raw.get("name", ""),
        "full_name": raw.get("full_name", raw.get("name", "")),
        "default_branch": raw.get("default_branch", "main"),
        "url": raw.get("html_url", raw.get("url", "")),
    }


def normalize_github_pr(raw: dict, org_id: str) -> dict:
    """
    Normalize a raw GitHub pull request dict (from /repos/{owner}/{repo}/pulls).

    Example:
        { "id": 1, "number": 42, "title": "Fix bug",
          "state": "open", "merged_at": null,
          "user": { "login": "dev1", "id": 789 },
          "html_url": "...", "created_at": "...",
          "requested_reviewers": [{ "login": "rev1" }] }
    """
    user = raw.get("user") or {}
    merged_at = raw.get("merged_at")
    is_merged = merged_at is not None

    reviewers = [
        r.get("login", "") for r in (raw.get("requested_reviewers") or [])
    ]

    return {
        "organization_id": org_id,
        "external_id": str(raw.get("id", "")),
        "number": _safe_int(raw.get("number")),
        "title": raw.get("title", "Untitled PR"),
        "status": map_github_pr_status(raw.get("state", "open"), is_merged),
        "reviewers": reviewers,
        "ci_status": "UNKNOWN",  # resolved separately from check-runs API
        "url": raw.get("html_url", ""),
        "created_external_at": _parse_iso(raw.get("created_at")),
        "merged_at": _parse_iso(merged_at),
        # FK placeholders
        "repository_id": None,  # resolved during sync
        "author_id": None,      # resolved during sync
        "linked_work_item_id": None,
        # metadata for FK resolution
        "_author_login": user.get("login"),
        "_author_id": str(user.get("id", "")),
        "_repo_full_name": None,  # set by caller
    }


def normalize_github_commit(raw: dict, org_id: str) -> dict:
    """
    Normalize a raw GitHub commit dict (from /repos/{owner}/{repo}/commits).

    Example:
        { "sha": "abc123...", "commit": { "message": "Fix bug", "author": { "date": "..." } },
          "author": { "login": "dev1", "id": 789 },
          "stats": { "total": 42 } }
    """
    commit_data = raw.get("commit") or {}
    author_data = raw.get("author") or {}
    commit_author = commit_data.get("author") or {}
    stats = raw.get("stats") or {}

    message = commit_data.get("message", "")

    # Extract linked ticket IDs from commit message (e.g., PROJ-123, #456, AB#789)
    import re
    ticket_refs: list[str] = []
    # Jira-style: PROJ-123
    ticket_refs.extend(re.findall(r"[A-Z]+-\d+", message))
    # GitHub-style: #123
    ticket_refs.extend(re.findall(r"#(\d+)", message))
    # ADO-style: AB#123
    ticket_refs.extend(re.findall(r"AB#(\d+)", message))

    return {
        "organization_id": org_id,
        "sha": raw.get("sha", ""),
        "message": message[:500],  # truncate very long messages
        "branch": "",  # set by caller (not in commit response)
        "linked_ticket_ids": ticket_refs,
        "files_changed": _safe_int(stats.get("total")),
        "committed_at": _parse_iso(commit_author.get("date")),
        # FK placeholders
        "repository_id": None,  # resolved during sync
        "author_id": None,      # resolved during sync
        # metadata for FK resolution
        "_author_login": author_data.get("login"),
        "_author_id": str(author_data.get("id", "")),
    }

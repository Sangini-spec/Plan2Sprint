"""
Data normalization — re-exports from the canonical adapters module.

DEPRECATED: New code should import from app.adapters.normalizers directly.
This file is kept for backward compatibility.
"""

# Re-export from the canonical adapter layer
from ..adapters.normalizers import (
    normalize_jira_sprint,
    normalize_jira_issue,
    normalize_jira_member,
    normalize_ado_work_item,
    normalize_ado_iteration,
    normalize_ado_team_member,
    normalize_github_repo,
    normalize_github_pr,
    normalize_github_commit,
)

# Legacy aliases (used by older code that imported these names)
normalize_jira_sprint = normalize_jira_sprint
normalize_ado_iteration = normalize_ado_iteration


def normalize_work_item(raw: dict) -> dict:
    """Legacy fill-defaults for any partial WorkItem dict. Not tool-specific."""
    return {
        "organization_id": raw.get("organization_id", ""),
        "external_id": raw.get("external_id", raw.get("id", "")),
        "source_tool": raw.get("source_tool", "JIRA"),
        "title": raw.get("title", "Untitled"),
        "description": raw.get("description"),
        "status": raw.get("status", "BACKLOG"),
        "story_points": raw.get("story_points"),
        "priority": raw.get("priority", 0),
        "type": raw.get("type", "story"),
        "labels": raw.get("labels", []),
        "acceptance_criteria": raw.get("acceptance_criteria"),
        "epic_id": raw.get("epic_id"),
        "iteration_id": raw.get("iteration_id"),
        "assignee_id": raw.get("assignee_id"),
    }


def normalize_pull_request(raw: dict) -> dict:
    """Legacy fill-defaults for any partial PullRequest dict. Not tool-specific."""
    from datetime import datetime, timezone
    return {
        "repository_id": raw.get("repository_id", ""),
        "external_id": raw.get("external_id", raw.get("id", "")),
        "number": raw.get("number", 0),
        "title": raw.get("title", "Untitled PR"),
        "status": raw.get("status", "OPEN"),
        "author_id": raw.get("author_id"),
        "reviewers": raw.get("reviewers", []),
        "ci_status": raw.get("ci_status", "UNKNOWN"),
        "linked_work_item_id": raw.get("linked_work_item_id"),
        "url": raw.get("url", ""),
        "created_external_at": raw.get("created_external_at", datetime.now(timezone.utc).isoformat()),
        "merged_at": raw.get("merged_at"),
    }

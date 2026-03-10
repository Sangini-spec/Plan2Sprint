"""
Status mapping tables for normalizing tool-specific statuses to unified enums.

Unified WorkItem statuses: BACKLOG, TODO, IN_PROGRESS, IN_REVIEW, DONE, CANCELLED
Unified PR statuses:       OPEN, AWAITING_REVIEW, CHANGES_REQUESTED, APPROVED, MERGED, CLOSED
Unified CI statuses:       PASSING, FAILING, PENDING, UNKNOWN
Unified Iteration states:  future, active, closed
"""

# ---------------------------------------------------------------------------
# ADO Work Item State → Unified Status
# Ref: https://learn.microsoft.com/en-us/azure/devops/boards/work-items/workflow-and-state-categories
# ---------------------------------------------------------------------------
ADO_WORK_ITEM_STATUS: dict[str, str] = {
    # Proposed category
    "new": "TODO",
    "proposed": "TODO",
    # In Progress category
    "active": "IN_PROGRESS",
    "committed": "IN_PROGRESS",
    "in progress": "IN_PROGRESS",
    "resolved": "IN_REVIEW",
    # Completed category
    "closed": "DONE",
    "done": "DONE",
    "completed": "DONE",
    # Removed category
    "removed": "CANCELLED",
    "cut": "CANCELLED",
}

# ADO Work Item Type → normalised lower-case type
ADO_WORK_ITEM_TYPE: dict[str, str] = {
    "user story": "story",
    "product backlog item": "story",
    "bug": "bug",
    "task": "task",
    "feature": "feature",
    "epic": "epic",
    "issue": "bug",
    "impediment": "bug",
    "test case": "task",
}

# ADO Priority (1=Critical…4=Low) → integer (lower = higher priority, 0-based)
ADO_PRIORITY: dict[int, int] = {1: 0, 2: 1, 3: 2, 4: 3}


# ---------------------------------------------------------------------------
# Jira Status → Unified Status
# Jira status category IDs: "new" | "indeterminate" | "done"
# ---------------------------------------------------------------------------
JIRA_STATUS_CATEGORY: dict[str, str] = {
    "new": "TODO",
    "indeterminate": "IN_PROGRESS",
    "done": "DONE",
}

# Common Jira status name overrides (case-insensitive)
JIRA_STATUS_NAME: dict[str, str] = {
    "backlog": "BACKLOG",
    "to do": "TODO",
    "selected for development": "TODO",
    "in progress": "IN_PROGRESS",
    "in review": "IN_REVIEW",
    "in qa": "IN_REVIEW",
    "done": "DONE",
    "closed": "DONE",
    "resolved": "DONE",
    "cancelled": "CANCELLED",
    "rejected": "CANCELLED",
    "won't do": "CANCELLED",
    "won't fix": "CANCELLED",
}

# Jira issue type → normalised lower-case type
JIRA_ISSUE_TYPE: dict[str, str] = {
    "story": "story",
    "user story": "story",
    "bug": "bug",
    "task": "task",
    "sub-task": "task",
    "subtask": "task",
    "epic": "epic",
    "feature": "feature",
    "improvement": "story",
    "new feature": "feature",
    "spike": "task",
    "tech debt": "task",
}


# ---------------------------------------------------------------------------
# GitHub PR State → Unified Status
# ---------------------------------------------------------------------------
GITHUB_PR_STATUS: dict[str, str] = {
    "open": "OPEN",
    "closed": "CLOSED",
    "merged": "MERGED",
}

GITHUB_CI_STATUS: dict[str, str] = {
    "success": "PASSING",
    "failure": "FAILING",
    "error": "FAILING",
    "pending": "PENDING",
    "action_required": "FAILING",
    "cancelled": "FAILING",
    "timed_out": "FAILING",
    "neutral": "PASSING",
    "skipped": "PASSING",
    "stale": "UNKNOWN",
    "queued": "PENDING",
    "in_progress": "PENDING",
    "requested": "PENDING",
    "waiting": "PENDING",
    "completed": "PASSING",
}


# ---------------------------------------------------------------------------
# ADO Iteration timeFrame → Unified state
# ---------------------------------------------------------------------------
ADO_ITERATION_STATE: dict[str, str] = {
    "past": "closed",
    "current": "active",
    "future": "future",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def map_ado_status(ado_state: str) -> str:
    """Map an ADO work-item state to the unified status."""
    return ADO_WORK_ITEM_STATUS.get(ado_state.lower().strip(), "TODO")


def map_ado_type(ado_type: str) -> str:
    """Map an ADO work-item type to the normalised type."""
    return ADO_WORK_ITEM_TYPE.get(ado_type.lower().strip(), "story")


def map_ado_priority(ado_priority: int | None) -> int:
    """Map ADO priority (1-4) to 0-based integer."""
    if ado_priority is None:
        return 2
    return ADO_PRIORITY.get(ado_priority, 2)


def map_jira_status(status_name: str, status_category_key: str | None = None) -> str:
    """Map a Jira status to the unified status."""
    # Prefer exact name match
    name_lower = status_name.lower().strip()
    if name_lower in JIRA_STATUS_NAME:
        return JIRA_STATUS_NAME[name_lower]
    # Fall back to category
    if status_category_key:
        return JIRA_STATUS_CATEGORY.get(status_category_key.lower(), "TODO")
    return "TODO"


def map_jira_type(issue_type: str) -> str:
    """Map a Jira issue type to the normalised type."""
    return JIRA_ISSUE_TYPE.get(issue_type.lower().strip(), "story")


def map_github_pr_status(state: str, merged: bool = False) -> str:
    """Map GitHub PR state to unified status."""
    if merged:
        return "MERGED"
    return GITHUB_PR_STATUS.get(state.lower().strip(), "OPEN")


def map_github_ci_status(conclusion: str | None, status: str | None = None) -> str:
    """Map GitHub CI conclusion/status to unified CI status."""
    if conclusion:
        return GITHUB_CI_STATUS.get(conclusion.lower().strip(), "UNKNOWN")
    if status:
        return GITHUB_CI_STATUS.get(status.lower().strip(), "UNKNOWN")
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Reverse Maps: Unified Status → Tool-Specific State (for write-back)
# ---------------------------------------------------------------------------

# Unified → ADO System.State (for PATCH /fields/System.State)
UNIFIED_TO_ADO_STATE: dict[str, str] = {
    "TODO": "New",
    "BACKLOG": "New",
    "IN_PROGRESS": "Active",
    "IN_REVIEW": "Resolved",
    "DONE": "Closed",
    "CANCELLED": "Removed",
}

# Unified → Jira target status name (used to find the right transition)
# Match priority: exact name first, then statusCategory fallback
UNIFIED_TO_JIRA_STATUS: dict[str, tuple[str, str]] = {
    # (target_status_name, fallback_category_key)
    "TODO": ("To Do", "new"),
    "BACKLOG": ("Backlog", "new"),
    "IN_PROGRESS": ("In Progress", "indeterminate"),
    "IN_REVIEW": ("In Review", "indeterminate"),
    "DONE": ("Done", "done"),
    "CANCELLED": ("Cancelled", "done"),
}


def reverse_map_ado_status(unified: str) -> str:
    """Map a unified status to the ADO System.State value for write-back."""
    return UNIFIED_TO_ADO_STATE.get(unified.upper(), "New")


def reverse_map_jira_status(unified: str) -> tuple[str, str]:
    """
    Map a unified status to (target_status_name, fallback_category_key)
    for Jira transition discovery.
    """
    return UNIFIED_TO_JIRA_STATUS.get(unified.upper(), ("To Do", "new"))

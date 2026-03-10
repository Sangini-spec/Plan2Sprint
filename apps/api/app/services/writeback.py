"""
Write-back safety enforcement.
Port of apps/web/src/lib/integrations/writeback.ts

Immutable allowlists — Python tuples cannot be modified at runtime.
"""

from typing import Literal

# Frozen allowlists — equivalent to Object.freeze() in TypeScript
JIRA_WRITEBACK_ALLOWLIST: tuple[str, ...] = ("assignee", "sprint_id", "story_points", "status")
ADO_WRITEBACK_ALLOWLIST: tuple[str, ...] = (
    "System.AssignedTo",
    "System.IterationPath",
    "Microsoft.VSTS.Scheduling.StoryPoints",
    "System.State",
)
GITHUB_WRITEBACK_ALLOWLIST: tuple[str, ...] = ()  # GitHub is read-only


def validate_writeback_fields(
    tool: Literal["jira", "ado", "github"],
    fields: dict[str, object],
) -> tuple[bool, list[str]]:
    """
    Validate that all fields in the write-back request are in the allowlist.

    Returns:
        (is_valid, disallowed_fields) — is_valid is True if all fields are allowed.
    """
    if tool == "github":
        return False, list(fields.keys())

    allowlist = JIRA_WRITEBACK_ALLOWLIST if tool == "jira" else ADO_WRITEBACK_ALLOWLIST
    disallowed = [f for f in fields if f not in allowlist]
    return len(disallowed) == 0, disallowed


def build_writeback_payload(
    tool: str,
    item_id: str,
    fields: dict[str, object],
    previous_values: dict[str, object] | None = None,
) -> dict:
    """Build an audit-ready write-back payload."""
    prev = previous_values or {}
    return {
        "tool": tool,
        "item_id": item_id,
        "changes": [
            {"field": k, "from": prev.get(k), "to": v}
            for k, v in fields.items()
        ],
    }

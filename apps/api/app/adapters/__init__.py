"""
Backend adapters — normalize tool-specific API responses into SQLAlchemy models.

Modules:
  normalizers  — Pure functions: raw API dict → model-ready dict
  status_maps  — ADO / Jira / GitHub status → unified status enum
  sync         — Upsert normalised records into the database
"""

from .normalizers import (
    normalize_ado_work_item,
    normalize_ado_iteration,
    normalize_ado_team_member,
    normalize_jira_issue,
    normalize_jira_sprint,
    normalize_jira_member,
    normalize_github_repo,
    normalize_github_pr,
    normalize_github_commit,
)

__all__ = [
    "normalize_ado_work_item",
    "normalize_ado_iteration",
    "normalize_ado_team_member",
    "normalize_jira_issue",
    "normalize_jira_sprint",
    "normalize_jira_member",
    "normalize_github_repo",
    "normalize_github_pr",
    "normalize_github_commit",
]

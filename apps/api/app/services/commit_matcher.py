"""GitHub commit -> work item matcher.

Used by the timeline engine (Sprint 5's real-time adjustment layer) to infer
the "most advanced" phase a project is in, based on what developers have been
actually committing — not just what ADO/Jira columns say.

Two reasons this exists:

  1. On small teams (the Plan2Sprint project itself has ONE developer) there
     are no pull requests to lean on — work lands via direct commits to
     main/master. Those commits are the only ground truth of real progress.
  2. ADO/Jira board columns lag real work: a dev may merge "Add Teams channel
     parity" and forget to flip the card to Done. The commit message is the
     tell.

Tier 1 matching — explicit issue references in the commit message:
      PROJ-123    (Jira-style key)
      #123        (GitHub-style)
      AB#123      (Azure Boards style)
  These map to ``WorkItem.external_id`` directly — highest confidence.

Tier 2 matching — keyword Jaccard similarity between commit message and work
item title. Both sides are tokenised, lowercased, camelCase-split, stopword-
filtered. A match requires:
    - Jaccard score >= TIER2_THRESHOLD  (default 0.3)
    - at least MIN_OVERLAP_TOKENS overlapping meaningful tokens (2)
  This guards against one-word false positives like every commit mentioning
  "fix" collapsing onto a work item titled "Fix blah".

The output of ``infer_github_phase(...)`` is the ``slug`` of the most advanced
phase (by ProjectPhase.sort_order) that has at least one commit-matched work
item in the recent window. ``None`` if we had no matches — the caller falls
back to ADO-only in that case.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.project_phase import ProjectPhase
from ..models.repository import Commit, Repository
from ..models.work_item import WorkItem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tuning knobs — centralised here so we can tweak without code rewrites
# ---------------------------------------------------------------------------

# How far back to look for commits. 30 days covers most active-sprint windows;
# older commits are typically not reflective of the project's *current* phase.
LOOKBACK_DAYS = 30

# Minimum Jaccard similarity for a Tier-2 keyword match.
TIER2_THRESHOLD = 0.30

# Alternative acceptance path — if ≥ this fraction of the *work item's* tokens
# is present in the commit message, accept the match even if Jaccard alone
# would reject it. This catches specific commits like "Weekly report gauge
# tweak" that touch a focused work item but also use unrelated words.
WI_COVERAGE_THRESHOLD = 0.40

# How many meaningful tokens must overlap, independent of the score. This
# stops "fix typo" commits from matching a work item named "Fix" just because
# the single word overlaps.
MIN_OVERLAP_TOKENS = 2

# Words we drop during tokenisation because they carry no signal.
STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "by",
    "for", "with", "from", "as", "is", "are", "was", "were", "be", "been",
    "being", "it", "its", "this", "that", "these", "those",
    # Common in commit messages but not useful for matching
    "fix", "feat", "chore", "docs", "test", "refactor", "add", "update",
    "remove", "make", "new", "initial", "minor", "polish", "cleanup",
    "bump", "wip", "tmp",
})

# Explicit issue-reference patterns we try in order. The captured group is
# matched against WorkItem.external_id.
ISSUE_REF_PATTERNS = [
    # Azure Boards style: AB#123
    re.compile(r"\bAB#(\d+)\b", re.IGNORECASE),
    # Jira style: PROJ-123
    re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b"),
    # GitHub style: #123 (anywhere in the message, but not at start of line
    # where it would be a code header)
    re.compile(r"(?<!\w)#(\d+)\b"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class CommitMatch:
    commit_sha: str
    commit_message_head: str
    work_item_id: str
    work_item_title: str
    phase_id: Optional[str]
    phase_slug: Optional[str]
    match_tier: str  # "EXPLICIT" | "KEYWORD"
    score: float


async def infer_github_phase(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    lookback_days: int = LOOKBACK_DAYS,
) -> Optional[str]:
    """Return the slug of the most advanced phase GitHub says the project is
    in. ``None`` if we can't infer anything (no commits, or no matches)."""
    matches = await collect_matches(db, org_id, project_id, lookback_days)
    if not matches:
        return None

    # Load phase sort_order to pick the most advanced match.
    phases_q = await db.execute(
        select(ProjectPhase.id, ProjectPhase.slug, ProjectPhase.sort_order)
        .where(ProjectPhase.project_id == project_id)
    )
    phase_order: dict[str, int] = {}
    phase_slug_by_id: dict[str, str] = {}
    for pid, pslug, psort in phases_q.all():
        phase_order[pid] = psort
        phase_slug_by_id[pid] = pslug

    best_slug: Optional[str] = None
    best_order: int = -1
    for m in matches:
        if m.phase_id is None:
            continue
        o = phase_order.get(m.phase_id, -1)
        if o > best_order:
            best_order = o
            best_slug = phase_slug_by_id.get(m.phase_id)

    return best_slug


async def collect_matches(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    lookback_days: int = LOOKBACK_DAYS,
) -> list[CommitMatch]:
    """Diagnostic-friendly variant that returns every commit → work item
    match it found, so we can dogfood / smoke-test the matcher."""
    # Fetch work items for this project (we match commits *against* these).
    wi_q = await db.execute(
        select(WorkItem.id, WorkItem.external_id, WorkItem.title, WorkItem.phase_id)
        .where(
            WorkItem.organization_id == org_id,
            WorkItem.imported_project_id == project_id,
        )
    )
    work_items = [
        _WorkItemLite(
            id=wid, external_id=ext_id, title=title,
            phase_id=phase_id, tokens=_tokenise(title),
        )
        for wid, ext_id, title, phase_id in wi_q.all()
    ]
    if not work_items:
        return []

    by_external: dict[str, _WorkItemLite] = {
        w.external_id: w for w in work_items if w.external_id
    }
    # Also build a lowercased lookup so Jira keys work case-insensitively.
    by_external_lower: dict[str, _WorkItemLite] = {
        w.external_id.lower(): w for w in work_items if w.external_id
    }

    # Fetch recent commits across every repo in this org.
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    commits_q = await db.execute(
        select(Commit.sha, Commit.message, Commit.linked_ticket_ids)
        .join(Repository, Commit.repository_id == Repository.id)
        .where(
            Repository.organization_id == org_id,
            Commit.committed_at >= since,
        )
    )
    rows = commits_q.all()
    if not rows:
        return []

    matches: list[CommitMatch] = []

    for sha, message, linked_ids in rows:
        match = _match_commit(message, linked_ids, work_items,
                              by_external, by_external_lower)
        if match is None:
            continue
        wi, tier, score = match
        matches.append(CommitMatch(
            commit_sha=sha,
            commit_message_head=(message or "").splitlines()[0][:80],
            work_item_id=wi.id,
            work_item_title=wi.title,
            phase_id=wi.phase_id,
            phase_slug=None,  # resolved later by caller if needed
            match_tier=tier,
            score=score,
        ))

    return matches


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

@dataclass
class _WorkItemLite:
    id: str
    external_id: Optional[str]
    title: str
    phase_id: Optional[str]
    tokens: frozenset[str]


def _match_commit(
    message: str,
    linked_ids: list[str],
    work_items: list[_WorkItemLite],
    by_external: dict[str, _WorkItemLite],
    by_external_lower: dict[str, _WorkItemLite],
) -> Optional[tuple[_WorkItemLite, str, float]]:
    """Tier 1 + Tier 2 matching. Returns (work_item, tier, score) or None."""
    msg = message or ""

    # Tier 0: the repo-level linked_ticket_ids column (populated by the GitHub
    # integration when a PR references an issue). Strongest possible signal.
    for tid in linked_ids or []:
        wi = by_external.get(tid) or by_external_lower.get((tid or "").lower())
        if wi is not None:
            return wi, "EXPLICIT", 1.0

    # Tier 1: regex-scrape the commit message for explicit issue references.
    for pat in ISSUE_REF_PATTERNS:
        m = pat.search(msg)
        if not m:
            continue
        ref = m.group(1)
        wi = by_external.get(ref) or by_external_lower.get(ref.lower())
        if wi is not None:
            return wi, "EXPLICIT", 1.0

    # Tier 2: keyword similarity over normalised tokens.
    # We accept if EITHER the Jaccard score clears TIER2_THRESHOLD OR the
    # commit covers at least WI_COVERAGE_THRESHOLD of the work item's tokens.
    # That means a focused commit like "Weekly report semicircle gauge tweak"
    # still matches "Weekly stakeholder PDF report" even though the commit has
    # several extra words that deflate the raw Jaccard number.
    commit_tokens = _tokenise(msg)
    if not commit_tokens:
        return None

    best: Optional[tuple[_WorkItemLite, float]] = None
    for wi in work_items:
        if not wi.tokens:
            continue
        overlap = commit_tokens & wi.tokens
        if len(overlap) < MIN_OVERLAP_TOKENS:
            continue
        jaccard = len(overlap) / len(commit_tokens | wi.tokens)
        wi_coverage = len(overlap) / len(wi.tokens)
        score = max(jaccard, wi_coverage)
        if jaccard < TIER2_THRESHOLD and wi_coverage < WI_COVERAGE_THRESHOLD:
            continue
        if best is None or score > best[1]:
            best = (wi, score)
    if best is None:
        return None
    return best[0], "KEYWORD", best[1]


_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9]+")


def _tokenise(text: str) -> frozenset[str]:
    """Produce a bag of lowercase meaningful tokens from a commit message or
    a work item title."""
    if not text:
        return frozenset()
    # Split on camelCase first so 'addSmartNotes' -> 'add Smart Notes'
    spaced = _CAMEL_SPLIT_RE.sub(" ", text)
    # Split on any non-alphanumeric
    raw = _NON_ALNUM_RE.split(spaced)
    tokens = set()
    for t in raw:
        if not t:
            continue
        tl = t.lower()
        if len(tl) < 2:
            continue
        if tl in STOPWORDS:
            continue
        tokens.add(tl)
    return frozenset(tokens)

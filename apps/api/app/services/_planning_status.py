"""Shared status taxonomy for sprint planning + rebalancing.

Why this exists
---------------
ADO and Jira surface a long tail of column / state names ("Resolved",
"Migrate", "Testing", "Closed", "Active" etc.). The platform normalises
the most common ones to an internal status set, but custom states drift
through unchanged. Sprint planning historically used a whitelist —
``status IN ('BACKLOG', 'TODO', 'IN_PROGRESS', 'IN_REVIEW')`` — which
silently dropped any work item in a custom state.

We flipped that to an exclusion-based filter: anything in
``TERMINAL_STATUSES`` is finished and therefore NOT plannable; everything
else flows through. This catches both the canonical normalised statuses
(``DONE``) and the raw external strings teams sometimes leave behind
(``Closed``, ``Resolved``, etc.).

All comparisons are case-insensitive — callers should use
``func.upper(WorkItem.status).notin_(TERMINAL_STATUSES)`` on the SQL side
or ``status.upper() in TERMINAL_STATUSES`` in Python.

Effort-scaling factors
----------------------
``REMAINING_EFFORT_FACTOR`` tells the AI sprint generator how much of a
work item's story-point budget is *still* remaining given its current
status. A 5 SP card in Testing only consumes 1.5 SP of capacity (0.30
factor) because most of the work is done. Tuned with the PO Apr 2026.
"""

from __future__ import annotations

# Statuses that mean "finished — not plannable". Compared case-insensitively
# AFTER stripping non-alphanumeric chars (so "In Review" → "INREVIEW").
#
# The base set covers the canonical ADO/Jira "completed" category. The
# extended aliases at the bottom catch the long tail of post-development
# board columns teams use as their actual terminal state — "Deployed",
# "Released", "Shipped", "Verified", "Accepted". Without these, a feature
# parked in a custom "Deployed" column would show as in-progress on the
# Gantt forever even though every team treats Deployed as done.
TERMINAL_STATUSES: frozenset[str] = frozenset({
    # Canonical
    "DONE",
    "CLOSED",
    "RESOLVED",
    "REMOVED",
    "ABANDONED",
    "COMPLETED",
    "CANCELED",
    "CANCELLED",
    # Post-development column aliases — common in custom ADO/Jira workflows
    "DEPLOYED",
    "DEPLOY",            # column singular form
    "DEPLOYMENT",        # phase / column name
    "RELEASED",
    "RELEASE",
    "SHIPPED",
    "VERIFIED",
    "ACCEPTED",
    "MERGED",
    "ARCHIVED",
})

# Statuses that mean "actively being built right now". 60% of original
# effort assumed remaining when planning capacity. Stored without spaces /
# separators since we normalise the input in remaining_effort_factor.
IN_PROGRESS_STATUSES: frozenset[str] = frozenset({
    "INPROGRESS",
    "ACTIVE",
    "COMMITTED",
    "DOING",
    "STARTED",
    "WIP",
})

# Statuses that mean "code complete, awaiting verification". 30% of
# original effort assumed remaining.
IN_REVIEW_STATUSES: frozenset[str] = frozenset({
    "INREVIEW",
    "REVIEW",
    "TESTING",
    "READYFORTEST",
    "QA",
    "VERIFY",
    "VERIFICATION",
    # ADO/Jira often surface late-stage states under custom names. We map
    # these to "in review" because they conceptually mean "code done, just
    # needs verifying / migrating / staging".
    "MIGRATE",
    "MIGRATING",
    "MIGRATION",
    "STAGING",
    "UAT",
})


def remaining_effort_factor(status: str | None) -> float:
    """Return the fraction (0..1) of original story points still remaining
    given a work item's current status.

    Used by the AI sprint generator to scale capacity allocation: a 5 SP
    card in Testing should only consume 5 * 0.30 = 1.5 SP of the team's
    remaining capacity, because most of the work is already done.

    Returns 1.0 (= treat as fresh) when the status is unknown or empty —
    safer to over-budget than under-budget if we genuinely don't know.
    Terminal statuses return 0.0 but those work items shouldn't reach
    this function in the first place (they're filtered upstream).
    """
    if not status:
        return 1.0
    # Normalise: strip, uppercase, collapse all whitespace / separators
    # ("In Progress", "In-Progress", "in_progress" all → "INPROGRESS").
    s = "".join(ch for ch in status.upper() if ch.isalnum())
    if not s:
        return 1.0
    if s in TERMINAL_STATUSES:
        return 0.0
    if s in IN_REVIEW_STATUSES:
        return 0.30
    if s in IN_PROGRESS_STATUSES:
        return 0.60
    # BACKLOG / TODO / NEW / PROPOSED / unknown -> full effort still ahead
    return 1.0

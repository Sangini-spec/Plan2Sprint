"""
Smart Blocker Detection Agent — proactively identifies blockers the team hasn't flagged.

Scans for:
  - Work items stalled > 2 days in IN_PROGRESS with no status change
  - PRs open > 48 hours with no review
  - CI failures blocking merge
  - Dependency chains (Item A → Item B → Item C all blocked)
  - Correlates across tools (Jira status + GitHub PR state + CI results)

Creates BlockerFlag records and notifies PO + affected developer.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone, date
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_orchestrator import AgentConfig, orchestrator
from ..agent_tools import build_blocker_detection_tools
from ...models.standup import StandupReport, BlockerFlag
from ...models.base import generate_cuid

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------

BLOCKER_AGENT_INSTRUCTIONS = """You are the Plan2Sprint Smart Blocker Detection Agent.

Your job is to proactively identify blockers that developers haven't manually flagged.
You scan across multiple data sources to detect implied and hidden blockers.

## Process

1. Call `get_team_members` to get the roster.
2. Call `get_work_items` with no filters to see all active items.
3. Call `get_github_activity` with `since_hours=72` (3 days lookback).
4. Call `get_open_blockers` to see what's already flagged.
5. Call `get_health_signals` for any warning/critical signals.
6. Call `get_recent_activity_events` with `since_hours=72` for staleness detection.

## Detection Rules

**Stalled Work Items:**
- IN_PROGRESS for > 48 hours with no associated commits or PR activity → "stalled_ticket"
- High priority items (priority 1-2) that are TODO for > 3 days → "neglected_high_priority"

**PR Review Bottlenecks:**
- PRs open > 48 hours with no reviews → "review_bottleneck"
- PRs with CHANGES_REQUESTED for > 24 hours with no new commits → "stalled_pr"

**CI/Build Failures:**
- Open PRs with failing CI checks → "ci_blocker"

**Dependency Chains:**
- If item A references item B (via ticket refs in commits/PRs) and item B is blocked → "dependency_chain"

**Capacity Issues:**
- Developer with > 5 IN_PROGRESS items → "overloaded_developer"
- Developer with burnout_risk or high_wip health signals + open blockers → "compound_risk"

## Important
- Do NOT re-flag blockers that are already in `get_open_blockers` results.
- Only flag NEW implied blockers not yet reported.
- Include the affected work item ID and developer name.
- Assess severity: "low" (informational), "medium" (needs attention), "high" (sprint-threatening).

## Output Format

```json
{
  "detected_blockers": [
    {
      "type": "stalled_ticket | review_bottleneck | ci_blocker | dependency_chain | overloaded_developer | compound_risk | neglected_high_priority | stalled_pr",
      "severity": "low | medium | high",
      "affected_member_id": "member_id",
      "affected_member_name": "Developer Name",
      "ticket_reference": "PROJ-123 or PR #45 or null",
      "description": "Clear description of the blocker and why it was flagged.",
      "suggested_action": "What should be done to resolve this.",
      "evidence": "Brief evidence (e.g., 'No commits in 3 days, PR #42 has no reviews')"
    }
  ],
  "summary": "2-3 sentence summary of the team's blocker landscape.",
  "new_blockers_found": 3,
  "severity_breakdown": {"high": 1, "medium": 1, "low": 1}
}
```

Return valid JSON only. Do NOT invent data — only flag what the tools confirm.
"""


# ---------------------------------------------------------------------------
# Agent Runner
# ---------------------------------------------------------------------------

async def run_blocker_agent(
    db: AsyncSession,
    org_id: str,
) -> dict[str, Any]:
    """Run the Smart Blocker Detection agent."""
    if not orchestrator.is_configured:
        return {
            "success": False,
            "error": "Agent Service not configured",
            "detected_blockers": [],
        }

    config = AgentConfig(
        name="blocker-detector",
        instructions=BLOCKER_AGENT_INSTRUCTIONS,
        tools=build_blocker_detection_tools(),
        temperature=0.2,
        max_tokens=6144,
        max_tool_rounds=8,
    )

    context = {"db": db, "org_id": org_id}
    today = date.today()
    prompt = (
        f"Scan organization {org_id} for hidden and implied blockers. "
        f"Today is {today.isoformat()}. "
        f"Look back 72 hours for staleness and review bottlenecks."
    )

    logger.info(f"Running blocker detection agent for org {org_id}")
    result = await orchestrator.run(config, prompt, context)

    if not result.success:
        logger.warning(f"Blocker agent failed: {result.error}")
        return {
            "success": False,
            "error": result.error,
            "detected_blockers": [],
        }

    try:
        output = _parse_output(result.output)
    except Exception as e:
        logger.warning(f"Failed to parse blocker agent output: {e}")
        return {
            "success": False,
            "error": f"Parse error: {str(e)[:200]}",
            "detected_blockers": [],
        }

    # Save detected blockers as BlockerFlag records
    saved_count = await _save_detected_blockers(db, org_id, output.get("detected_blockers", []))

    return {
        "success": True,
        "detected_blockers": output.get("detected_blockers", []),
        "summary": output.get("summary", ""),
        "new_blockers_found": output.get("new_blockers_found", 0),
        "severity_breakdown": output.get("severity_breakdown", {}),
        "saved_to_db": saved_count,
        "tool_calls": len(result.tool_calls_made),
    }


def _parse_output(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return json.loads(text)


async def _save_detected_blockers(
    db: AsyncSession,
    org_id: str,
    blockers: list[dict],
) -> int:
    """Save agent-detected blockers as BlockerFlag records linked to a synthetic standup."""
    if not blockers:
        return 0

    today = date.today()
    saved = 0

    for b in blockers:
        member_id = b.get("affected_member_id")
        if not member_id:
            continue

        # Find or create today's standup for this member to attach the blocker
        existing_q = await db.execute(
            select(StandupReport).where(
                StandupReport.organization_id == org_id,
                StandupReport.team_member_id == member_id,
                func.date(StandupReport.report_date) == today,
            )
        )
        report = existing_q.scalar_one_or_none()

        if not report:
            # Create a minimal standup placeholder for the blocker
            report = StandupReport(
                organization_id=org_id,
                team_member_id=member_id,
                report_date=datetime.now(timezone.utc),
                completed_items=[],
                in_progress_items=[],
                blockers=[],
                narrative_text=f"Auto-generated for blocker detection on {today.isoformat()}",
                acknowledged=False,
                is_inactive=False,
            )
            db.add(report)
            await db.flush()

        # Create BlockerFlag
        flag = BlockerFlag(
            standup_report_id=report.id,
            description=f"[AI Detected - {b.get('type', 'unknown')}] {b.get('description', 'Implied blocker detected')}",
            ticket_reference=b.get("ticket_reference"),
            status="OPEN",
        )
        db.add(flag)
        saved += 1

    await db.commit()
    return saved

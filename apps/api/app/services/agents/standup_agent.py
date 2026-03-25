"""
Auto Standup Generator Agent — uses AI to generate rich standup reports.

Workflow:
  1. Agent gets team members via tool call
  2. For each member, pulls GitHub activity, work items, health signals
  3. Reasons across data to identify: completed work, in-progress, blockers
  4. Detects implied blockers (stalled PRs, long review waits, CI failures)
  5. Generates a natural-language standup report per developer
  6. Returns structured JSON that gets saved to StandupReport records

Falls back to the existing deterministic standup_generator if:
  - AI Agent Service is not configured
  - The agent run fails
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, date
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_orchestrator import AgentConfig, orchestrator
from ..agent_tools import build_standup_tools
from ...models.standup import StandupReport, TeamStandupDigest
from ...models.team_member import TeamMember
from ...models.iteration import Iteration
from ..standup_generator import generate_all_standups as deterministic_generate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent Instructions (system prompt)
# ---------------------------------------------------------------------------

STANDUP_AGENT_INSTRUCTIONS = """You are the Plan2Sprint Auto Standup Generator.

Your job is to generate daily standup reports for each developer on the team
by analyzing their recent activity across GitHub, Jira/ADO, and internal signals.

## Process

1. First, call `get_team_members` to get the full team roster.
2. For each team member, gather their data by calling:
   - `get_github_activity` with their `team_member_id` and `since_hours=24`
   - `get_work_items` with their `team_member_id`
   - `get_recent_activity_events` with their `team_member_id`
3. Also call `get_health_signals` and `get_open_blockers` once for the full team.
4. Optionally call `get_standup_history` to see what was reported yesterday
   (helps detect progress vs stalling).

## Analysis Rules

For each developer, determine:

**Completed:**
- Work items whose status changed to DONE in the last 24 hours
- Merged pull requests
- Resolved blockers

**In Progress:**
- Work items currently IN_PROGRESS or IN_REVIEW
- Open PRs awaiting review or with changes requested
- Active code reviews

**Blockers (explicit and implied):**
- Any open BlockerFlag records
- PRs open > 48 hours with no review → implied review bottleneck
- Work items IN_PROGRESS for > 3 days with no status change → implied stall
- CI/build failures on open PRs
- Health signals: burnout_risk, high_wip → flag as concern

**Inactive Members:**
- If a member has zero commits, zero PR activity, and no work item changes
  in the last 24 hours, mark them as inactive with a brief note.

## Output Format

Return a JSON object with this exact structure:
```json
{
  "standups": [
    {
      "team_member_id": "member_id_here",
      "display_name": "Developer Name",
      "completed_items": [
        {"title": "Implemented user auth", "ticketId": "PROJ-123"},
        {"title": "PR #45: Fix login bug", "prId": "45", "prStatus": "MERGED"}
      ],
      "in_progress_items": [
        {"title": "Building dashboard API", "ticketId": "PROJ-124"},
        {"title": "PR #47: Add caching layer", "prId": "47", "prStatus": "OPEN"}
      ],
      "blockers": [
        {"description": "Waiting on API spec from backend team", "ticketId": "PROJ-125", "status": "OPEN"},
        {"description": "PR #46 open 3 days with no review (implied)", "ticketId": null, "status": "IMPLIED"}
      ],
      "narrative": "A 2-3 sentence natural language summary of this developer's day.",
      "is_inactive": false,
      "implied_blockers_detected": 1,
      "health_concerns": ["high_wip"]
    }
  ],
  "team_summary": "A 2-3 sentence overall team summary including total completed, key blockers, and pacing.",
  "total_completed": 12,
  "total_blockers": 3,
  "implied_blockers": 2
}
```

## Important Rules
- Do NOT invent data. Only report what the tools actually return.
- Do NOT include developer emails or personal information in narratives.
- Use display_name for narrative text.
- Keep narratives concise (2-3 sentences max per developer).
- If tools return empty data for a member, mark them as inactive.
- Always return valid JSON.
"""


# ---------------------------------------------------------------------------
# Agent Runner
# ---------------------------------------------------------------------------

async def run_standup_agent(
    db: AsyncSession,
    org_id: str,
) -> dict[str, Any]:
    """
    Run the AI standup generation agent.

    Returns a summary dict compatible with the standup generation response format.
    Falls back to deterministic generation if the agent fails.
    """
    today = date.today()

    # Skip weekends
    if today.weekday() in (5, 6):
        return {"generated": 0, "skipped": "weekend", "agent_used": False}

    # Check if agent service is configured
    if not orchestrator.is_configured:
        logger.info("Agent Service not configured — falling back to deterministic standup generation")
        result = await deterministic_generate(db, org_id)
        result["agent_used"] = False
        return result

    # Build agent config
    config = AgentConfig(
        name="standup-generator",
        instructions=STANDUP_AGENT_INSTRUCTIONS,
        tools=build_standup_tools(),
        temperature=0.3,
        max_tokens=8192,
        max_tool_rounds=10,
    )

    # Run the agent
    context = {"db": db, "org_id": org_id}
    prompt = (
        f"Generate standup reports for organization {org_id}. "
        f"Today is {today.isoformat()}. "
        f"Pull data for the last 24 hours and generate reports for each team member."
    )

    logger.info(f"Running standup agent for org {org_id}")
    result = await orchestrator.run(config, prompt, context)

    if not result.success:
        logger.warning(f"Standup agent failed: {result.error} — falling back to deterministic")
        fallback = await deterministic_generate(db, org_id)
        fallback["agent_used"] = False
        fallback["agent_error"] = result.error
        return fallback

    # Parse the agent's JSON output
    try:
        agent_output = _parse_agent_output(result.output)
    except Exception as e:
        logger.warning(f"Failed to parse standup agent output: {e} — falling back")
        fallback = await deterministic_generate(db, org_id)
        fallback["agent_used"] = False
        fallback["agent_error"] = f"Parse error: {str(e)[:200]}"
        return fallback

    # Save to database
    saved = await _save_agent_standups(db, org_id, agent_output)

    return {
        "generated": saved["generated"],
        "inactive": saved["inactive"],
        "totalMembers": saved["total_members"],
        "digestGenerated": saved["digest_generated"],
        "agent_used": True,
        "tool_calls": len(result.tool_calls_made),
        "implied_blockers": agent_output.get("implied_blockers", 0),
    }


def _parse_agent_output(raw_text: str) -> dict:
    """Parse the agent's JSON response, handling markdown wrapping."""
    text = raw_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        import re
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)

    data = json.loads(text)

    # Validate required fields
    if "standups" not in data:
        raise ValueError("Agent output missing 'standups' key")

    return data


async def _save_agent_standups(
    db: AsyncSession,
    org_id: str,
    agent_output: dict,
) -> dict:
    """Save agent-generated standups to the database."""
    today = date.today()
    now = datetime.now(timezone.utc)

    # Find active iteration
    iter_result = await db.execute(
        select(Iteration)
        .where(
            Iteration.organization_id == org_id,
            Iteration.state == "active",
        )
        .order_by(Iteration.start_date.desc())
        .limit(1)
    )
    active_iter = iter_result.scalar_one_or_none()
    active_iteration_id = active_iter.id if active_iter else None

    generated = 0
    inactive = 0
    reports: list[StandupReport] = []

    for standup in agent_output.get("standups", []):
        member_id = standup.get("team_member_id")
        if not member_id:
            continue

        is_inactive = standup.get("is_inactive", False)
        completed = standup.get("completed_items", [])
        in_progress = standup.get("in_progress_items", [])
        blockers = standup.get("blockers", [])
        narrative = standup.get("narrative", "")

        # Include implied blockers in the blockers list
        # (the agent flags them with status: "IMPLIED")

        # Upsert StandupReport
        existing_q = await db.execute(
            select(StandupReport).where(
                StandupReport.organization_id == org_id,
                StandupReport.team_member_id == member_id,
                func.date(StandupReport.report_date) == today,
            )
        )
        report = existing_q.scalar_one_or_none()

        if report:
            report.completed_items = completed
            report.in_progress_items = in_progress
            report.blockers = blockers
            report.narrative_text = narrative
            report.iteration_id = active_iteration_id
            report.is_inactive = is_inactive
        else:
            report = StandupReport(
                organization_id=org_id,
                team_member_id=member_id,
                iteration_id=active_iteration_id,
                report_date=now,
                completed_items=completed,
                in_progress_items=in_progress,
                blockers=blockers,
                narrative_text=narrative,
                acknowledged=False,
                is_inactive=is_inactive,
            )
            db.add(report)

        reports.append(report)
        if is_inactive:
            inactive += 1
        else:
            generated += 1

    # Generate team digest from agent summary
    team_summary = agent_output.get("team_summary", "")
    total_completed = agent_output.get("total_completed", 0)
    total_blockers = agent_output.get("total_blockers", 0)

    digest_generated = False
    if reports:
        try:
            await _save_team_digest(
                db, org_id, active_iteration_id, reports,
                team_summary, total_completed, total_blockers,
            )
            digest_generated = True
        except Exception as e:
            logger.warning(f"Failed to save team digest: {e}")

    await db.commit()

    return {
        "generated": generated,
        "inactive": inactive,
        "total_members": len(reports),
        "digest_generated": digest_generated,
    }


async def _save_team_digest(
    db: AsyncSession,
    org_id: str,
    iteration_id: str | None,
    reports: list[StandupReport],
    summary_text: str,
    total_completed: int,
    total_blockers: int,
) -> None:
    """Save or update the team standup digest."""
    today = date.today()

    total_reports = len(reports)
    acknowledged = sum(1 for r in reports if r.acknowledged)
    ack_pct = int((acknowledged / total_reports) * 100) if total_reports > 0 else 0

    # Simple pacing estimate
    active_reports = [r for r in reports if not r.is_inactive]
    sprint_pacing = int((len(active_reports) / max(total_reports, 1)) * 100)

    # Sprint health from blockers
    if total_blockers == 0 and sprint_pacing >= 80:
        health = "GREEN"
    elif total_blockers <= 2:
        health = "AMBER"
    else:
        health = "RED"

    existing_q = await db.execute(
        select(TeamStandupDigest).where(
            TeamStandupDigest.organization_id == org_id,
            func.date(TeamStandupDigest.digest_date) == today,
        )
    )
    digest = existing_q.scalar_one_or_none()

    if digest:
        digest.sprint_pacing = sprint_pacing
        digest.acknowledged_pct = ack_pct
        digest.sprint_health = health
        digest.blocker_count = total_blockers
        digest.summary_text = summary_text or f"Team completed {total_completed} items. {total_blockers} blockers active."
        digest.iteration_id = iteration_id
    else:
        digest = TeamStandupDigest(
            organization_id=org_id,
            iteration_id=iteration_id,
            digest_date=datetime.now(timezone.utc),
            sprint_pacing=sprint_pacing,
            acknowledged_pct=ack_pct,
            sprint_health=health,
            at_risk_items={"items": []},
            blocker_count=total_blockers,
            summary_text=summary_text or f"Team completed {total_completed} items. {total_blockers} blockers active.",
        )
        db.add(digest)

"""
Sprint Health Coach Agent — correlates health signals and generates actionable recommendations.

Runs periodically (or on demand) to:
  1. Evaluate all active health signals for the team
  2. Correlate signals into compound risks (burnout + stalled + review lag)
  3. Compare sprint pacing vs historical velocity
  4. Generate actionable recommendations with severity-based routing
  5. Route alerts: in-app for low, notification for medium/high
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_orchestrator import AgentConfig, orchestrator
from ..agent_tools import build_health_coach_tools

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------

HEALTH_COACH_INSTRUCTIONS = """You are the Plan2Sprint Sprint Health Coach.

Your job is to analyze the team's current sprint health by correlating multiple
signals, then generate specific, actionable recommendations. You act as an
experienced Agile coach who catches problems early.

## Process

1. Call `get_sprint_forecast` to understand current sprint pacing and timeline.
2. Call `get_team_members` to get the full roster.
3. Call `get_health_signals` to see all active signals.
4. Call `get_velocity_data` to compare current pace vs historical averages.
5. Call `get_open_blockers` for active blockers.
6. Call `get_work_items` to see workload distribution.
7. Call `get_standup_history` with `days=5` to detect patterns from recent standups.

## Analysis Framework

**Sprint Pacing Analysis:**
- Compare completion_pct vs time_pct from sprint forecast
- If completion < 70% of time elapsed → "behind_pace"
- If SP remaining > team velocity_avg × days_remaining → "scope_risk"

**Individual Risk Assessment (per developer):**
- Compound risk: multiple signals on same person (burnout + high_wip + after_hours)
- Overload: assigned SP > 120% of rolling_average
- Underutilization: assigned SP < 50% of rolling_average with available capacity
- Stalling: no standup activity changes for 2+ days

**Team-Level Patterns:**
- Bottleneck skill: multiple blocked items needing same skill
- Review backlog: multiple PRs awaiting review
- Blocker clustering: 3+ blockers in same sprint week

**Severity Assignment:**
- LOW: informational, no action needed immediately (e.g., minor pacing variance)
- MEDIUM: needs attention this sprint (e.g., developer overloaded, review backlog)
- HIGH: sprint-threatening, act now (e.g., behind pace with 3+ days of blockers, burnout risk on critical-path dev)

## Output Format

```json
{
  "sprint_health_score": 72,
  "sprint_health_label": "AMBER",
  "pacing_analysis": {
    "on_track": false,
    "completion_pct": 35.2,
    "time_pct": 60.0,
    "risk": "behind_pace",
    "details": "Sprint is 60% through time but only 35% complete."
  },
  "recommendations": [
    {
      "severity": "high | medium | low",
      "category": "pacing | workload | blocker | health | process",
      "title": "Short action title",
      "description": "Detailed recommendation with specific names and ticket IDs.",
      "affected_members": ["member_id_1"],
      "affected_tickets": ["PROJ-123"],
      "suggested_action": "Specific step to take."
    }
  ],
  "individual_risks": [
    {
      "team_member_id": "id",
      "display_name": "Name",
      "risk_level": "high | medium | low",
      "signals": ["burnout_risk", "high_wip"],
      "recommendation": "Specific recommendation for this person."
    }
  ],
  "summary": "3-4 sentence executive summary of sprint health for the PO.",
  "total_recommendations": 5,
  "severity_breakdown": {"high": 1, "medium": 2, "low": 2}
}
```

## Rules
- Be specific — name developers and ticket IDs in recommendations.
- Be actionable — every recommendation must have a clear "do this" step.
- Do NOT generate recommendations for things that are going well.
- If the sprint is healthy, say so clearly with a low recommendation count.
- Always return valid JSON.
"""


# ---------------------------------------------------------------------------
# Agent Runner
# ---------------------------------------------------------------------------

async def run_health_coach_agent(
    db: AsyncSession,
    org_id: str,
) -> dict[str, Any]:
    """Run the Sprint Health Coach agent."""
    if not orchestrator.is_configured:
        return {
            "success": False,
            "error": "Agent Service not configured",
            "recommendations": [],
        }

    config = AgentConfig(
        name="health-coach",
        instructions=HEALTH_COACH_INSTRUCTIONS,
        tools=build_health_coach_tools(),
        temperature=0.3,
        max_tokens=8192,
        max_tool_rounds=10,
    )

    context = {"db": db, "org_id": org_id}
    today = date.today()
    prompt = (
        f"Analyze sprint health for organization {org_id}. "
        f"Today is {today.isoformat()}. "
        f"Assess pacing, individual risks, team patterns, and generate actionable recommendations."
    )

    logger.info(f"Running health coach agent for org {org_id}")
    result = await orchestrator.run(config, prompt, context)

    if not result.success:
        logger.warning(f"Health coach agent failed: {result.error}")
        return {
            "success": False,
            "error": result.error,
            "recommendations": [],
        }

    try:
        output = _parse_output(result.output)
    except Exception as e:
        logger.warning(f"Failed to parse health coach output: {e}")
        return {
            "success": False,
            "error": f"Parse error: {str(e)[:200]}",
            "recommendations": [],
        }

    return {
        "success": True,
        "sprint_health_score": output.get("sprint_health_score"),
        "sprint_health_label": output.get("sprint_health_label"),
        "pacing_analysis": output.get("pacing_analysis"),
        "recommendations": output.get("recommendations", []),
        "individual_risks": output.get("individual_risks", []),
        "summary": output.get("summary", ""),
        "total_recommendations": output.get("total_recommendations", 0),
        "severity_breakdown": output.get("severity_breakdown", {}),
        "tool_calls": len(result.tool_calls_made),
    }


def _parse_output(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return json.loads(text)

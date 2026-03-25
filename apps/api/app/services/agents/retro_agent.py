"""
AI Retrospective Synthesizer Agent — generates data-backed sprint retrospectives.

Aggregates:
  - Sprint metrics (planned vs delivered SP, carry-forward items)
  - Blocker history and resolution timeline
  - Health signal timeline throughout the sprint
  - Velocity trends (this sprint vs historical)
  - Standup report themes (repeated blockers, recurring delays)
  - Past retrospectives for recurring patterns

Generates structured retro output and creates SprintConstraint feed-forward records.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone, date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_orchestrator import AgentConfig, orchestrator
from ..agent_tools import build_retro_tools
from ...models.retrospective import Retrospective, RetroActionItem
from ...models.sprint_constraint import SprintConstraint
from ...models.base import generate_cuid

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------

RETRO_AGENT_INSTRUCTIONS = """You are the Plan2Sprint AI Retrospective Synthesizer.

Your job is to generate a comprehensive, data-backed sprint retrospective by
analyzing actual sprint data rather than relying on subjective recollections.

## Process

1. Call `get_sprint_forecast` to get current sprint metrics (completion %, SP, pacing).
2. Call `get_team_members` to know the roster.
3. Call `get_work_items` to see final state of all items (DONE, IN_PROGRESS, TODO).
4. Call `get_velocity_data` to compare this sprint's velocity vs historical average.
5. Call `get_health_signals` for the full signal timeline this sprint.
6. Call `get_open_blockers` for any unresolved blockers.
7. Call `get_standup_history` with `days=14` to extract themes from daily standups.
8. Call `get_retro_history` to check for recurring patterns from past retrospectives.
9. Call `get_sprint_plan_data` to compare planned assignments vs actual outcomes.

## Analysis Framework

**What Went Well (data-backed):**
- Items completed ahead of schedule (done before sprint midpoint)
- High-confidence assignments that delivered (confidence > 0.8 and status = DONE)
- Blockers that were resolved quickly (< 24 hours)
- Developers who exceeded their velocity average
- PRs merged with fast review turnaround

**What Didn't Go Well (with root causes):**
- Carry-forward items (IN_PROGRESS or TODO at sprint end) — why?
- Blockers that lasted > 48 hours — what delayed resolution?
- Velocity shortfall — overcommitment vs execution vs dependencies?
- Health signal spikes — when did problems emerge and what caused them?
- Repeated themes from standups (same blocker mentioned 3+ times)

**Root Cause Classification:**
Classify the primary failure mode (if sprint didn't meet 85% completion):
- OVERCOMMITMENT: assigned more SP than team velocity supports
- EXECUTION: work started but didn't finish (PR lag, testing delays)
- DEPENDENCY: external blockers outside team control
- CAPACITY: key developer was unavailable or overloaded
- SCOPE_CREEP: new tickets added mid-sprint

**Recurring Patterns:**
- Cross-reference with past 3 retros for themes that repeat
- Flag carry-forward action items from past retros that are still open

**Action Items:**
- Each must be specific, assignable, and time-bound
- Tag action items that are feed-forward constraints for the next sprint
- Prioritize: max 5 action items (focused > comprehensive)

## Output Format

```json
{
  "sprint_summary": {
    "iteration_id": "sprint_id_if_available",
    "planned_sp": 85,
    "completed_sp": 68,
    "completion_pct": 80.0,
    "carry_forward_count": 4,
    "blocker_count": 3,
    "team_size": 5
  },
  "what_went_well": [
    {
      "observation": "Clear data-backed statement of what went well.",
      "evidence": "Specific ticket IDs, names, or metrics supporting this.",
      "impact": "Why this matters."
    }
  ],
  "what_didnt_go_well": [
    {
      "observation": "Clear data-backed statement of what went poorly.",
      "root_cause": "Why this happened (specific, not generic).",
      "evidence": "Specific ticket IDs, blocker timelines, or metrics.",
      "impact": "SP or days lost, or sprint risk incurred."
    }
  ],
  "root_cause_analysis": {
    "primary_classification": "OVERCOMMITMENT | EXECUTION | DEPENDENCY | CAPACITY | SCOPE_CREEP | NONE",
    "explanation": "Why this classification fits the data.",
    "contributing_factors": ["factor1", "factor2"]
  },
  "recurring_patterns": [
    {
      "pattern": "Description of the recurring issue.",
      "sprints_affected": 3,
      "trend": "worsening | stable | improving"
    }
  ],
  "action_items": [
    {
      "title": "Specific action to take.",
      "description": "Detailed explanation.",
      "suggested_owner": "team_member_id or role (e.g., 'PO', 'Tech Lead')",
      "priority": "high | medium",
      "is_feed_forward": true,
      "feed_forward_rule": "If is_feed_forward, the constraint to apply to next sprint (e.g., 'Limit WIP to 3 per developer')"
    }
  ],
  "summary": "3-5 sentence executive summary covering the sprint outcome, key wins, main problems, and top recommended action."
}
```

## Rules
- Be honest and specific — don't sugarcoat problems but don't be harsh.
- Every "what didn't go well" MUST have a root cause, not just a description.
- Action items must be concrete — "improve communication" is too vague.
- If the sprint was successful (>= 85% completion), celebrate it but still look for improvements.
- Always return valid JSON.
"""


# ---------------------------------------------------------------------------
# Agent Runner
# ---------------------------------------------------------------------------

async def run_retro_agent(
    db: AsyncSession,
    org_id: str,
    iteration_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Run the AI Retrospective Synthesizer agent."""
    if not orchestrator.is_configured:
        return {
            "success": False,
            "error": "Agent Service not configured",
        }

    config = AgentConfig(
        name="retro-synthesizer",
        instructions=RETRO_AGENT_INSTRUCTIONS,
        tools=build_retro_tools(),
        temperature=0.3,
        max_tokens=10240,
        max_tool_rounds=12,
    )

    context = {"db": db, "org_id": org_id}
    today = date.today()
    iter_clause = f" for iteration {iteration_id}" if iteration_id else ""
    prompt = (
        f"Generate a data-backed retrospective for organization {org_id}{iter_clause}. "
        f"Today is {today.isoformat()}. "
        f"Analyze the sprint thoroughly — what went well, what didn't, root causes, "
        f"recurring patterns, and specific action items."
    )

    logger.info(f"Running retro agent for org {org_id}")
    result = await orchestrator.run(config, prompt, context)

    if not result.success:
        logger.warning(f"Retro agent failed: {result.error}")
        return {"success": False, "error": result.error}

    try:
        output = _parse_output(result.output)
    except Exception as e:
        logger.warning(f"Failed to parse retro agent output: {e}")
        return {"success": False, "error": f"Parse error: {str(e)[:200]}"}

    # Save retrospective to DB
    retro_id = await _save_retro(db, org_id, iteration_id, output)

    # Save feed-forward constraints
    constraints_saved = 0
    if project_id:
        constraints_saved = await _save_feed_forward(
            db, org_id, project_id, output.get("action_items", [])
        )

    return {
        "success": True,
        "retro_id": retro_id,
        "sprint_summary": output.get("sprint_summary"),
        "what_went_well_count": len(output.get("what_went_well", [])),
        "what_didnt_go_well_count": len(output.get("what_didnt_go_well", [])),
        "root_cause": output.get("root_cause_analysis", {}).get("primary_classification"),
        "recurring_patterns": len(output.get("recurring_patterns", [])),
        "action_items_count": len(output.get("action_items", [])),
        "constraints_saved": constraints_saved,
        "summary": output.get("summary", ""),
        "tool_calls": len(result.tool_calls_made),
        # Full output for frontend rendering
        "what_went_well": output.get("what_went_well", []),
        "what_didnt_go_well": output.get("what_didnt_go_well", []),
        "root_cause_analysis": output.get("root_cause_analysis"),
        "action_items": output.get("action_items", []),
    }


def _parse_output(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return json.loads(text)


async def _save_retro(
    db: AsyncSession,
    org_id: str,
    iteration_id: str | None,
    output: dict,
) -> str:
    """Save the AI-generated retrospective to the database."""
    rca = output.get("root_cause_analysis", {})

    retro = Retrospective(
        organization_id=org_id,
        iteration_id=iteration_id,
        what_went_well=output.get("what_went_well", []),
        what_didnt_go_well=output.get("what_didnt_go_well", []),
        root_cause_analysis=rca,
        failure_classification=rca.get("primary_classification"),
        failure_evidence=rca.get("contributing_factors"),
        pattern_detected=len(output.get("recurring_patterns", [])) > 0,
        consecutive_failure_count=0,
        feed_forward_signals=[
            ai for ai in output.get("action_items", [])
            if ai.get("is_feed_forward")
        ],
        is_draft=False,
        finalized_at=datetime.now(timezone.utc),
    )
    db.add(retro)
    await db.flush()

    # Save action items
    for ai in output.get("action_items", []):
        action = RetroActionItem(
            retrospective_id=retro.id,
            title=ai.get("title", "Untitled action"),
            assignee_id=ai.get("suggested_owner"),
            status="open",
            is_carry_forward=ai.get("is_feed_forward", False),
        )
        db.add(action)

    await db.commit()
    return retro.id


async def _save_feed_forward(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    action_items: list[dict],
) -> int:
    """Save feed-forward action items as SprintConstraint records."""
    saved = 0
    for ai in action_items:
        if not ai.get("is_feed_forward"):
            continue

        constraint = SprintConstraint(
            organization_id=org_id,
            project_id=project_id,
            source="ai_retro_agent",
            constraint_data={
                "type": "feed_forward",
                "rule": ai.get("feed_forward_rule", ai.get("title", "")),
                "reason": ai.get("description", ""),
                "priority": ai.get("priority", "medium"),
            },
            expires_after_sprints=3,
            sprints_applied=0,
        )
        db.add(constraint)
        saved += 1

    if saved > 0:
        await db.commit()
    return saved

"""
AI Sprint Generation Service — Azure AI Foundry (Grok) powered sprint plan generation.

Replaces the deterministic optimizer with an AI-powered pipeline:
  1. Assemble context from DB (backlog, team, velocity, blockers)
  2. Scrub PII (replace names/emails with DEV_001 tokens)
  3. Build structured prompt with real data
  4. Call Azure AI Foundry (Grok) via OpenAI-compatible chat completions API
  5. Parse JSON response and validate schema
  6. Reconstruct PII (replace tokens back to real identities)
  7. Calculate plan-level metrics
  8. Store SprintPlan + PlanAssignment records in DB

Falls back to the deterministic optimizer if:
  - No Azure AI API key is configured
  - The AI call fails
  - The response is malformed
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.base import generate_cuid
from ..models.sprint_plan import SprintPlan, PlanAssignment
from ..models.work_item import WorkItem
from ..models.team_member import TeamMember
from ..models.iteration import Iteration
from ..models.standup import BlockerFlag
from ..models.analytics import HealthSignal
from ..models.imported_project import ImportedProject

logger = logging.getLogger(__name__)

AI_MODEL = settings.azure_ai_model or "grok-4-fast-reasoning"


# ---------------------------------------------------------------------------
# PII Scrubbing
# ---------------------------------------------------------------------------

def build_token_map(members: list[TeamMember]) -> dict[str, str]:
    """Build mapping: 'Sangini Tripathi' → 'DEV_001', etc."""
    token_map: dict[str, str] = {}
    for i, m in enumerate(members, 1):
        token = f"DEV_{i:03d}"
        token_map[m.display_name] = token
        if m.email:
            token_map[m.email] = token
        token_map[m.id] = token
    return token_map


def scrub_pii(text: str, token_map: dict[str, str]) -> str:
    """Replace all PII in text with tokens."""
    result = text
    # Sort by length descending to avoid partial replacements
    for real_value in sorted(token_map.keys(), key=len, reverse=True):
        if real_value and real_value in result:
            result = result.replace(real_value, token_map[real_value])
    return result


def reconstruct_pii(text: str, reverse_map: dict[str, str]) -> str:
    """Replace tokens back with real identities."""
    result = text
    for token, real_value in reverse_map.items():
        result = result.replace(token, real_value)
    return result


# ---------------------------------------------------------------------------
# Feed-Forward Constraints
# ---------------------------------------------------------------------------

async def load_active_constraints(
    db: AsyncSession,
    org_id: str,
    project_id: str,
) -> list[dict]:
    """Load active sprint constraints that haven't expired yet."""
    from ..models.sprint_constraint import SprintConstraint

    result = await db.execute(
        select(SprintConstraint).where(
            SprintConstraint.organization_id == org_id,
            SprintConstraint.project_id == project_id,
        )
    )
    constraints = []
    for sc in result.scalars().all():
        expires = sc.expires_after_sprints or 3
        if sc.sprints_applied < expires:
            data = sc.constraint_data if isinstance(sc.constraint_data, dict) else {}
            constraints.append({
                "id": sc.id,
                "source": sc.source,
                "type": data.get("type", "unknown"),
                "rule": data.get("rule", str(data)),
                "reason": data.get("reason", ""),
            })
    return constraints


async def increment_constraints_applied(
    db: AsyncSession,
    org_id: str,
    project_id: str,
) -> None:
    """Increment sprints_applied counter for all active constraints after use."""
    from ..models.sprint_constraint import SprintConstraint

    result = await db.execute(
        select(SprintConstraint).where(
            SprintConstraint.organization_id == org_id,
            SprintConstraint.project_id == project_id,
        )
    )
    for sc in result.scalars().all():
        expires = sc.expires_after_sprints or 3
        if sc.sprints_applied < expires:
            sc.sprints_applied += 1


def _format_constraints(constraints: list[dict] | None) -> str:
    """Format feed-forward constraints as a prompt section."""
    if not constraints:
        return ""

    lines = [
        "HARD CONSTRAINTS (from failure analysis — these override default behavior):"
    ]
    for i, c in enumerate(constraints, 1):
        lines.append(f"  {i}. [{c['type'].upper()}] {c['rule']}")
        if c.get("reason"):
            lines.append(f"     Reason: {c['reason']}")
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------

def build_sprint_prompt(
    backlog_items: list[dict],
    team_members: list[dict],
    iteration: dict,
    velocity_map: dict[str, dict],
    health_signals: list[dict],
    blocked_item_ids: set[str],
    carry_forward_items: list[dict],
    feedback: str | None,
    constraints: list[dict] | None = None,
) -> str:
    """Build the LLM prompt with real scrubbed data."""

    # Format backlog items
    backlog_text = ""
    for item in backlog_items:
        blocked = " [BLOCKED]" if item["id"] in blocked_item_ids else ""
        backlog_text += (
            f"  - ID: {item['id']} | Title: {item['title']} | Type: {item['type']} | "
            f"Priority: {item['priority']} | SP: {item.get('story_points') or 'unestimated'} | "
            f"Status: {item['status']}{blocked}\n"
        )

    # Format carry-forward items
    carry_text = ""
    if carry_forward_items:
        for item in carry_forward_items:
            carry_text += (
                f"  - ID: {item['id']} | Title: {item['title']} | "
                f"SP: {item.get('story_points') or 'unestimated'} | "
                f"Status: {item['status']} (carry-forward from previous sprint)\n"
            )
    else:
        carry_text = "  None\n"

    # Calculate sprint duration for capacity context
    try:
        from datetime import datetime as _dt
        _start = _dt.fromisoformat(str(iteration.get("startDate", "")))
        _end = _dt.fromisoformat(str(iteration.get("endDate", "")))
        sprint_days = max(1, (_end - _start).days)
    except (ValueError, TypeError):
        sprint_days = 14  # Default 2-week sprint

    # Format team members with velocity and computed SP capacity
    team_text = ""
    total_team_capacity = 0.0
    for member in team_members:
        vel = velocity_map.get(member["token"], {})
        avg_sp = vel.get("avg_sp", 15)
        cold = " (cold-start estimate)" if vel.get("is_cold_start") else ""
        hours_per_week = member.get("capacity", 40)
        skills = ", ".join(member.get("skills", [])) if member.get("skills") else "general"

        # Compute SP capacity for this sprint duration
        weeks = sprint_days / 7.0
        sp_capacity = round(hours_per_week * weeks / 5.0, 0)  # ~5h per SP
        # Use the higher of velocity or capacity estimate
        effective_capacity = max(avg_sp, sp_capacity)
        total_team_capacity += effective_capacity

        # Health warnings
        health_warnings = ""
        for hs in health_signals:
            if hs.get("member_token") == member["token"]:
                health_warnings += f" ⚠ {hs['signal_type']}"

        team_text += (
            f"  - {member['token']} | Skills: {skills} | "
            f"Velocity: {avg_sp:.0f} SP/sprint{cold} | "
            f"Sprint capacity (per sprint): {effective_capacity:.0f} SP | "
            f"Hours: {hours_per_week}h/week{health_warnings}\n"
        )

    # Build sprint info
    sprint_name = iteration.get("name", "Current Sprint")
    sprint_goal = iteration.get("goal") or "No specific goal set"
    start_date = iteration.get("startDate", "unknown")
    end_date = iteration.get("endDate", "unknown")

    # Regeneration feedback
    feedback_section = ""
    if feedback:
        feedback_section = f"""
REGENERATION FEEDBACK:
The Product Owner rejected the previous plan with this feedback:
  "{feedback}"
Take this into account when generating the new plan.
"""

    prompt = f"""You are a sprint planning AI for an agile development team. Your job is to create a COMPLETE project plan by assigning ALL backlog items to developers across multiple sprints.

SPRINT CONTEXT:
- Sprint duration: {sprint_days} days per sprint ({start_date} → {end_date} is Sprint 1)
- Goal: {sprint_goal}
- Team capacity per sprint: ~{total_team_capacity:.0f} story points

AVAILABLE DEVELOPERS (only these people can be assigned work):
{team_text}
NOTE: Only the developers listed above are available for assignments. There may be other team members (POs, stakeholders) who are NOT developers and must NOT receive assignments.

CARRY-FORWARD ITEMS (must be included in Sprint 1 if possible):
{carry_text}

BACKLOG ITEMS (ordered by priority, highest first):
{backlog_text}
{feedback_section}
{_format_constraints(constraints)}RULES:
1. Assign ALL items to developers — do NOT leave items unplanned unless they are [BLOCKED].
2. If the total work exceeds one sprint's capacity, spread items across multiple sprints (Sprint 1, Sprint 2, Sprint 3, etc.). Each sprint has the same duration ({sprint_days} days).
3. Higher-priority items go into earlier sprints. Sprint 1 gets the most critical work.
4. Use each developer's "Sprint capacity (per sprint)" as their maximum SP per sprint. A developer can be assigned work in multiple sprints.
5. Carry-forward items should be prioritized in Sprint 1.
6. [BLOCKED] items must NOT be assigned — include them in unplanned_items with reason.
7. Items without story points: estimate based on type (story=5, bug=3, task=2, feature=8, epic=13).
8. For each assignment, provide a rationale and a sprint_number (1, 2, 3, etc.).
9. Calculate a confidence score (0.0 to 1.0) for each assignment.
10. Provide estimated_sprints (total number of sprints needed to complete ALL work).
11. IMPORTANT: Every non-blocked item MUST be assigned. The plan should cover the entire backlog across however many sprints are needed.

Respond with ONLY a JSON object (no markdown, no explanation outside JSON) matching this schema:

{{
  "overall_rationale": "string — 2-3 sentence summary including how many sprints needed and why",
  "goal_attainment_confidence": 0.85,
  "risk_level": "LOW | MODERATE | HIGH",
  "estimated_sprints": 3,
  "assignments": [
    {{
      "work_item_id": "string — the item ID from the backlog",
      "assignee_token": "string — e.g. DEV_001",
      "story_points": 5,
      "sprint_number": 1,
      "confidence_score": 0.85,
      "rationale": "string — why this person for this item",
      "risk_flags": ["skill_gap", "overloaded"]
    }}
  ],
  "unplanned_items": [
    {{
      "work_item_id": "string",
      "reason": "string — only for BLOCKED items"
    }}
  ]
}}"""

    return prompt


# ---------------------------------------------------------------------------
# Main Generation Function
# ---------------------------------------------------------------------------

async def generate_sprint_plan_ai(
    db: AsyncSession,
    org_id: str,
    project_id: str,
    iteration_id: str | None = None,
    feedback: str | None = None,
) -> dict[str, Any]:
    """
    Generate a sprint plan using Claude AI.

    Returns dict with plan details and assignment summary.
    Falls back to deterministic optimizer if AI is unavailable.
    """

    # -----------------------------------------------------------------------
    # 1. Check if Azure AI API key is available
    # -----------------------------------------------------------------------
    if not settings.azure_ai_api_key or not settings.azure_ai_endpoint:
        logger.info("No Azure AI API key/endpoint — falling back to deterministic optimizer")
        from .sprint_optimizer import generate_sprint_plan
        return await generate_sprint_plan(db, org_id, project_id, iteration_id, feedback)

    # -----------------------------------------------------------------------
    # 2. Resolve iteration
    # -----------------------------------------------------------------------
    if iteration_id:
        result = await db.execute(
            select(Iteration).where(Iteration.id == iteration_id)
        )
        iteration = result.scalar_one_or_none()
    else:
        query = select(Iteration).where(Iteration.organization_id == org_id)
        if project_id:
            query = query.where(Iteration.imported_project_id == project_id)
        query = query.order_by(Iteration.start_date.desc()).limit(1)
        result = await db.execute(query)
        iteration = result.scalar_one_or_none()

        if not iteration and project_id:
            result = await db.execute(
                select(Iteration)
                .where(Iteration.organization_id == org_id)
                .order_by(Iteration.start_date.desc())
                .limit(1)
            )
            iteration = result.scalar_one_or_none()

    if not iteration:
        return {"error": "No active iteration found for this project"}

    # -----------------------------------------------------------------------
    # 3. Load project for source_tool context
    # -----------------------------------------------------------------------
    proj_result = await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == project_id,
            ImportedProject.organization_id == org_id,
        )
    )
    project = proj_result.scalar_one_or_none()
    source_tool = (project.source_tool or "ado").lower() if project else "ado"

    # -----------------------------------------------------------------------
    # 4. Load team members — only developers get assignments
    # -----------------------------------------------------------------------
    tm_result = await db.execute(
        select(TeamMember).where(TeamMember.organization_id == org_id)
    )
    all_members = list(tm_result.scalars().all())
    # Filter to developers only for assignment purposes
    members = [m for m in all_members if m.role == "developer"]
    if not members:
        return {"error": "No developers found in the team. Mark at least one team member as a developer."}

    # -----------------------------------------------------------------------
    # 5. Load work items (plannable)
    # -----------------------------------------------------------------------
    wi_query = (
        select(WorkItem)
        .where(
            WorkItem.organization_id == org_id,
            WorkItem.status.in_(["BACKLOG", "TODO", "IN_PROGRESS", "IN_REVIEW"]),
        )
    )
    if project_id:
        wi_query = wi_query.where(WorkItem.imported_project_id == project_id)
    wi_query = wi_query.order_by(WorkItem.priority.asc(), WorkItem.created_at.asc())
    wi_result = await db.execute(wi_query)
    work_items = list(wi_result.scalars().all())

    if not work_items:
        return {"error": "No work items available for planning"}

    # -----------------------------------------------------------------------
    # 6. Load velocity profiles
    # -----------------------------------------------------------------------
    from .velocity_calculator import calculate_velocity_profiles
    velocity_map = await calculate_velocity_profiles(db, org_id, members)

    # -----------------------------------------------------------------------
    # 7. Load health signals and blockers
    # -----------------------------------------------------------------------
    hs_result = await db.execute(
        select(HealthSignal).where(
            HealthSignal.organization_id == org_id,
            HealthSignal.resolved_at.is_(None),
        )
    )
    health_signals_db = list(hs_result.scalars().all())

    # Load active blockers — BlockerFlag links through StandupReport, uses ticket_reference
    from ..models.standup import StandupReport
    blocker_result = await db.execute(
        select(BlockerFlag.ticket_reference)
        .join(StandupReport, BlockerFlag.standup_report_id == StandupReport.id)
        .where(
            StandupReport.organization_id == org_id,
            BlockerFlag.resolved_at.is_(None),
            BlockerFlag.ticket_reference.isnot(None),
        )
    )
    ticket_refs = set(blocker_result.scalars().all())
    if ticket_refs:
        blocked_wi_result = await db.execute(
            select(WorkItem.id).where(
                WorkItem.organization_id == org_id,
                WorkItem.external_id.in_(ticket_refs),
            )
        )
        blocked_item_ids = set(blocked_wi_result.scalars().all())
    else:
        blocked_item_ids: set[str] = set()

    # -----------------------------------------------------------------------
    # 7b. Load feed-forward constraints from failure analysis
    # -----------------------------------------------------------------------
    active_constraints = await load_active_constraints(db, org_id, project_id)
    if active_constraints:
        logger.info(f"Loaded {len(active_constraints)} active feed-forward constraints")

    # -----------------------------------------------------------------------
    # 8. PII Scrubbing
    # -----------------------------------------------------------------------
    token_map = build_token_map(members)
    reverse_map = {v: k for k, v in token_map.items() if k == next(
        (m.display_name for m in members if m.id == k or m.display_name == k), ""
    )}
    # Build proper reverse map: token → display_name
    reverse_map = {}
    for m in members:
        token = token_map.get(m.display_name, token_map.get(m.id, ""))
        if token:
            reverse_map[token] = m.display_name

    # Build token → member_id map for assignment resolution
    token_to_member_id: dict[str, str] = {}
    for m in members:
        token = token_map.get(m.display_name, token_map.get(m.id, ""))
        if token:
            token_to_member_id[token] = m.id

    # -----------------------------------------------------------------------
    # 9. Build prompt data (scrubbed)
    # -----------------------------------------------------------------------

    # Separate carry-forward vs backlog
    carry_forward = [wi for wi in work_items if wi.iteration_id == iteration.id and wi.status in ("IN_PROGRESS", "IN_REVIEW")]
    backlog = [wi for wi in work_items if wi not in carry_forward]

    # Sprint capacity calculation
    sprint_days = max(1, (iteration.end_date.replace(tzinfo=None) - iteration.start_date.replace(tzinfo=None)).days)
    weeks = sprint_days / 7.0

    def _wi_to_dict(wi: WorkItem) -> dict:
        return {
            "id": wi.id,
            "title": scrub_pii(wi.title, token_map),
            "type": wi.type or "story",
            "priority": wi.priority,
            "story_points": wi.story_points,
            "status": wi.status,
        }

    def _member_to_dict(m: TeamMember) -> dict:
        token = token_map.get(m.display_name, f"DEV_{members.index(m)+1:03d}")
        return {
            "token": token,
            "skills": m.skill_tags or [],
            "capacity": m.default_capacity,
        }

    scrubbed_backlog = [_wi_to_dict(wi) for wi in backlog]
    scrubbed_carry = [_wi_to_dict(wi) for wi in carry_forward]
    scrubbed_team = [_member_to_dict(m) for m in members]

    scrubbed_health = []
    for hs in health_signals_db:
        member_token = token_map.get(
            next((m.display_name for m in members if m.id == hs.team_member_id), ""),
            "UNKNOWN"
        )
        scrubbed_health.append({
            "member_token": member_token,
            "signal_type": hs.signal_type,
            "severity": hs.severity,
        })

    # Token-keyed velocity map for the prompt
    token_velocity: dict[str, dict] = {}
    for m in members:
        token = token_map.get(m.display_name, "")
        if token and m.id in velocity_map:
            token_velocity[token] = velocity_map[m.id]

    iter_dict = {
        "name": iteration.name,
        "goal": iteration.goal,
        "startDate": iteration.start_date.isoformat() if iteration.start_date else "unknown",
        "endDate": iteration.end_date.isoformat() if iteration.end_date else "unknown",
    }

    prompt = build_sprint_prompt(
        backlog_items=scrubbed_backlog + scrubbed_carry,
        team_members=scrubbed_team,
        iteration=iter_dict,
        velocity_map=token_velocity,
        health_signals=scrubbed_health,
        blocked_item_ids=blocked_item_ids,
        carry_forward_items=scrubbed_carry,
        feedback=feedback,
        constraints=active_constraints if active_constraints else None,
    )

    # -----------------------------------------------------------------------
    # 10. Create SprintPlan record (GENERATING)
    # -----------------------------------------------------------------------
    plan = SprintPlan(
        id=generate_cuid(),
        organization_id=org_id,
        project_id=project_id,
        iteration_id=iteration.id,
        status="GENERATING",
        ai_model_used=AI_MODEL,
        tool=source_tool,
        rejection_feedback=feedback,
    )
    db.add(plan)
    await db.flush()

    # -----------------------------------------------------------------------
    # 11. Call Azure AI Foundry (Grok) via OpenAI-compatible API
    # -----------------------------------------------------------------------
    try:
        import httpx

        logger.info(f"Calling Azure AI Foundry ({AI_MODEL}) for sprint plan generation (plan {plan.id})")

        headers = {
            "Content-Type": "application/json",
            "api-key": settings.azure_ai_api_key,
        }
        payload = {
            "model": AI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 16384,
            "temperature": 0.3,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            resp = await client.post(
                settings.azure_ai_endpoint,
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()

        data = resp.json()
        ai_text = data["choices"][0]["message"]["content"]

        logger.info(f"Azure AI response received: {len(ai_text)} chars")

    except Exception as e:
        logger.error(f"Azure AI API call failed: {e}")
        # Fallback to deterministic
        plan.status = "FAILED"
        plan.risk_summary = f"AI generation failed: {str(e)[:200]}. Falling back to deterministic optimizer."
        await db.commit()

        from .sprint_optimizer import generate_sprint_plan
        return await generate_sprint_plan(db, org_id, project_id, iteration_id, feedback)

    # -----------------------------------------------------------------------
    # 12. Parse and validate JSON response
    # -----------------------------------------------------------------------
    try:
        # Extract JSON from response (handle potential markdown wrapping)
        json_text = ai_text.strip()
        if json_text.startswith("```"):
            # Remove markdown code fences
            json_text = re.sub(r"^```(?:json)?\s*\n?", "", json_text)
            json_text = re.sub(r"\n?```\s*$", "", json_text)

        ai_plan = json.loads(json_text)

        assignments_raw = ai_plan.get("assignments", [])
        unplanned_raw = ai_plan.get("unplanned_items", [])
        overall_rationale = ai_plan.get("overall_rationale", "")
        goal_confidence = ai_plan.get("goal_attainment_confidence", 0.7)
        risk_level = ai_plan.get("risk_level", "MODERATE")
        estimated_sprints = ai_plan.get("estimated_sprints", 1)

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"Failed to parse AI response: {e}")
        plan.status = "FAILED"
        plan.risk_summary = f"AI response parsing failed. Falling back to deterministic optimizer."
        await db.commit()

        from .sprint_optimizer import generate_sprint_plan
        return await generate_sprint_plan(db, org_id, project_id, iteration_id, feedback)

    # -----------------------------------------------------------------------
    # 13. Reconstruct PII & create PlanAssignment records
    # -----------------------------------------------------------------------
    # Build work_item_id lookup
    wi_id_set = {wi.id for wi in work_items}

    total_sp = 0.0
    confidence_scores: list[float] = []
    risk_flags_all: list[str] = []
    assignment_count = 0

    for a in assignments_raw:
        wi_id = a.get("work_item_id", "")
        assignee_token = a.get("assignee_token", "")
        member_id = token_to_member_id.get(assignee_token)

        if not member_id:
            logger.warning(f"Unknown assignee token: {assignee_token}")
            continue

        if wi_id not in wi_id_set:
            logger.warning(f"Unknown work item ID: {wi_id}")
            continue

        sp = float(a.get("story_points", 0))
        conf = float(a.get("confidence_score", 0.7))
        if conf > 1.0:
            conf = conf / 100.0

        # Reconstruct PII in rationale
        rationale = reconstruct_pii(a.get("rationale", ""), reverse_map)
        risk_flags = a.get("risk_flags", [])

        sprint_num = int(a.get("sprint_number", 1))

        pa = PlanAssignment(
            id=generate_cuid(),
            sprint_plan_id=plan.id,
            work_item_id=wi_id,
            team_member_id=member_id,
            story_points=sp,
            confidence_score=round(conf, 3),
            rationale=rationale,
            risk_flags=risk_flags,
            skill_match=None,
            is_human_edited=False,
            sprint_number=sprint_num,
        )
        db.add(pa)

        total_sp += sp
        confidence_scores.append(conf)
        risk_flags_all.extend(risk_flags)
        assignment_count += 1

    # -----------------------------------------------------------------------
    # 14. Compute plan-level metrics
    # -----------------------------------------------------------------------
    avg_confidence = (
        sum(confidence_scores) / len(confidence_scores)
        if confidence_scores
        else 0.0
    )

    plan.confidence_score = round(avg_confidence, 3)
    plan.total_story_points = total_sp
    plan.overall_rationale = reconstruct_pii(overall_rationale, reverse_map)
    plan.goal_attainment_confidence = float(goal_confidence)
    plan.estimated_sprints = int(estimated_sprints) if estimated_sprints else 1
    # Calculate estimated end date based on sprint count and duration
    if iteration.start_date and plan.estimated_sprints:
        from datetime import timedelta
        plan.estimated_end_date = iteration.start_date + timedelta(
            days=sprint_days * plan.estimated_sprints
        )
    plan.risk_summary = _build_risk_summary(
        risk_level, avg_confidence, total_sp, len(unplanned_raw), risk_flags_all,
        plan.estimated_sprints,
    )
    plan.unplanned_items = {
        "items": [
            {
                "workItemId": u.get("work_item_id", ""),
                "reason": reconstruct_pii(u.get("reason", ""), reverse_map),
            }
            for u in unplanned_raw
        ]
    }

    # 15. Attach success probability at generation time
    try:
        from .sprint_forecast import calculate_success_probability
        prob_data = await calculate_success_probability(
            db, org_id, project_id, iteration.id
        )
        plan.success_probability = prob_data.get("successProbability")
        plan.forecast_updated_at = datetime.now(timezone.utc)
    except Exception as e:
        logger.warning(f"Success probability calculation failed: {e}")

    # 16. Set status to PENDING_REVIEW
    plan.status = "PENDING_REVIEW"

    # 17. Increment feed-forward constraints usage counter
    if active_constraints:
        try:
            await increment_constraints_applied(db, org_id, project_id)
        except Exception as e:
            logger.warning(f"Failed to increment constraint counters: {e}")

    await db.commit()

    logger.info(
        "AI sprint plan %s: %d assignments, %.0f SP, confidence %.0f%%, success %s%%",
        plan.id, assignment_count, total_sp, avg_confidence * 100,
        plan.success_probability,
    )

    return {
        "planId": plan.id,
        "iterationId": iteration.id,
        "iterationName": iteration.name,
        "status": plan.status,
        "totalStoryPoints": total_sp,
        "confidenceScore": plan.confidence_score,
        "riskSummary": plan.risk_summary,
        "overallRationale": plan.overall_rationale,
        "goalAttainmentConfidence": plan.goal_attainment_confidence,
        "assignmentCount": assignment_count,
        "unplannedCount": len(unplanned_raw),
        "aiModelUsed": AI_MODEL,
        "estimatedSprints": plan.estimated_sprints,
        "estimatedEndDate": plan.estimated_end_date.isoformat() if plan.estimated_end_date else None,
        "successProbability": plan.success_probability,
    }


def _build_risk_summary(
    risk_level: str,
    avg_confidence: float,
    total_sp: float,
    unplanned_count: int,
    risk_flags: list[str],
    estimated_sprints: int | None = None,
) -> str:
    """Build a plan-level risk summary."""
    parts = [f"{risk_level} risk."]

    if avg_confidence >= 0.8:
        parts.append("High confidence in assignments.")
    elif avg_confidence >= 0.6:
        parts.append("Moderate confidence — some assignments may need review.")
    else:
        parts.append("Low confidence — review assignments carefully.")

    parts.append(f"Total: {total_sp:.0f} story points planned.")

    if estimated_sprints and estimated_sprints > 1:
        parts.append(f"Spanning {estimated_sprints} sprints to complete all work.")

    unique_flags = set(risk_flags)
    if "burnout_risk" in unique_flags:
        parts.append("Burnout risk detected for some members.")
    if "skill_gap" in unique_flags:
        count = risk_flags.count("skill_gap")
        parts.append(f"{count} assignment(s) have skill gaps.")
    if "overloaded" in unique_flags:
        parts.append("Some members may be overloaded.")

    if unplanned_count > 0:
        parts.append(f"{unplanned_count} item(s) excluded (blocked).")

    return " ".join(parts)

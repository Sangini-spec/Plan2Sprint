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

    # Format backlog items — group by epic/feature for AI context
    # Build epic lookup: epic_id → epic title
    epics = {item["id"]: item["title"] for item in backlog_items if item.get("type") in ("epic", "feature")}
    stories_by_epic: dict[str, list] = {}
    standalone_items: list = []
    for item in backlog_items:
        epic = item.get("epic_id")
        if epic and epic in epics:
            stories_by_epic.setdefault(epic, []).append(item)
        else:
            standalone_items.append(item)

    backlog_text = ""
    # First list epics with their children grouped together
    for epic_id, epic_title in epics.items():
        blocked = " [BLOCKED]" if epic_id in blocked_item_ids else ""
        backlog_text += f"\n  [FEATURE/EPIC] ID: {epic_id} | Title: {epic_title}{blocked}\n"
        children = stories_by_epic.get(epic_id, [])
        for item in children:
            blocked = " [BLOCKED]" if item["id"] in blocked_item_ids else ""
            backlog_text += (
                f"    - ID: {item['id']} | Title: {item['title']} | Type: {item['type']} | "
                f"Priority: {item['priority']} | SP: {item.get('story_points') or 'unestimated'} | "
                f"Status: {item['status']} | Parent: {epic_title}{blocked}\n"
            )
    # Then standalone items
    for item in standalone_items:
        if item.get("type") in ("epic", "feature"):
            continue  # Already listed above
        blocked = " [BLOCKED]" if item["id"] in blocked_item_ids else ""
        backlog_text += (
            f"  - ID: {item['id']} | Title: {item['title']} | Type: {item['type']} | "
            f"Priority: {item['priority']} | SP: {item.get('story_points') or 'unestimated'} | "
            f"Status: {item['status']}{blocked}\n"
        )

    num_features = len(epics)
    num_stories = len(backlog_items) - len(epics)

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
    cold_start_count = 0
    no_skills_count = 0
    for member in team_members:
        vel = velocity_map.get(member["token"], {})
        avg_sp = vel.get("avg_sp", 15)
        is_cold = vel.get("is_cold_start", False)
        cold = " (cold-start estimate)" if is_cold else ""
        if is_cold:
            cold_start_count += 1
        hours_per_week = member.get("capacity", 40)
        skills = ", ".join(member.get("skills", [])) if member.get("skills") else "general"
        if skills == "general":
            no_skills_count += 1

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

    # Detect data gaps for AI compensation
    zero_priority_count = sum(1 for item in backlog_items if item.get("priority", 0) == 0)
    unestimated_count = sum(1 for item in backlog_items if not item.get("story_points"))
    total_items = len(backlog_items)

    data_gaps_section = ""
    if zero_priority_count > 0 or unestimated_count > 0 or no_skills_count > 0 or cold_start_count > 0:
        gap_lines = ["DATA GAPS DETECTED (compensate for these):"]
        if zero_priority_count > 0:
            gap_lines.append(
                f"  - {zero_priority_count}/{total_items} items have priority=0 (unset). "
                f"You MUST assign a suggested_priority (1=Critical, 2=High, 3=Medium, 4=Low, 5=Trivial) "
                f"based on item type, title complexity, and dependencies."
            )
        if unestimated_count > 0:
            gap_lines.append(
                f"  - {unestimated_count}/{total_items} items have no story points. "
                f"Estimate SP from the item type AND title complexity (not just default by type). "
                f"A 'Redesign checkout flow' story is larger than a 'Fix button color' story."
            )
        if no_skills_count > 0:
            gap_lines.append(
                f"  - {no_skills_count}/{len(team_members)} developers have no skill tags. "
                f"Assign work based on capacity and velocity rather than skill matching. "
                f"Distribute work evenly among skill-unknown developers."
            )
        if cold_start_count > 0:
            gap_lines.append(
                f"  - {cold_start_count}/{len(team_members)} developers have cold-start velocity (no history). "
                f"Use conservative estimates: cap their sprint load at 80% of stated capacity."
            )
        gap_lines.append("")
        data_gaps_section = "\n".join(gap_lines) + "\n"

    # Build sprint info
    sprint_name = iteration.get("name", "Current Sprint")
    sprint_goal = iteration.get("goal") or "No specific goal set"
    start_date = iteration.get("startDate", "unknown")
    end_date = iteration.get("endDate", "unknown")

    # PO instructions / regeneration feedback
    feedback_section = ""
    if feedback:
        feedback_section = f"""
PRODUCT OWNER INSTRUCTIONS:
The Product Owner has provided specific instructions for this sprint plan:
  "{feedback}"
You MUST follow these instructions. They take priority over default ordering and distribution rules. Adjust the plan to satisfy the PO's requirements while still assigning all items.
"""

    prompt = f"""You are a sprint planning AI. Create a project plan by assigning ALL backlog items to developers across sprints.

PROJECT STATS:
- {num_features} features/epics, {num_stories} stories/tasks/bugs
- Sprint duration: {sprint_days} days ({start_date} → {end_date} is Sprint 1)
- Team capacity per sprint: ~{total_team_capacity:.0f} SP
- Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

DEVELOPERS:
{team_text}
Only these developers can receive assignments.

CARRY-FORWARD (prioritize in Sprint 1):
{carry_text}

BACKLOG (grouped by feature):
{backlog_text}
{data_gaps_section}{feedback_section}
{_format_constraints(constraints)}SPRINT ASSIGNMENT RULES (CRITICAL — follow exactly):

1. FEATURE-BASED GROUPING: Assign sprints BY FEATURE. All stories under the same feature/epic go into the SAME sprint. One sprint can contain multiple complete features if capacity allows. NEVER split a feature's stories across different sprints.

2. SPRINT ORDERING = FEATURE ORDER: Sprint 1 gets the first feature(s) in the backlog, Sprint 2 gets the next, etc. Follow the feature order as listed above. Foundational features (auth, registration, core models) go first, dependent features next, polish last.

3. PACK SPRINTS FULL: Each sprint should have MULTIPLE items (stories + their parent epic). Fill each sprint to near the team capacity before moving to the next sprint. A sprint with only 1 item is wrong — pack more features in.

4. NO EMPTY SPRINTS: The sprint_number values must be CONSECUTIVE (1, 2, 3...) with NO gaps. If you use sprints 1-6, every sprint 1 through 6 must have items.

5. MINIMIZE SPRINT COUNT: Use the FEWEST sprints possible. With {num_features} features, you likely need around {max(3, num_features // 2)}-{num_features} sprints (grouping 1-3 features per sprint), NOT 20+ sprints.

6. ASSIGN ALL ITEMS: Every non-blocked item (epics AND their stories) must be assigned. Do NOT leave items unplanned.

7. STORY POINTS: Items without SP — estimate from complexity (story=3-5, bug=2-3, task=2, epic=5-8). Keep estimates realistic and low — minimum 2 SP per item.

8. CAPACITY IS FLEXIBLE: You can exceed the stated capacity by up to 30% per sprint. The goal is fewer, denser sprints — not perfectly balanced load.

9. [BLOCKED] items go in unplanned_items.

10. For items with priority=0, include "suggested_priority" (1-5) in the assignment.

PROJECT ANALYSIS:
- estimated_sprints = exact count of sprints that have assignments (no empty ones)
- estimated_weeks_total = estimated_sprints × {sprint_days / 7.0:.1f} weeks per sprint
- capacity_recommendations: is the team understaffed? how many more developers would help?

Respond with ONLY a JSON object (no markdown, no explanation outside JSON) matching this schema:

{{
  "overall_rationale": "string — 4-6 sentence detailed explanation: how features are grouped into sprints, why this grouping makes sense (related features together), what the sprint capacity looks like, any risks or trade-offs, and what the PO should pay attention to. Be specific about which features go into which sprints and why.",
  "goal_attainment_confidence": 0.85,
  "risk_level": "LOW | MODERATE | HIGH",
  "estimated_sprints": 3,
  "estimated_weeks_total": 6,
  "project_completion_summary": "string — 2-3 sentences about the full project timeline, key milestones, and when all work should be done",
  "capacity_recommendations": {{
    "team_utilization_pct": 85,
    "understaffed": false,
    "recommended_additions": 0,
    "bottleneck_skills": ["backend"],
    "summary": "string — 1-2 sentence capacity analysis"
  }},
  "assignments": [
    {{
      "work_item_id": "string — the item ID from the backlog",
      "assignee_token": "string — e.g. DEV_001",
      "story_points": 5,
      "sprint_number": 1,
      "confidence_score": 0.85,
      "rationale": "string — why this person for this item",
      "risk_flags": ["skill_gap", "overloaded"],
      "suggested_priority": null
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
    #    Filter by project to avoid mixing members from other projects
    # -----------------------------------------------------------------------
    tm_filters = [TeamMember.organization_id == org_id]
    if project_id:
        tm_filters.append(TeamMember.imported_project_id == project_id)
    tm_result = await db.execute(
        select(TeamMember).where(*tm_filters)
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
            "epic_id": wi.epic_id,
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

        # New project-level fields
        estimated_weeks_total = ai_plan.get("estimated_weeks_total")
        project_completion_summary = ai_plan.get("project_completion_summary", "")
        capacity_recommendations = ai_plan.get("capacity_recommendations")

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
        suggested_pri = a.get("suggested_priority")
        if suggested_pri is not None:
            try:
                suggested_pri = int(suggested_pri)
            except (ValueError, TypeError):
                suggested_pri = None

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
            suggested_priority=suggested_pri,
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
    # Count sprints from ACTUAL assignments — only sprints that have items count
    from datetime import timedelta
    from math import ceil
    used_sprints = set(a.get("sprint_number", 1) for a in assignments_raw)
    actual_sprint_count = len(used_sprints) if used_sprints else 1
    # Use actual count of non-empty sprints (not AI's estimated_sprints which may include empties)
    plan.estimated_sprints = actual_sprint_count

    # Calculate weeks from real sprint count × sprint duration
    sprint_weeks = sprint_days / 7.0
    plan.estimated_weeks_total = ceil(plan.estimated_sprints * sprint_weeks)

    # Calculate estimated_end_date from today (not iteration start which may be past)
    now = datetime.now(timezone.utc)
    planning_start = max(now, iteration.start_date) if iteration.start_date else now
    if plan.estimated_sprints:
        plan.estimated_end_date = planning_start + timedelta(
            days=sprint_days * plan.estimated_sprints
        )

    # New project-level fields
    if project_completion_summary:
        plan.project_completion_summary = reconstruct_pii(
            str(project_completion_summary), reverse_map
        )
    if capacity_recommendations and isinstance(capacity_recommendations, dict):
        # Reconstruct PII in the summary text
        if "summary" in capacity_recommendations:
            capacity_recommendations["summary"] = reconstruct_pii(
                str(capacity_recommendations["summary"]), reverse_map
            )
        plan.capacity_recommendations = capacity_recommendations
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
        "estimatedWeeksTotal": plan.estimated_weeks_total,
        "projectCompletionSummary": plan.project_completion_summary,
        "capacityRecommendations": plan.capacity_recommendations,
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

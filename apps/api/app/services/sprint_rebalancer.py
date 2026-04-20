"""
Sprint Rebalancer Service — AI-powered sprint rescue plans.

Two modes:
  1. PROTECT_TIMELINE — end date fixed, AI cuts/defers scope
  2. PROTECT_SCOPE    — all stories kept, AI extends timeline (optional custom date)

Pipeline:
  1. Load current plan + assignments + work items
  2. Load forecast signals (spillover, blockers, capacity)
  3. PII-scrub names
  4. Build mode-specific prompt
  5. Call Grok AI → parse complete sprint allocation + changes
  6. Calculate downstream impact
  7. Store RebalanceProposal
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..models.base import generate_cuid
from ..models.sprint_plan import SprintPlan, PlanAssignment, RebalanceProposal
from ..models.work_item import WorkItem
from ..models.team_member import TeamMember
from ..models.iteration import Iteration
from .ai_sprint_generator import build_token_map, scrub_pii, reconstruct_pii, AI_MODEL

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------

def build_rebalance_prompt(
    current_sprints: list[dict],
    signals: dict,
    mode: str,
    end_date: str,
    target_date: str | None,
    capacity_per_sprint: int,
    po_guidance: str | None,
) -> str:
    """Build the rebalancing prompt for the AI model."""

    sprints_json = json.dumps(current_sprints, separators=(",", ":"))
    signals_json = json.dumps(signals, separators=(",", ":"))

    mode_constraint = ""
    if mode == "PROTECT_TIMELINE":
        mode_constraint = f"""
TIMELINE CONSTRAINT: The end date {end_date} is FIXED. You CANNOT add sprints
or extend the timeline. If items don't fit within existing sprints, DEFER them
to later sprints within the plan or DESCOPE them (action="DESCOPE") to the
post-launch backlog. Prioritize shipping the sprint goal over completeness.
"""
    elif mode == "PROTECT_SCOPE":
        if target_date:
            mode_constraint = f"""
DEADLINE CONSTRAINT: All stories must be delivered by {target_date}.
Calculate how many 2-week sprints fit between now and {target_date}. Distribute
work across those sprints with even load (max {capacity_per_sprint} SP per sprint).
If it's impossible to fit everything, flag which items are at risk.
You SHOULD add new sprints beyond what currently exists if any sprint exceeds 80% capacity.
"""
        else:
            mode_constraint = f"""
SCOPE CONSTRAINT: ALL stories must be delivered. The timeline is FLEXIBLE.
You SHOULD extend the timeline by adding new sprints if ANY sprint exceeds 80% capacity
({int(capacity_per_sprint * 0.8)} SP). Do NOT overload sprints — spread work evenly.
Each sprint should ideally be 60-80% capacity for a sustainable pace.
Add Sprint 5, Sprint 6, etc. as needed. Calculate the new projected end date
based on 2-week sprint cycles from the last existing sprint's end date.
The goal is a balanced, realistic plan — not cramming everything into existing sprints.
"""

    guidance_section = ""
    if po_guidance:
        guidance_section = f"""
PO GUIDANCE (must be respected):
{po_guidance}
"""

    prompt = f"""You are a sprint rescue advisor for an agile team. The current sprint plan
is at risk of failure. Your job is to propose a REBALANCED sprint plan that saves the project.

CRITICAL RULES:
1. You manage SCOPE, not people. Do NOT reassign work to different developers — developers self-assign in agile.
2. Your tools:
   - KEEP: Story stays exactly where it is (no change)
   - DEFER: Move story to a later sprint number
   - REPRIORITIZE: Change which sprint a story belongs to for better balance
   - ADJUST_SP: Update story point estimate when actuals clearly diverge
   - SPLIT: Recommend splitting a large story into an MVP portion (this sprint) and follow-up (later sprint)
   - DESCOPE: Move story to post-launch backlog (only in PROTECT_TIMELINE mode)
3. Output the COMPLETE sprint allocation — EVERY story with its sprint number and the action taken.
4. For EACH change (non-KEEP action), explain WHY it helps and what capacity it frees.
5. Preserve feature grouping — stories of the same feature should stay in the same sprint when possible.
6. Minimize total changes — keep as much stable as possible. A good rebalancing plan changes the LEAST while improving the MOST.
7. Never leave a sprint completely empty.
{mode_constraint}
{guidance_section}
== CURRENT SPRINT PLAN ==
{sprints_json}

== REAL-TIME SIGNALS ==
{signals_json}

== REQUIRED JSON OUTPUT ==
Return a single JSON object (no markdown, no extra text) with this exact schema:
{{
  "summary": "2-3 sentence rescue strategy overview",
  "projectedSuccessProbability": <integer 0-100>,
  "projectedEndDate": "<YYYY-MM-DD>",
  "rationale": "Detailed explanation of the rescue strategy and trade-offs",
  "sprints": [
    {{
      "number": 1,
      "totalSP": <int>,
      "stories": [
        {{
          "id": "<work_item_id>",
          "title": "<story title>",
          "sp": <int>,
          "action": "KEEP | DEFER | REPRIORITIZE | ADJUST_SP | SPLIT | DESCOPE",
          "reason": "<why this action, only for non-KEEP items>"
        }}
      ]
    }}
  ],
  "downstreamImpact": {{
    "<sprintN>": {{ "spChange": "<+/-N>", "newTotal": <int>, "capacityPct": <int>, "warning": "<text or null>" }}
  }},
  "changesSummary": [
    {{
      "id": "<work_item_id>",
      "title": "<story title>",
      "action": "<action>",
      "fromSprint": <int>,
      "toSprint": <int or null>,
      "spFreed": <int>,
      "reason": "<brief reason>"
    }}
  ]
}}
"""
    return prompt


# ---------------------------------------------------------------------------
# Deterministic Fallback
# ---------------------------------------------------------------------------

def fallback_rebalance(
    current_sprints: list[dict],
    signals: dict,
    mode: str,
    capacity_per_sprint: int,
) -> dict:
    """Simple heuristic: defer lowest-priority spillover items until sprint 1 is within capacity."""
    sprints = [dict(s) for s in current_sprints]  # shallow copy
    if not sprints:
        return {"summary": "No sprints to rebalance", "sprints": [], "changesSummary": []}

    sprint1 = sprints[0]
    stories = list(sprint1.get("stories", []))
    capacity = capacity_per_sprint
    changes = []

    # Sort by priority descending (highest number = lowest priority = defer first)
    stories_with_priority = [(s, s.get("priority", 3)) for s in stories]
    stories_with_priority.sort(key=lambda x: -x[1])

    total_sp = sum(s.get("sp", 0) for s in stories)
    deferred = []

    for story, _priority in stories_with_priority:
        if total_sp <= capacity:
            break
        sp = story.get("sp", 0)
        total_sp -= sp
        deferred.append(story)
        changes.append({
            "id": story["id"],
            "title": story.get("title", ""),
            "action": "DEFER" if mode != "PROTECT_SCOPE" else "DEFER",
            "fromSprint": 1,
            "toSprint": 2,
            "spFreed": sp,
            "reason": f"Lowest priority item deferred to free {sp} SP (automated fallback)",
        })

    # Rebuild sprints
    remaining = [s for s in stories if s not in deferred]
    sprint1_new = {**sprint1, "stories": [dict(s, action="KEEP") for s in remaining], "totalSP": sum(s.get("sp", 0) for s in remaining)}

    sprint2_stories = []
    if len(sprints) > 1:
        sprint2_stories = list(sprints[1].get("stories", []))
    for s in deferred:
        sprint2_stories.append({**s, "action": "DEFERRED"})

    sprint2_new = {
        "number": 2,
        "totalSP": sum(s.get("sp", 0) for s in sprint2_stories),
        "stories": sprint2_stories,
    }

    result_sprints = [sprint1_new, sprint2_new] + sprints[2:]

    return {
        "summary": f"Deferred {len(deferred)} items ({sum(s.get('sp', 0) for s in deferred)} SP) from Sprint 1 to Sprint 2. (Automated fallback — AI unavailable)",
        "projectedSuccessProbability": 65,
        "projectedEndDate": sprints[-1].get("endDate", ""),
        "rationale": "Automated rebalancing: deferred lowest-priority items to bring Sprint 1 within capacity.",
        "sprints": result_sprints,
        "downstreamImpact": {},
        "changesSummary": changes,
    }


# ---------------------------------------------------------------------------
# Core: Generate Rebalance Proposal
# ---------------------------------------------------------------------------

async def generate_rebalance_proposal(
    db: AsyncSession,
    org_id: str,
    plan_id: str,
    mode: str = "PROTECT_TIMELINE",
    target_date: str | None = None,
    po_guidance: str | None = None,
) -> dict[str, Any]:
    """Generate an AI-powered rebalancing proposal for an at-risk sprint plan."""

    # -----------------------------------------------------------------------
    # 1. Load current plan + assignments
    # -----------------------------------------------------------------------
    plan_result = await db.execute(
        select(SprintPlan)
        .options(selectinload(SprintPlan.assignments).selectinload(PlanAssignment.work_item))
        .options(selectinload(SprintPlan.assignments).selectinload(PlanAssignment.team_member))
        .where(SprintPlan.id == plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        return {"ok": False, "error": "Sprint plan not found"}

    # -----------------------------------------------------------------------
    # 2. Build sprint allocation from current assignments
    # -----------------------------------------------------------------------
    sprints_map: dict[int, list[dict]] = {}
    for a in plan.assignments:
        sn = a.sprint_number or 1
        if sn not in sprints_map:
            sprints_map[sn] = []
        sprints_map[sn].append({
            "id": a.work_item_id,
            "title": a.work_item.title if a.work_item else "Unknown",
            "sp": int(a.story_points or 0),
            "status": a.work_item.status if a.work_item else "UNKNOWN",
            "priority": a.work_item.priority if a.work_item else 3,
            "feature": a.work_item.feature_name if a.work_item and hasattr(a.work_item, 'feature_name') else "",
            "assignee": a.team_member.display_name if a.team_member else "Unassigned",
        })

    # Load iteration for sprint dates
    iteration = None
    if plan.iteration_id:
        iter_result = await db.execute(
            select(Iteration).where(Iteration.id == plan.iteration_id)
        )
        iteration = iter_result.scalar_one_or_none()

    sprint_duration_days = 14
    if iteration and iteration.start_date and iteration.end_date:
        delta = (iteration.end_date - iteration.start_date).days
        if delta > 0:
            sprint_duration_days = delta

    current_sprints = []
    for sn in sorted(sprints_map.keys()):
        stories = sprints_map[sn]
        start = iteration.start_date + timedelta(days=(sn - 1) * sprint_duration_days) if iteration and iteration.start_date else None
        end = start + timedelta(days=sprint_duration_days) if start else None
        current_sprints.append({
            "number": sn,
            "startDate": start.strftime("%Y-%m-%d") if start else "",
            "endDate": end.strftime("%Y-%m-%d") if end else "",
            "totalSP": sum(s["sp"] for s in stories),
            "stories": stories,
        })

    # Estimate capacity from team
    members_result = await db.execute(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
            TeamMember.role.in_(["DEVELOPER", "developer"]),
        )
    )
    members = members_result.scalars().all()
    capacity_per_sprint = max(sum(m.default_capacity or 10 for m in members), 20)

    end_date_str = plan.estimated_end_date.strftime("%Y-%m-%d") if plan.estimated_end_date else ""

    # -----------------------------------------------------------------------
    # 3. Load forecast signals + LIVE success probability
    # -----------------------------------------------------------------------
    from .sprint_forecast import calculate_spillover_risk, calculate_success_probability

    # Calculate live success probability (not stale DB value)
    live_success = plan.success_probability or 0
    try:
        live_result = await calculate_success_probability(db, org_id, plan.project_id or "", plan.iteration_id)
        live_success = live_result.get("successProbability", live_success)
        plan.success_probability = live_success
        await db.flush()
    except Exception as e:
        logger.warning(f"Could not calculate live success probability: {e}")

    spillover_data = await calculate_spillover_risk(
        db, org_id, plan.project_id or "", plan.iteration_id
    )
    spillover_items = spillover_data.get("items", [])

    signals = {
        "successProbability": live_success,
        "spilloverItems": [
            {"id": si.get("id", ""), "risk": si.get("risk", "medium"), "reason": si.get("reason", "")}
            for si in spillover_items[:20]  # limit
        ],
        "blockers": [],
        "totalSpilloverSP": spillover_data.get("totalSpilloverSP", 0),
        "teamCapacityPerSprint": capacity_per_sprint,
    }

    # -----------------------------------------------------------------------
    # 4. PII scrub (minimal — just team member names in stories)
    # -----------------------------------------------------------------------
    token_map = build_token_map(members)
    reverse_map = {v: k for k, v in token_map.items() if not k.startswith("c") or len(k) < 20}

    # Scrub assignee names in sprint data
    for sprint in current_sprints:
        for story in sprint.get("stories", []):
            assignee = story.get("assignee", "")
            if assignee in token_map:
                story["assignee"] = token_map[assignee]

    # -----------------------------------------------------------------------
    # 5. Build prompt and call AI
    # -----------------------------------------------------------------------
    prompt = build_rebalance_prompt(
        current_sprints=current_sprints,
        signals=signals,
        mode=mode,
        end_date=end_date_str,
        target_date=target_date,
        capacity_per_sprint=capacity_per_sprint,
        po_guidance=po_guidance,
    )

    # -----------------------------------------------------------------------
    # 6. Create RebalanceProposal record
    # -----------------------------------------------------------------------
    proposal = RebalanceProposal(
        id=generate_cuid(),
        organization_id=org_id,
        sprint_plan_id=plan_id,
        project_id=plan.project_id,
        status="GENERATING",
        mode=mode,
        original_success_probability=live_success,
        original_end_date=plan.estimated_end_date,
        po_guidance=po_guidance,
        ai_model_used=AI_MODEL,
    )
    if target_date:
        try:
            proposal.target_date = datetime.fromisoformat(target_date)
        except ValueError:
            pass
    db.add(proposal)
    await db.flush()

    # -----------------------------------------------------------------------
    # 7. Call Grok AI
    # -----------------------------------------------------------------------
    ai_result = None
    try:
        if not (settings.azure_ai_api_key or settings.azure_ai_key):
            raise ValueError("No Azure AI API key configured")

        import httpx

        logger.info(f"Calling Grok AI for rebalancing (proposal {proposal.id}, mode={mode})")

        headers = {
            "Content-Type": "application/json",
            "api-key": (settings.azure_ai_api_key or settings.azure_ai_key),
        }
        payload = {
            "model": AI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8192,
            "temperature": 0.2,
        }

        logger.info(f"Calling Grok AI (prompt ~{len(prompt)} chars, timeout 300s)")

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            resp = await client.post(
                settings.azure_ai_endpoint,
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()

        data = resp.json()
        ai_text = data["choices"][0]["message"]["content"]

        logger.info(f"Grok AI rebalancing response: {len(ai_text)} chars")

        # Parse JSON
        json_text = ai_text.strip()
        if json_text.startswith("```"):
            json_text = re.sub(r"^```(?:json)?\s*\n?", "", json_text)
            json_text = re.sub(r"\n?```\s*$", "", json_text)

        ai_result = json.loads(json_text)

    except Exception as e:
        logger.warning(f"AI rebalancing failed, using fallback: {e}")
        ai_result = fallback_rebalance(current_sprints, signals, mode, capacity_per_sprint)

    # -----------------------------------------------------------------------
    # 8. Reconstruct PII in AI response
    # -----------------------------------------------------------------------
    if ai_result:
        for sprint in ai_result.get("sprints", []):
            for story in sprint.get("stories", []):
                if "assignee" in story:
                    story["assignee"] = reconstruct_pii(story["assignee"], reverse_map)
        if "rationale" in ai_result:
            ai_result["rationale"] = reconstruct_pii(ai_result["rationale"], reverse_map)
        if "summary" in ai_result:
            ai_result["summary"] = reconstruct_pii(ai_result["summary"], reverse_map)

    # -----------------------------------------------------------------------
    # 9. Update proposal with AI results
    # -----------------------------------------------------------------------
    proposal.status = "PENDING_REVIEW"
    proposal.summary = ai_result.get("summary", "")
    proposal.ai_rationale = ai_result.get("rationale", "")
    proposal.projected_success_probability = ai_result.get("projectedSuccessProbability", 0)
    proposal.sprint_allocations = ai_result.get("sprints", [])
    proposal.changes_summary = ai_result.get("changesSummary", [])
    proposal.downstream_impact = ai_result.get("downstreamImpact", {})

    projected_end = ai_result.get("projectedEndDate", "")
    if projected_end:
        try:
            proposal.projected_end_date = datetime.fromisoformat(projected_end)
        except ValueError:
            proposal.projected_end_date = plan.estimated_end_date

    await db.commit()
    await db.refresh(proposal)

    logger.info(f"Rebalance proposal {proposal.id} generated: "
                f"{len(ai_result.get('changesSummary', []))} changes, "
                f"projected success {ai_result.get('projectedSuccessProbability', 0)}%")

    return {
        "ok": True,
        "proposalId": proposal.id,
        "status": proposal.status,
        "mode": proposal.mode,
        "summary": proposal.summary,
        "rationale": proposal.ai_rationale,
        "originalSuccessProbability": proposal.original_success_probability,
        "projectedSuccessProbability": proposal.projected_success_probability,
        "originalEndDate": proposal.original_end_date.isoformat() if proposal.original_end_date else None,
        "projectedEndDate": proposal.projected_end_date.isoformat() if proposal.projected_end_date else None,
        "sprints": proposal.sprint_allocations,
        "changesSummary": proposal.changes_summary,
        "downstreamImpact": proposal.downstream_impact,
    }


# ---------------------------------------------------------------------------
# Approve Rebalance → Create New SprintPlan
# ---------------------------------------------------------------------------

async def approve_rebalance(
    db: AsyncSession,
    proposal_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Approve a rebalance proposal — creates a new SprintPlan that supersedes the old one."""

    # Load proposal
    result = await db.execute(
        select(RebalanceProposal).where(RebalanceProposal.id == proposal_id)
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        return {"ok": False, "error": "Proposal not found"}

    if proposal.status not in ("PENDING_REVIEW",):
        return {"ok": False, "error": f"Proposal status is {proposal.status}, expected PENDING_REVIEW"}

    # Load old plan
    old_plan_result = await db.execute(
        select(SprintPlan).where(SprintPlan.id == proposal.sprint_plan_id)
    )
    old_plan = old_plan_result.scalar_one_or_none()
    if not old_plan:
        return {"ok": False, "error": "Original plan not found"}

    # -----------------------------------------------------------------------
    # 1. Create NEW SprintPlan from rebalanced allocations
    # -----------------------------------------------------------------------
    new_plan = SprintPlan(
        id=generate_cuid(),
        organization_id=proposal.organization_id,
        project_id=proposal.project_id,
        iteration_id=old_plan.iteration_id,
        status="APPROVED",
        confidence_score=old_plan.confidence_score,
        risk_summary=f"Rebalanced plan: {proposal.summary}",
        overall_rationale=proposal.ai_rationale if isinstance(proposal.ai_rationale, str) else json.dumps(proposal.ai_rationale or {}),
        total_story_points=old_plan.total_story_points,
        estimated_sprints=len(proposal.sprint_allocations or []),
        estimated_end_date=proposal.projected_end_date or old_plan.estimated_end_date,
        success_probability=proposal.projected_success_probability,
        ai_model_used=proposal.ai_model_used,
        tool=old_plan.tool,
        estimated_weeks_total=old_plan.estimated_weeks_total,
        project_completion_summary=f"Rebalanced from plan {old_plan.id}",
        approved_by_id=user_id,
        approved_at=datetime.now(timezone.utc),
        is_rebalanced=True,
        rebalance_source_id=old_plan.id,
    )
    db.add(new_plan)
    await db.flush()

    # -----------------------------------------------------------------------
    # 2. Create PlanAssignment records from rebalanced allocations
    # -----------------------------------------------------------------------
    # Build work_item lookup from old plan's assignments
    old_assignments = await db.execute(
        select(PlanAssignment).where(PlanAssignment.sprint_plan_id == old_plan.id)
    )
    old_assignment_map = {a.work_item_id: a for a in old_assignments.scalars().all()}

    total_sp = 0
    assignment_count = 0

    for sprint_data in (proposal.sprint_allocations or []):
        sprint_num = sprint_data.get("number", 1)
        for story in sprint_data.get("stories", []):
            work_item_id = story.get("id", "")
            if not work_item_id:
                continue

            # Get team_member_id from old assignment or default
            old_a = old_assignment_map.get(work_item_id)
            team_member_id = old_a.team_member_id if old_a else None

            if not team_member_id:
                # Skip items we can't assign
                continue

            sp = story.get("sp", old_a.story_points if old_a else 0)
            action = story.get("action", "KEEP")

            # Skip DESCOPE'd items — they're removed from the plan
            if action == "DESCOPE":
                continue

            new_assignment = PlanAssignment(
                id=generate_cuid(),
                sprint_plan_id=new_plan.id,
                work_item_id=work_item_id,
                team_member_id=team_member_id,
                story_points=sp,
                confidence_score=old_a.confidence_score if old_a else 0.7,
                rationale=story.get("reason", old_a.rationale if old_a else "Rebalanced"),
                risk_flags=old_a.risk_flags if old_a else [],
                skill_match=old_a.skill_match if old_a else None,
                sprint_number=sprint_num,
                is_human_edited=False,
                suggested_priority=old_a.suggested_priority if old_a else None,
            )
            db.add(new_assignment)
            total_sp += sp
            assignment_count += 1

    new_plan.total_story_points = total_sp

    # -----------------------------------------------------------------------
    # 3. Supersede old plan
    # -----------------------------------------------------------------------
    old_plan.status = "SUPERSEDED"

    # -----------------------------------------------------------------------
    # 4. Update proposal
    # -----------------------------------------------------------------------
    proposal.status = "APPROVED"
    proposal.new_plan_id = new_plan.id

    await db.commit()

    logger.info(f"Rebalance approved: proposal {proposal_id} → new plan {new_plan.id} "
                f"({assignment_count} assignments, {total_sp} SP)")

    return {
        "ok": True,
        "newPlanId": new_plan.id,
        "oldPlanId": old_plan.id,
        "assignmentCount": assignment_count,
        "totalStoryPoints": total_sp,
        "projectedSuccessProbability": proposal.projected_success_probability,
    }

"""
Enterprise Team Health Engine -- 6-pillar computation service.

Pillars:
  1. Work Hours        (overtime / sustainable pace)
  2. Burnout Risk Index (composite burnout signal)
  3. Sprint Sustainability (velocity stability, carry-over, scope creep)
  4. Bus Factor         (knowledge-concentration risk)
  5. Flow Health        (WIP, blocked time, context switching)
  6. Team Resilience    (workload equity, cross-training, attrition risk)

Plus AI-powered recommendations via Grok (xAI) with rule-based fallback.
"""

from __future__ import annotations

import logging
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select, func, case, and_, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import TeamMember, WorkItem, Iteration, HealthSignal
from ..models.activity import ActivityEvent

logger = logging.getLogger(__name__)

XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_BASE = "https://api.x.ai/v1"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _severity_from_hours(hours: float) -> str:
    if hours < 45:
        return "GREEN"
    if hours < 50:
        return "AMBER"
    if hours < 60:
        return "RED"
    return "CRITICAL"


def _trend(current: float, previous: float) -> str:
    if current > previous + 1:
        return "up"
    if current < previous - 1:
        return "down"
    return "stable"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _normalize(value: float, low: float, high: float) -> float:
    """Map *value* into 0-100 where low -> 0 and high -> 100."""
    if high <= low:
        return 0.0
    return _clamp((value - low) / (high - low) * 100)


def _gini(values: List[float]) -> float:
    """Compute the Gini coefficient (0 = perfect equality, 1 = max inequality)."""
    if not values or sum(values) == 0:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    cumulative = sum((i + 1) * v for i, v in enumerate(sorted_vals))
    return (2 * cumulative) / (n * sum(sorted_vals)) - (n + 1) / n


async def _get_project_members(
    db: AsyncSession, org_id: str, project_id: Optional[str]
) -> List[TeamMember]:
    q = select(TeamMember).where(TeamMember.organization_id == org_id)
    if project_id:
        q = q.where(TeamMember.imported_project_id == project_id)
    result = await db.execute(q)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# 1. Work Hours
# ---------------------------------------------------------------------------

async def compute_work_hours(
    db: AsyncSession,
    org_id: str,
    project_id: Optional[str] = None,
    weeks: int = 4,
) -> List[Dict[str, Any]]:
    """Estimate weekly work hours per developer from activity events."""
    members = await _get_project_members(db, org_id, project_id)
    if not members:
        return []

    member_ids = [m.id for m in members]
    member_map = {m.id: m for m in members}
    cutoff = datetime.now(timezone.utc) - timedelta(weeks=weeks)

    # Fetch activity events
    ae_q = (
        select(ActivityEvent)
        .where(
            ActivityEvent.organization_id == org_id,
            ActivityEvent.team_member_id.in_(member_ids),
            ActivityEvent.occurred_at >= cutoff,
        )
        .order_by(ActivityEvent.occurred_at)
    )
    ae_result = await db.execute(ae_q)
    events = ae_result.scalars().all()

    # Fetch work-item update timestamps as secondary signal
    wi_q = (
        select(WorkItem.assignee_id, func.date(WorkItem.updated_at).label("day"))
        .where(
            WorkItem.assignee_id.in_(member_ids),
            WorkItem.updated_at >= cutoff,
        )
    )
    wi_result = await db.execute(wi_q)
    wi_rows = wi_result.all()

    # Group activity events by member -> day
    # events_by_member_day[member_id][date] = [timestamps]
    events_by_member_day: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for ev in events:
        day_key = ev.occurred_at.strftime("%Y-%m-%d")
        events_by_member_day[ev.team_member_id][day_key].append(ev.occurred_at)

    # Also merge work-item timestamps (as a lighter signal)
    wi_days_by_member: Dict[str, set] = defaultdict(set)
    for row in wi_rows:
        if row[0]:
            wi_days_by_member[row[0]].add(str(row[1]))

    now = datetime.now(timezone.utc)
    results = []

    for mid, member in member_map.items():
        weekly_hours: List[float] = []

        for w in range(weeks):
            week_start = now - timedelta(weeks=w + 1)
            week_end = now - timedelta(weeks=w)
            total_day_hours = 0.0
            days_counted = 0

            for d in range(7):
                day = week_start + timedelta(days=d)
                day_key = day.strftime("%Y-%m-%d")
                timestamps = events_by_member_day.get(mid, {}).get(day_key, [])

                if len(timestamps) >= 2:
                    first = min(timestamps)
                    last = max(timestamps)
                    active_h = (last - first).total_seconds() / 3600
                    active_h = min(active_h, 16.0)  # cap at 16h
                    total_day_hours += active_h
                    days_counted += 1
                elif len(timestamps) == 1:
                    total_day_hours += 4.0  # single event -> assume half-day
                    days_counted += 1

            # Fallback: estimate from work-item activity if no events
            if days_counted == 0:
                wi_days_in_week = 0
                for d in range(7):
                    day = week_start + timedelta(days=d)
                    day_key = day.strftime("%Y-%m-%d")
                    if day_key in wi_days_by_member.get(mid, set()):
                        wi_days_in_week += 1
                total_day_hours = wi_days_in_week * 6.0  # 6h per active day

            weekly_hours.append(round(total_day_hours, 1))

        # weekly_hours[0] = most recent complete week, [1] = week before, etc.
        this_week = weekly_hours[0] if weekly_hours else 0
        last_week = weekly_hours[1] if len(weekly_hours) > 1 else 0

        results.append({
            "id": mid,
            "name": member.display_name,
            "thisWeek": this_week,
            "lastWeek": last_week,
            "trend": _trend(this_week, last_week),
            "severity": _severity_from_hours(this_week),
            "weeklyHistory": list(reversed(weekly_hours)),  # oldest first
        })

    return results


# ---------------------------------------------------------------------------
# 2. Burnout Risk Index
# ---------------------------------------------------------------------------

async def compute_burnout_risk_index(
    db: AsyncSession,
    org_id: str,
    project_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Composite burnout risk per developer (0-100, higher = worse)."""
    members = await _get_project_members(db, org_id, project_id)
    if not members:
        return []

    member_ids = [m.id for m in members]
    member_map = {m.id: m for m in members}
    cutoff = datetime.now(timezone.utc) - timedelta(weeks=4)

    # Pre-fetch work hours
    work_hours_data = await compute_work_hours(db, org_id, project_id, weeks=4)
    hours_by_id = {d["id"]: d["thisWeek"] for d in work_hours_data}

    # Activity totals per member
    totals_q = (
        select(
            ActivityEvent.team_member_id,
            func.count(ActivityEvent.id).label("total"),
            func.count(case((ActivityEvent.is_after_hours == True, 1))).label("after_hours"),
            func.count(case((ActivityEvent.is_weekend == True, 1))).label("weekend"),
        )
        .where(
            ActivityEvent.organization_id == org_id,
            ActivityEvent.team_member_id.in_(member_ids),
            ActivityEvent.occurred_at >= cutoff,
        )
        .group_by(ActivityEvent.team_member_id)
    )
    totals_result = await db.execute(totals_q)
    activity_stats = {
        row[0]: {"total": row[1], "after_hours": row[2], "weekend": row[3]}
        for row in totals_result.all()
    }

    # WIP count per member
    wip_q = (
        select(WorkItem.assignee_id, func.count(WorkItem.id))
        .where(
            WorkItem.assignee_id.in_(member_ids),
            WorkItem.status == "IN_PROGRESS",
        )
        .group_by(WorkItem.assignee_id)
    )
    wip_result = await db.execute(wip_q)
    wip_by_id = dict(wip_result.all())

    # Context switches: distinct work items with updates per day
    cs_q = (
        select(
            WorkItem.assignee_id,
            func.date(WorkItem.updated_at).label("day"),
            func.count(distinct(WorkItem.id)).label("items"),
        )
        .where(
            WorkItem.assignee_id.in_(member_ids),
            WorkItem.updated_at >= cutoff,
        )
        .group_by(WorkItem.assignee_id, func.date(WorkItem.updated_at))
    )
    cs_result = await db.execute(cs_q)
    cs_rows = cs_result.all()
    cs_by_member: Dict[str, List[int]] = defaultdict(list)
    for row in cs_rows:
        cs_by_member[row[0]].append(row[2])

    # Carry-over: items assigned to a past iteration that appear in the next one
    # Simplified: count items where iteration end_date < now and status != DONE/CLOSED
    carry_q = (
        select(WorkItem.assignee_id, func.count(WorkItem.id))
        .join(Iteration, WorkItem.iteration_id == Iteration.id)
        .where(
            WorkItem.assignee_id.in_(member_ids),
            Iteration.end_date < datetime.now(timezone.utc),
            ~WorkItem.status.in_(["DONE", "CLOSED", "REMOVED"]),
        )
        .group_by(WorkItem.assignee_id)
    )
    carry_result = await db.execute(carry_q)
    carry_by_id = dict(carry_result.all())

    results = []
    for mid, member in member_map.items():
        hours = hours_by_id.get(mid, 0)
        work_hours_score = _normalize(hours, 45, 60)

        stats = activity_stats.get(mid, {"total": 0, "after_hours": 0, "weekend": 0})
        total_events = max(stats["total"], 1)
        after_hours_ratio = (stats["after_hours"] / total_events) * 100
        weekend_ratio = (stats["weekend"] / total_events) * 100

        wip = wip_by_id.get(mid, 0)
        wip_score = _normalize(wip, 3, 7)

        cs_list = cs_by_member.get(mid, [])
        avg_cs = statistics.mean(cs_list) if cs_list else 0
        context_switch_score = _normalize(avg_cs, 3, 8)

        carry = carry_by_id.get(mid, 0)
        carry_over_score = _normalize(carry, 1, 5)

        composite = (
            work_hours_score * 0.30
            + after_hours_ratio * 0.20
            + weekend_ratio * 0.15
            + wip_score * 0.15
            + context_switch_score * 0.10
            + carry_over_score * 0.10
        )
        composite = _clamp(composite)

        severity = "GREEN" if composite < 30 else ("AMBER" if composite < 60 else "RED")

        results.append({
            "id": mid,
            "name": member.display_name,
            "score": round(composite, 1),
            "severity": severity,
            "breakdown": {
                "workHours": round(work_hours_score, 1),
                "afterHoursRatio": round(after_hours_ratio, 1),
                "weekendRatio": round(weekend_ratio, 1),
                "wipScore": round(wip_score, 1),
                "contextSwitchScore": round(context_switch_score, 1),
                "carryOverScore": round(carry_over_score, 1),
            },
        })

    return results


# ---------------------------------------------------------------------------
# 3. Sprint Sustainability
# ---------------------------------------------------------------------------

async def compute_sprint_sustainability(
    db: AsyncSession,
    org_id: str,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Velocity stability, carry-over trend, and scope creep across recent sprints."""
    iter_q = (
        select(Iteration)
        .where(
            Iteration.organization_id == org_id,
            Iteration.state.in_(["completed", "closed", "past"]),
        )
        .order_by(Iteration.end_date.desc())
        .limit(6)
    )
    if project_id:
        iter_q = iter_q.where(Iteration.imported_project_id == project_id)

    iter_result = await db.execute(iter_q)
    iterations = list(iter_result.scalars().all())

    if not iterations:
        return {
            "score": 0,
            "severity": "GREY",
            "velocityTrend": [],
            "carryOverTrend": 0,
            "scopeCreepPct": 0,
        }

    velocity_data = []
    carry_over_pcts = []

    for it in reversed(iterations):  # oldest first
        # Total SP planned for this sprint
        planned_q = (
            select(func.coalesce(func.sum(WorkItem.story_points), 0))
            .where(WorkItem.iteration_id == it.id)
        )
        planned_result = await db.execute(planned_q)
        total_sp = float(planned_result.scalar() or 0)

        # Completed SP
        completed_q = (
            select(func.coalesce(func.sum(WorkItem.story_points), 0))
            .where(
                WorkItem.iteration_id == it.id,
                WorkItem.status.in_(["DONE", "CLOSED"]),
            )
        )
        completed_result = await db.execute(completed_q)
        completed_sp = float(completed_result.scalar() or 0)

        # Carry-over: items not done by sprint end
        carry_over_sp = max(total_sp - completed_sp, 0)
        carry_over_pct = (carry_over_sp / total_sp * 100) if total_sp > 0 else 0
        carry_over_pcts.append(carry_over_pct)

        # Scope creep: items created after sprint start
        creep_q = (
            select(func.count(WorkItem.id))
            .where(
                WorkItem.iteration_id == it.id,
                WorkItem.created_at > it.start_date,
            )
        )
        creep_result = await db.execute(creep_q)
        creep_count = creep_result.scalar() or 0

        total_items_q = (
            select(func.count(WorkItem.id)).where(WorkItem.iteration_id == it.id)
        )
        total_items_result = await db.execute(total_items_q)
        total_items = total_items_result.scalar() or 1

        velocity_data.append({
            "name": it.name,
            "planned": round(total_sp, 1),
            "completed": round(completed_sp, 1),
            "carryOver": round(carry_over_sp, 1),
            "scopeCreepPct": round(creep_count / total_items * 100, 1),
        })

    # Velocity stability (higher = more stable)
    completed_list = [v["completed"] for v in velocity_data]
    if len(completed_list) >= 2 and statistics.mean(completed_list) > 0:
        cv = statistics.stdev(completed_list) / statistics.mean(completed_list)
        velocity_stability = _clamp(100 - cv * 100)
    else:
        velocity_stability = 50.0

    # Carry-over trend: simple linear slope
    if len(carry_over_pcts) >= 2:
        n = len(carry_over_pcts)
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(carry_over_pcts)
        num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(carry_over_pcts))
        den = sum((i - x_mean) ** 2 for i in range(n))
        carry_over_slope = num / den if den else 0
    else:
        carry_over_slope = 0

    # Scope creep average
    scope_creep_avg = statistics.mean([v["scopeCreepPct"] for v in velocity_data]) if velocity_data else 0

    # Overall score: weighted (higher = healthier)
    carry_over_health = _clamp(100 - statistics.mean(carry_over_pcts)) if carry_over_pcts else 50
    scope_health = _clamp(100 - scope_creep_avg)
    overall = velocity_stability * 0.4 + carry_over_health * 0.35 + scope_health * 0.25
    overall = _clamp(overall)

    severity = "GREEN" if overall >= 70 else ("AMBER" if overall >= 40 else "RED")

    return {
        "score": round(overall, 1),
        "severity": severity,
        "velocityTrend": velocity_data,
        "carryOverTrend": round(carry_over_slope, 2),
        "scopeCreepPct": round(scope_creep_avg, 1),
    }


# ---------------------------------------------------------------------------
# 4. Bus Factor
# ---------------------------------------------------------------------------

async def compute_bus_factor(
    db: AsyncSession,
    org_id: str,
    project_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Knowledge-concentration risk per feature / epic."""
    # Get epics / features
    epic_q = (
        select(WorkItem)
        .where(
            WorkItem.organization_id == org_id,
            WorkItem.type.in_(["Epic", "Feature", "epic", "feature"]),
        )
    )
    if project_id:
        epic_q = epic_q.where(WorkItem.imported_project_id == project_id)
    epic_result = await db.execute(epic_q)
    epics = list(epic_result.scalars().all())

    # Also get distinct epic_ids referenced by child items
    child_epic_q = (
        select(WorkItem.epic_id)
        .where(
            WorkItem.organization_id == org_id,
            WorkItem.epic_id.isnot(None),
        )
        .distinct()
    )
    if project_id:
        child_epic_q = child_epic_q.where(WorkItem.imported_project_id == project_id)
    child_epic_result = await db.execute(child_epic_q)
    referenced_epic_ids = {row[0] for row in child_epic_result.all()}

    # Build feature list from both sources
    feature_ids = {e.id for e in epics}
    feature_names = {e.id: e.title for e in epics}
    # Add referenced epic_ids that may be external IDs
    all_feature_keys = feature_ids | referenced_epic_ids

    results = []
    matrix_data: List[Dict] = []

    for fk in all_feature_keys:
        # Query children by epic_id or iteration grouping
        children_q = (
            select(WorkItem.assignee_id, func.count(WorkItem.id))
            .where(
                WorkItem.organization_id == org_id,
                WorkItem.epic_id == fk,
                WorkItem.assignee_id.isnot(None),
            )
            .group_by(WorkItem.assignee_id)
        )
        children_result = await db.execute(children_q)
        contributors_raw = children_result.all()

        if not contributors_raw:
            continue

        # Resolve contributor names
        contributor_ids = [row[0] for row in contributors_raw]
        name_q = select(TeamMember.id, TeamMember.display_name).where(
            TeamMember.id.in_(contributor_ids)
        )
        name_result = await db.execute(name_q)
        name_map = dict(name_result.all())

        bus_factor = len(contributors_raw)
        severity = "CRITICAL" if bus_factor <= 1 else ("AMBER" if bus_factor <= 2 else "GREEN")

        contributors = [
            {"id": row[0], "name": name_map.get(row[0], "Unknown"), "itemCount": row[1]}
            for row in contributors_raw
        ]

        feature_name = feature_names.get(fk, fk or "Unlinked")

        results.append({
            "featureId": fk,
            "name": feature_name,
            "busFactor": bus_factor,
            "severity": severity,
            "contributors": contributors,
        })

        # Matrix row
        for c in contributors:
            matrix_data.append({
                "feature": feature_name,
                "developer": c["name"],
                "itemCount": c["itemCount"],
            })

    return results


# ---------------------------------------------------------------------------
# 5. Flow Health
# ---------------------------------------------------------------------------

async def compute_flow_health(
    db: AsyncSession,
    org_id: str,
    project_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """WIP, blocked duration, and context-switching per developer."""
    members = await _get_project_members(db, org_id, project_id)
    if not members:
        return []

    member_ids = [m.id for m in members]
    member_map = {m.id: m for m in members}
    cutoff = datetime.now(timezone.utc) - timedelta(weeks=2)

    # Average WIP (current IN_PROGRESS count as proxy)
    wip_q = (
        select(WorkItem.assignee_id, func.count(WorkItem.id))
        .where(
            WorkItem.assignee_id.in_(member_ids),
            WorkItem.status == "IN_PROGRESS",
        )
        .group_by(WorkItem.assignee_id)
    )
    wip_result = await db.execute(wip_q)
    wip_by_id = dict(wip_result.all())

    # Blocked items duration: count of items in BLOCKED status
    blocked_q = (
        select(WorkItem.assignee_id, func.count(WorkItem.id))
        .where(
            WorkItem.assignee_id.in_(member_ids),
            WorkItem.status.in_(["BLOCKED", "CANCELLED"]),
        )
        .group_by(WorkItem.assignee_id)
    )
    blocked_result = await db.execute(blocked_q)
    blocked_by_id = dict(blocked_result.all())

    # Items per day (distinct items touched)
    ipd_q = (
        select(
            WorkItem.assignee_id,
            func.date(WorkItem.updated_at).label("day"),
            func.count(distinct(WorkItem.id)).label("items"),
        )
        .where(
            WorkItem.assignee_id.in_(member_ids),
            WorkItem.updated_at >= cutoff,
        )
        .group_by(WorkItem.assignee_id, func.date(WorkItem.updated_at))
    )
    ipd_result = await db.execute(ipd_q)
    ipd_rows = ipd_result.all()
    ipd_by_member: Dict[str, List[int]] = defaultdict(list)
    for row in ipd_rows:
        ipd_by_member[row[0]].append(row[2])

    results = []
    for mid, member in member_map.items():
        avg_wip = wip_by_id.get(mid, 0)
        blocked_count = blocked_by_id.get(mid, 0)
        # Estimate blocked hours (rough: 8h per blocked item)
        blocked_hours = blocked_count * 8.0
        items_list = ipd_by_member.get(mid, [])
        items_per_day = statistics.mean(items_list) if items_list else 0

        # Score: lower WIP + lower blocked + moderate throughput = higher flow
        wip_health = _clamp(100 - _normalize(avg_wip, 1, 6) * 1.0)
        blocked_health = _clamp(100 - _normalize(blocked_hours, 0, 40))
        cs_health = _clamp(100 - _normalize(items_per_day, 3, 10) * 0.8)  # some switching is normal

        flow_score = wip_health * 0.40 + blocked_health * 0.35 + cs_health * 0.25
        flow_score = _clamp(flow_score)

        results.append({
            "id": mid,
            "name": member.display_name,
            "flowScore": round(flow_score, 1),
            "avgWip": avg_wip,
            "blockedHours": round(blocked_hours, 1),
            "itemsPerDay": round(items_per_day, 1),
        })

    return results


# ---------------------------------------------------------------------------
# 6. Team Resilience
# ---------------------------------------------------------------------------

async def compute_team_resilience(
    db: AsyncSession,
    org_id: str,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Workload equity, cross-training breadth, and attrition risk."""
    members = await _get_project_members(db, org_id, project_id)
    if not members:
        return {
            "score": 0,
            "severity": "GREY",
            "giniCoefficient": 0,
            "crossTrainingIndex": 0,
            "attritionRiskCount": 0,
            "workloadDistribution": [],
        }

    member_ids = [m.id for m in members]
    member_map = {m.id: m for m in members}

    # SP assigned per developer
    sp_q = (
        select(
            WorkItem.assignee_id,
            func.coalesce(func.sum(WorkItem.story_points), 0),
        )
        .where(
            WorkItem.assignee_id.in_(member_ids),
            ~WorkItem.status.in_(["DONE", "CLOSED", "REMOVED"]),
        )
        .group_by(WorkItem.assignee_id)
    )
    sp_result = await db.execute(sp_q)
    sp_by_id = dict(sp_result.all())

    sp_values = [float(sp_by_id.get(mid, 0)) for mid in member_ids]
    total_sp = sum(sp_values) or 1
    gini = _gini(sp_values)

    # Cross-training: average bus factor across features
    bus_data = await compute_bus_factor(db, org_id, project_id)
    bus_factors = [f["busFactor"] for f in bus_data] if bus_data else [1]
    cross_training_index = statistics.mean(bus_factors) if bus_factors else 1

    # Attrition risk: developers with burnout > 60
    burnout_data = await compute_burnout_risk_index(db, org_id, project_id)
    attrition_count = sum(1 for d in burnout_data if d["score"] > 60)

    # Composite score (higher = more resilient)
    gini_health = _clamp(100 - gini * 100)  # low gini = good
    ct_health = _clamp(_normalize(cross_training_index, 1, 4) * 1.0)  # 4+ contributors is great
    attrition_health = _clamp(100 - (attrition_count / max(len(members), 1)) * 200)

    score = gini_health * 0.35 + ct_health * 0.35 + attrition_health * 0.30
    score = _clamp(score)

    severity = "GREEN" if score >= 70 else ("AMBER" if score >= 40 else "RED")

    workload_dist = []
    for mid in member_ids:
        sp = float(sp_by_id.get(mid, 0))
        workload_dist.append({
            "id": mid,
            "name": member_map[mid].display_name,
            "assignedSp": round(sp, 1),
            "pctOfTotal": round(sp / total_sp * 100, 1),
        })

    return {
        "score": round(score, 1),
        "severity": severity,
        "giniCoefficient": round(gini, 3),
        "crossTrainingIndex": round(cross_training_index, 2),
        "attritionRiskCount": attrition_count,
        "workloadDistribution": workload_dist,
    }


# ---------------------------------------------------------------------------
# AI Recommendations
# ---------------------------------------------------------------------------

async def generate_ai_recommendations(
    health_data: Dict[str, Any],
) -> List[Dict[str, str]]:
    """Call Grok (xAI) for actionable recommendations; fall back to rules."""
    # Build summary prompt
    pillars = health_data.get("pillars", {})
    lines = ["Team Health Summary:"]
    for name, data in pillars.items():
        score = data.get("score", "N/A")
        sev = data.get("severity", "GREY")
        lines.append(f"  - {name}: score={score}, severity={sev}")

    burnout = health_data.get("burnoutRisk", [])
    high_risk = [d for d in burnout if d.get("severity") == "RED"]
    if high_risk:
        lines.append(f"  - {len(high_risk)} developer(s) at HIGH burnout risk")

    work_hours = health_data.get("workHours", {}).get("developers", [])
    overtime = [d for d in work_hours if d.get("severity") in ("RED", "CRITICAL")]
    if overtime:
        lines.append(f"  - {len(overtime)} developer(s) working overtime")

    prompt = "\n".join(lines) + (
        "\n\nBased on this team health data, provide 3-5 specific, actionable recommendations "
        "to improve team health. For each, state the severity (HIGH/MEDIUM/LOW), "
        "the target area, a short message, and a concrete action. "
        "Return ONLY a JSON array of objects with keys: severity, target, message, action."
    )

    if XAI_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{XAI_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {XAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "grok-3-mini",
                        "messages": [
                            {"role": "system", "content": "You are a team health advisor for software engineering teams."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.4,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                # Try to parse JSON from the response
                import json
                # Strip markdown code fences if present
                cleaned = content.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[1]
                    cleaned = cleaned.rsplit("```", 1)[0]
                recs = json.loads(cleaned)
                if isinstance(recs, list):
                    return recs[:5]
        except Exception as e:
            logger.warning("Grok AI recommendation call failed: %s", e)

    # Rule-based fallback
    return _rule_based_recommendations(health_data)


def _rule_based_recommendations(health_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Hardcoded threshold-based recommendations when AI is unavailable."""
    recs = []

    burnout = health_data.get("burnoutRisk", [])
    high_burnout = [d for d in burnout if d.get("severity") == "RED"]
    if high_burnout:
        names = ", ".join(d["name"] for d in high_burnout[:3])
        recs.append({
            "severity": "HIGH",
            "target": "Burnout Risk",
            "message": f"{len(high_burnout)} developer(s) at high burnout risk ({names})",
            "action": "Review workload distribution and consider reassigning tasks or adding capacity.",
        })

    work_hours = health_data.get("workHours", {}).get("developers", [])
    overtime_devs = [d for d in work_hours if d.get("severity") in ("RED", "CRITICAL")]
    if overtime_devs:
        recs.append({
            "severity": "HIGH",
            "target": "Work Hours",
            "message": f"{len(overtime_devs)} team member(s) exceeding sustainable work hours",
            "action": "Enforce work-hour caps and redistribute tasks to prevent sustained overtime.",
        })

    pillars = health_data.get("pillars", {})
    sus = pillars.get("sprintSustainability", {})
    if sus.get("severity") in ("RED", "CRITICAL"):
        recs.append({
            "severity": "HIGH",
            "target": "Sprint Sustainability",
            "message": "Sprint velocity is unstable or carry-over rate is high",
            "action": "Right-size sprint commitments and protect scope once the sprint starts.",
        })

    bus = pillars.get("busFactor", {})
    if bus.get("severity") in ("RED", "CRITICAL"):
        recs.append({
            "severity": "MEDIUM",
            "target": "Bus Factor",
            "message": "Critical knowledge concentration detected in one or more features",
            "action": "Pair-program or rotate developers across features to spread knowledge.",
        })

    resilience = pillars.get("teamResilience", {})
    if resilience.get("severity") in ("RED", "AMBER"):
        recs.append({
            "severity": "MEDIUM",
            "target": "Team Resilience",
            "message": "Workload is unevenly distributed across the team",
            "action": "Rebalance story point assignments and invest in cross-training sessions.",
        })

    if not recs:
        recs.append({
            "severity": "LOW",
            "target": "General",
            "message": "Team health looks good across all pillars",
            "action": "Continue monitoring and maintain current practices.",
        })

    return recs[:5]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def get_full_health_dashboard(
    db: AsyncSession,
    org_id: str,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute all 6 pillars in PARALLEL for speed."""
    import asyncio
    from ..database import AsyncSessionLocal

    async def _run(fn, *args):
        """Run a pillar computation in its own DB session for parallel execution."""
        async with AsyncSessionLocal() as sess:
            return await fn(sess, *args)

    # Run all 6 pillars concurrently — ~13s instead of ~47s sequential
    work_hours, burnout, sustainability, bus_factor, flow, resilience = await asyncio.gather(
        _run(compute_work_hours, org_id, project_id),
        _run(compute_burnout_risk_index, org_id, project_id),
        _run(compute_sprint_sustainability, org_id, project_id),
        _run(compute_bus_factor, org_id, project_id),
        _run(compute_flow_health, org_id, project_id),
        _run(compute_team_resilience, org_id, project_id),
    )

    # Derive pillar-level scores for the summary
    avg_burnout = statistics.mean([d["score"] for d in burnout]) if burnout else 0
    burnout_pillar_score = _clamp(100 - avg_burnout)  # invert: low burnout = high health

    avg_flow = statistics.mean([d["flowScore"] for d in flow]) if flow else 50

    bus_factors = [f["busFactor"] for f in bus_factor] if bus_factor else [1]
    avg_bus = statistics.mean(bus_factors)
    bus_pillar_score = _clamp(_normalize(avg_bus, 1, 4) * 100 / 100)

    avg_hours = statistics.mean([d["thisWeek"] for d in work_hours]) if work_hours else 40
    hours_pillar_score = _clamp(100 - _normalize(avg_hours, 40, 60) * 1.0)

    pillars = {
        "workHours": {
            "score": round(hours_pillar_score, 1),
            "severity": "GREEN" if hours_pillar_score >= 70 else ("AMBER" if hours_pillar_score >= 40 else "RED"),
        },
        "burnoutRisk": {
            "score": round(burnout_pillar_score, 1),
            "severity": "GREEN" if burnout_pillar_score >= 70 else ("AMBER" if burnout_pillar_score >= 40 else "RED"),
            "developers": burnout,
        },
        "sprintSustainability": {
            "score": sustainability["score"],
            "severity": sustainability["severity"],
            "metrics": {
                "velocityTrend": sustainability.get("velocityTrend", []),
                "carryOverTrend": [sustainability.get("carryOverTrend", 0)],
                "scopeCreepPct": sustainability.get("scopeCreepPct", 0),
            },
        },
        "busFactor": {
            "score": round(bus_pillar_score, 1),
            "severity": "GREEN" if bus_pillar_score >= 70 else ("AMBER" if bus_pillar_score >= 40 else "RED"),
            "features": bus_factor,
            "matrix": {},  # Build matrix from bus_factor data
        },
        "flowHealth": {
            "score": round(avg_flow, 1),
            "severity": "GREEN" if avg_flow >= 70 else ("AMBER" if avg_flow >= 40 else "RED"),
            "developers": flow,
        },
        "teamResilience": {
            "score": resilience["score"],
            "severity": resilience["severity"],
            "metrics": {
                "giniCoefficient": resilience.get("giniCoefficient", 0),
                "crossTrainingIndex": resilience.get("crossTrainingIndex", 0),
                "attritionRiskCount": resilience.get("attritionRiskCount", 0),
                "workloadDistribution": resilience.get("workloadDistribution", []),
            },
        },
    }

    # Overall weighted score
    weights = {
        "workHours": 0.15,
        "burnoutRisk": 0.25,
        "sprintSustainability": 0.20,
        "busFactor": 0.10,
        "flowHealth": 0.15,
        "teamResilience": 0.15,
    }
    overall_score = sum(pillars[k]["score"] * weights[k] for k in weights)
    overall_score = round(_clamp(overall_score), 1)
    overall_severity = "GREEN" if overall_score >= 70 else ("AMBER" if overall_score >= 40 else "RED")

    # Build data dict for recommendations
    health_data = {
        "pillars": pillars,
        "burnoutRisk": burnout,
        "workHours": {"developers": work_hours},
    }
    # Use rule-based recommendations by default (fast, no external API call)
    # AI recommendations via Grok can be triggered separately if needed
    recommendations = _rule_based_recommendations(health_data)

    return {
        "overallScore": overall_score,
        "overallSeverity": overall_severity,
        "pillars": pillars,
        "workHours": {"developers": work_hours},
        "recommendations": recommendations,
    }

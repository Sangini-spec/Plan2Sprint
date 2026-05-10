"""Composite confidence score for the PO dashboard KPI.

Replaces ``SprintPlan.confidence_score`` (the AI's frozen self-assessment) as
the number the hero banner displays. This composite reacts to real project
state — velocity, CI/CD throughput, target-launch feasibility, sprint
history — so the KPI actually tells the PO whether the project is healthy.

Factors (total weight = 100):
    1. velocity           30  — work done vs. linear pace expected
    2. cicd               15  — recent commit/PR throughput vs. required pace
    3. ai_plan             15  — the AI plan's own confidence_score (baseline)
    4. target_feasibility 25  — projected finish vs. target_launch_date
    5. sprint_reliability 15  — last 4 completed sprints' hit-rate, recency-weighted

Fallbacks rescale weights when a factor isn't applicable (no approved plan,
no linked repo, no completed sprints yet, no target date).

Per product decision (Apr 2026): burnout and team-health signals are NOT
factored in. Confidence is about *delivery reality*, not wellbeing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import case, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.imported_project import ImportedProject
from ..models.iteration import Iteration
from ..models.repository import Commit, PullRequest, Repository
from ..models.work_item import WorkItem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

# Weights for each factor. Must sum to 100. We rescale these when a factor is
# dropped for a given project (e.g. no repo -> drop cicd and redistribute).
WEIGHT_VELOCITY = 30
WEIGHT_CICD = 15
WEIGHT_AI_PLAN = 15
WEIGHT_TARGET_FEASIBILITY = 25
WEIGHT_SPRINT_RELIABILITY = 15

# Sprint-reliability recency weights. Index 0 = most recent completed sprint.
# Normalised by the engine if we have fewer than 4 sprints.
SPRINT_RECENCY_WEIGHTS = [0.50, 0.25, 0.15, 0.10]

# CI/CD baseline: commits + merged PRs we *expect* per active developer per
# two-week window for a healthy project. Below -> throughput factor scores
# proportionally lower; above -> caps at 100.
CICD_EXPECTED_PER_DEV_FORTNIGHT = 10

# Target-feasibility falloff. 0 days slip = 100. SLIP_FLOOR_DAYS slip = 0.
# Linear in between.
SLIP_FLOOR_DAYS = 42  # six weeks past target = zero confidence in target


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------

@dataclass
class ConfidenceBreakdown:
    velocity: Optional[float] = None
    cicd: Optional[float] = None
    ai_plan: Optional[float] = None
    target_feasibility: Optional[float] = None
    sprint_reliability: Optional[float] = None


@dataclass
class ConfidenceResult:
    score: Optional[int]          # 0-100, or None if project not ready
    breakdown: ConfidenceBreakdown = field(default_factory=ConfidenceBreakdown)
    weights: dict[str, int] = field(default_factory=dict)
    factors_used: list[str] = field(default_factory=list)
    reason_hidden: Optional[str] = None   # set when score is None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def compute_confidence(
    db: AsyncSession,
    org_id: str,
    project_id: str,
) -> ConfidenceResult:
    """Compute a 0-100 composite confidence for one project.

    Returns ``score=None`` when the project doesn't have enough state for any
    meaningful reading yet — typically when no plan has been approved. The
    UI should hide the confidence KPI in that case and show "Plan pending".
    """
    project = await _load_project(db, org_id, project_id)
    if project is None:
        return ConfidenceResult(score=None, reason_hidden="project_not_found")

    plan = await _load_active_plan(db, project_id)
    if plan is None:
        # No approved plan -> confidence isn't meaningful (nothing to track
        # against). Hide the KPI tile on the hero banner.
        return ConfidenceResult(score=None, reason_hidden="no_approved_plan")

    # Compute each factor independently. Each returns either a 0-100 float
    # or None when the factor can't be computed for this project.
    breakdown = ConfidenceBreakdown()
    breakdown.velocity = await _factor_velocity(db, project, plan)
    breakdown.cicd = await _factor_cicd(db, project)
    breakdown.ai_plan = _factor_ai_plan(plan)
    breakdown.target_feasibility = await _factor_target_feasibility(db, project, plan)
    breakdown.sprint_reliability = await _factor_sprint_reliability(db, project)

    # Rescale weights over only the factors we could actually measure.
    raw_weights = {
        "velocity": WEIGHT_VELOCITY,
        "cicd": WEIGHT_CICD,
        "ai_plan": WEIGHT_AI_PLAN,
        "target_feasibility": WEIGHT_TARGET_FEASIBILITY,
        "sprint_reliability": WEIGHT_SPRINT_RELIABILITY,
    }
    usable: dict[str, float] = {}
    for k, v in raw_weights.items():
        val = getattr(breakdown, k)
        if val is not None:
            usable[k] = float(v)
    if not usable:
        # Extremely unlikely but defensive: nothing to compute.
        return ConfidenceResult(
            score=None,
            breakdown=breakdown,
            reason_hidden="no_measurable_factors",
        )
    total_weight = sum(usable.values())
    rescaled = {k: round(v / total_weight * 100) for k, v in usable.items()}

    # Weighted sum
    score = 0.0
    for k, w in rescaled.items():
        score += (getattr(breakdown, k) or 0.0) * (w / 100.0)
    score = max(0, min(100, round(score)))

    return ConfidenceResult(
        score=int(score),
        breakdown=breakdown,
        weights=rescaled,
        factors_used=list(usable.keys()),
    )


# ---------------------------------------------------------------------------
# Factor 1: Completion velocity — work done vs. linear pace expected
# ---------------------------------------------------------------------------

async def _factor_velocity(
    db: AsyncSession,
    project: ImportedProject,
    plan,
) -> Optional[float]:
    """Returns 0..100 or None.

    actual_fraction  = done_sp / total_sp
    expected_fraction = (now - project_start) / (target - project_start)
    score             = min(100, actual_fraction / expected_fraction * 100)
    """
    # Totals
    q = await db.execute(
        select(
            func.coalesce(func.sum(WorkItem.story_points), 0.0),
            func.coalesce(
                func.sum(
                    case(
                        (WorkItem.status.in_(("DONE", "CLOSED", "RESOLVED")), WorkItem.story_points),
                        else_=0.0,
                    )
                ),
                0.0,
            ),
        ).where(
            WorkItem.organization_id == project.organization_id,
            WorkItem.imported_project_id == project.id,
        )
    )
    total_sp, done_sp = q.first() or (0.0, 0.0)
    total_sp = float(total_sp or 0)
    done_sp = float(done_sp or 0)
    if total_sp <= 0:
        return None  # project hasn't sized its work yet

    # Project window: origin (earliest work item planned_start) -> target
    target = project.target_launch_date
    if target is None:
        return None

    origin_q = await db.execute(
        select(func.min(WorkItem.planned_start)).where(
            WorkItem.organization_id == project.organization_id,
            WorkItem.imported_project_id == project.id,
            WorkItem.planned_start.isnot(None),
        )
    )
    origin = origin_q.scalar() or plan.created_at
    if origin is None:
        return None
    now = datetime.now(timezone.utc)
    if target <= origin:
        return None
    elapsed = (now - origin).total_seconds()
    total_window = (target - origin).total_seconds()
    if elapsed <= 0:
        # Project not officially started yet — everything is "on time" by default.
        return 100.0
    expected_fraction = elapsed / total_window
    actual_fraction = done_sp / total_sp
    if expected_fraction <= 0:
        return 100.0
    raw = actual_fraction / expected_fraction * 100.0
    return max(0.0, min(100.0, raw))


# ---------------------------------------------------------------------------
# Factor 2: CI/CD throughput
# ---------------------------------------------------------------------------

async def _factor_cicd(
    db: AsyncSession,
    project: ImportedProject,
) -> Optional[float]:
    """Returns 0..100 or None.

    We can't tie commits to a specific project with certainty (repos are org-
    level), so this factor measures the *org's* recent dev activity against a
    per-developer baseline. For single-project orgs this effectively measures
    that project. For multi-project orgs it measures aggregate throughput —
    good enough for a PO-level health signal.
    """
    since = datetime.now(timezone.utc) - timedelta(days=14)

    repos_q = await db.execute(
        select(func.count(Repository.id)).where(Repository.organization_id == project.organization_id)
    )
    repo_count = repos_q.scalar() or 0
    if repo_count == 0:
        return None  # no GitHub connected -> drop this factor entirely

    commits_q = await db.execute(
        select(func.count(Commit.id))
        .join(Repository, Repository.id == Commit.repository_id)
        .where(
            Repository.organization_id == project.organization_id,
            Commit.committed_at >= since,
        )
    )
    commits = commits_q.scalar() or 0

    prs_q = await db.execute(
        select(func.count(PullRequest.id))
        .join(Repository, Repository.id == PullRequest.repository_id)
        .where(
            Repository.organization_id == project.organization_id,
            PullRequest.merged_at.isnot(None),
            PullRequest.merged_at >= since,
        )
    )
    merged_prs = prs_q.scalar() or 0

    # Active developers — count team members linked to the project
    from ..models.team_member import TeamMember
    devs_q = await db.execute(
        select(func.count(TeamMember.id)).where(
            TeamMember.organization_id == project.organization_id,
        )
    )
    dev_count = max(1, devs_q.scalar() or 1)

    activity = commits + merged_prs
    expected = dev_count * CICD_EXPECTED_PER_DEV_FORTNIGHT
    if expected <= 0:
        return 50.0  # neutral
    raw = activity / expected * 100.0
    return max(0.0, min(100.0, raw))


# ---------------------------------------------------------------------------
# Factor 3: AI plan baseline
# ---------------------------------------------------------------------------

def _factor_ai_plan(plan) -> Optional[float]:
    """The approved plan's own ``confidence_score``, normalised to 0-100.

    SprintPlan.confidence_score can be stored as 0-1 (AI probability) or
    0-100 (percent). Accept either.
    """
    raw = plan.confidence_score
    if raw is None:
        return None
    val = float(raw)
    if val <= 1.0:
        val *= 100.0
    return max(0.0, min(100.0, val))


# ---------------------------------------------------------------------------
# Factor 4: Target-launch feasibility
# ---------------------------------------------------------------------------

async def _factor_target_feasibility(
    db: AsyncSession,
    project: ImportedProject,
    plan,
) -> Optional[float]:
    """Project the finish date at current burn rate, compare to target.

    burn_rate = SP completed in last 14 days / 14  (SP per day)
    remaining_sp = total_sp - done_sp
    projected_days = remaining_sp / burn_rate
    slip = (now + projected_days) - target
    score = 100 if slip <= 0, 0 if slip >= SLIP_FLOOR_DAYS, linear in between.
    """
    target = project.target_launch_date
    if target is None:
        return None

    # Totals
    q = await db.execute(
        select(
            func.coalesce(func.sum(WorkItem.story_points), 0.0),
            func.coalesce(
                func.sum(
                    case(
                        (WorkItem.status.in_(("DONE", "CLOSED", "RESOLVED")), WorkItem.story_points),
                        else_=0.0,
                    )
                ),
                0.0,
            ),
        ).where(
            WorkItem.organization_id == project.organization_id,
            WorkItem.imported_project_id == project.id,
        )
    )
    total_sp, done_sp = q.first() or (0.0, 0.0)
    total_sp = float(total_sp or 0)
    done_sp = float(done_sp or 0)
    if total_sp <= 0:
        return None
    remaining_sp = max(0.0, total_sp - done_sp)
    if remaining_sp <= 0:
        return 100.0  # nothing left -> we finish on day zero

    # Burn rate from last 14 days.
    since = datetime.now(timezone.utc) - timedelta(days=14)
    burn_q = await db.execute(
        select(func.coalesce(func.sum(WorkItem.story_points), 0.0)).where(
            WorkItem.organization_id == project.organization_id,
            WorkItem.imported_project_id == project.id,
            WorkItem.status.in_(("DONE", "CLOSED", "RESOLVED")),
            WorkItem.updated_at >= since,
        )
    )
    sp_last_14 = float(burn_q.scalar() or 0.0)
    burn_per_day = sp_last_14 / 14.0
    if burn_per_day <= 0:
        # Nothing done in the last two weeks -> project is stalled. If any
        # work remains, we can't hit target at this rate -> score 0.
        return 0.0 if remaining_sp > 0 else 100.0

    now = datetime.now(timezone.utc)
    projected_days = remaining_sp / burn_per_day
    projected_finish = now + timedelta(days=projected_days)
    slip_days = (projected_finish - target).total_seconds() / 86400.0
    if slip_days <= 0:
        return 100.0
    if slip_days >= SLIP_FLOOR_DAYS:
        return 0.0
    # Linear falloff
    return max(0.0, 100.0 - (slip_days / SLIP_FLOOR_DAYS * 100.0))


# ---------------------------------------------------------------------------
# Factor 5: Sprint reliability with recency weighting
# ---------------------------------------------------------------------------

async def _factor_sprint_reliability(
    db: AsyncSession,
    project: ImportedProject,
) -> Optional[float]:
    """Last 4 completed sprints' commitment-hit rate, recency-weighted."""
    sprints_q = await db.execute(
        select(Iteration)
        .where(
            Iteration.organization_id == project.organization_id,
            Iteration.imported_project_id == project.id,
            func.lower(Iteration.state).in_(("completed", "closed", "past")),
        )
        .order_by(Iteration.end_date.desc())
        .limit(4)
    )
    sprints = list(sprints_q.scalars().all())
    if not sprints:
        return None

    per_sprint_hit_rates: list[float] = []
    for sprint in sprints:
        items_q = await db.execute(
            select(
                func.coalesce(func.sum(WorkItem.story_points), 0.0),
                func.coalesce(
                    func.sum(
                        case(
                            (WorkItem.status.in_(("DONE", "CLOSED", "RESOLVED")), WorkItem.story_points),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ),
                func.count(WorkItem.id),
                func.sum(
                    case(
                        (WorkItem.status.in_(("DONE", "CLOSED", "RESOLVED")), 1),
                        else_=0,
                    )
                ),
            ).where(WorkItem.iteration_id == sprint.id)
        )
        row = items_q.first()
        committed_sp = float(row[0] or 0.0)
        done_sp = float(row[1] or 0.0)
        committed_count = int(row[2] or 0)
        done_count = int(row[3] or 0)
        if committed_sp > 0:
            hit = done_sp / committed_sp
        elif committed_count > 0:
            hit = done_count / committed_count
        else:
            continue  # nothing was in this sprint
        per_sprint_hit_rates.append(max(0.0, min(1.0, hit)))

    if not per_sprint_hit_rates:
        return None

    # Apply recency weights, rescaling if we have fewer than 4.
    weights = SPRINT_RECENCY_WEIGHTS[: len(per_sprint_hit_rates)]
    weight_total = sum(weights)
    if weight_total <= 0:
        return None
    weighted = sum(hr * w for hr, w in zip(per_sprint_hit_rates, weights))
    return max(0.0, min(100.0, (weighted / weight_total) * 100.0))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _load_project(db: AsyncSession, org_id: str, project_id: str) -> Optional[ImportedProject]:
    q = await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == project_id,
            ImportedProject.organization_id == org_id,
        )
    )
    return q.scalar_one_or_none()


async def _load_active_plan(db: AsyncSession, project_id: str):
    try:
        from ..models.sprint_plan import SprintPlan
    except Exception:
        return None
    q = await db.execute(
        select(SprintPlan)
        .where(
            SprintPlan.project_id == project_id,
            SprintPlan.status.in_(("APPROVED", "SYNCED", "SYNCED_PARTIAL")),
        )
        .order_by(SprintPlan.created_at.desc())
    )
    return q.scalars().first()

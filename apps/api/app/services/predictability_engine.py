"""Delivery Predictability engine.

Single source of truth for the Stakeholder dashboard's Predictability score,
the PO dashboard's Predictability KPI, and the weekly PDF report.

Why this exists
---------------
The previous in-frontend ``computePredictability`` used
``min(1, completed / planned)`` per sprint. That silently clamps every
over-delivery to "perfect", so a team that routinely over-commits reads 100%.
It also didn't penalise variance: 40% → 130% → 60% → 120% averages to 87%
which looks great but reflects a wildly unpredictable team.

This module implements a proper *symmetric* predictability score.

Formula
-------
For the last N (≤ 5) completed sprints, ordered most-recent-first:

    ratio_i    = completed_sp / planned_sp                  # uncapped
    accuracy_i = max(0, 1 - |ratio_i - 1|)                  # symmetric
    hit_i      = 1 if 0.85 <= ratio_i <= 1.15 else 0        # strict goal hit

Three components (each 0-100):

    COMMITMENT_ACCURACY    recency-weighted mean of accuracy_i
    SPRINT_GOAL_HIT_RATE   mean(hit_i) * 100
    STABILITY              max(0, 1 - 2*stdev(accuracy_i)) * 100

Overall:
    0.50 * accuracy + 0.25 * hit_rate + 0.25 * stability

Returns per-sprint rows so the Delivery tab can audit every point.

Product decision (Apr 2026): symmetric penalty — over-delivery is as bad a
signal of planning accuracy as under-delivery. A team that consistently
ships 30% more than planned is not predictable, it's just over-committing.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.iteration import Iteration
from ..models.work_item import WorkItem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables (centralised so they can shift without spelunking)
# ---------------------------------------------------------------------------

# How many completed sprints to consider.
LOOKBACK_SPRINTS = 5

# Recency weights applied to per-sprint accuracies. Index 0 = most recent.
# Rescaled if we have fewer than 5 sprints.
RECENCY_WEIGHTS = [0.35, 0.25, 0.18, 0.12, 0.10]

# Goal-hit window: ratio must land in [1 - tol, 1 + tol] to count as hit.
GOAL_HIT_TOLERANCE = 0.15

# Overall-score weights — must sum to 1.0.
#
# Reweighted Apr 2026 (Hotfix 12): the original 25/25/50 split made
# stability dominate the bottom of the range, gifting 25 free points to
# any team that "consistently" delivered zero. The new 10/25/65 split
# keeps stability as a real signal (a team's process consistency does
# count for SOMETHING) without letting it carry the composite when
# delivery is poor. Net effect:
#   * Accuracy is now the dominant driver (was 50, now 65)
#   * Hit-rate unchanged (25)
#   * Stability dialled down to 10 — a 5-sprint team consistently
#     delivering nothing now scores ~10% rather than 25 or 0, which
#     reads as "low but not zero — the team's behaviour is predictable,
#     just at a low level"
#
# This produces real-math gradation across the spectrum without any
# hardcoded floors or special-case clamps.
W_ACCURACY = 0.65
W_HIT_RATE = 0.25
W_STABILITY = 0.10


# Realism ceiling — a 100% composite reads as a measurement artifact even
# when the math arrives there honestly, because perfect predictability
# across multiple human-driven sprints is functionally impossible. We
# subtract a "perfection penalty" from 100 to get the upper bound of
# what's actually displayable, then ``min`` the raw score against that
# ceiling. Two factors drive the penalty:
#
#   * Sample-size term — confidence interval narrows as 1/sqrt(N), so
#     a 5-sprint history is allowed closer to the ceiling than a
#     1-sprint history.
#   * Variance term — observed accuracy stdev. A team with zero variance
#     looks more predictable, but absolute zero is itself suspicious so
#     we floor the penalty to ensure no display ever reads exactly 100.
#
# Below ``REALISM_FLOOR`` raw scores pass through untouched — the ceiling
# only compresses the top end so a team scoring 60 isn't artificially
# deflated to 58.
REALISM_FLOOR = 90.0     # below this, displayed = raw (rounded to 1 dp)
REALISM_BASE_PENALTY = 1.5
REALISM_SAMPLE_K = 5.0   # multiplier on 1/sqrt(N)
REALISM_VARIANCE_K = 8.0 # multiplier on observed accuracy stdev


# ---------------------------------------------------------------------------
# Output shape (serialisable)
# ---------------------------------------------------------------------------

@dataclass
class SprintAudit:
    sprint_id: str
    sprint_name: str
    end_date: Optional[str]                # ISO 8601 or None
    planned_sp: float
    completed_sp: float
    ratio: float                           # completed / planned (uncapped)
    accuracy: int                          # 0-100
    hit_goal: bool                         # within ±GOAL_HIT_TOLERANCE
    weight: float                          # recency weight applied


@dataclass
class PredictabilityBreakdown:
    commitment_accuracy: Optional[int] = None     # 0-100
    sprint_goal_hit_rate: Optional[int] = None    # 0-100
    stability: Optional[int] = None               # 0-100


@dataclass
class CapInfo:
    """How the displayed ``score`` differs from the raw weighted composite.

    Surfaced in the UI so the stakeholder understands why the components
    don't sum to the headline number — e.g. "components math to 90 but
    we cap at 75 with only 1 sprint of evidence."
    """
    applied: bool = False
    raw: Optional[float] = None      # raw weighted composite before any cap
    capped_at: Optional[float] = None
    reason: Optional[str] = None     # human-readable, e.g. "1 sprint of evidence"


@dataclass
class VelocityTrend:
    """Direction the team's actual delivered SP is moving over time.

    Computed from the last N sprints' completed SP values: ``up`` if the
    most recent half outperforms the older half by ≥10%, ``down`` if
    underperforms by ≥10%, ``flat`` otherwise. ``None`` when n < 2.
    """
    direction: Optional[str] = None  # "up" | "flat" | "down"
    delta_pct: Optional[float] = None
    current_avg_sp: Optional[float] = None
    prior_avg_sp: Optional[float] = None


@dataclass
class Throughput:
    """Absolute output metrics — useful when accuracy/hit rate are
    misleading (e.g. team consistently delivers 5 SP planned + 5 SP
    completed = 100% accuracy but the absolute throughput is tiny)."""
    avg_completed_sp: Optional[float] = None
    total_completed_sp: Optional[float] = None
    sprint_count: int = 0


@dataclass
class PredictabilityResult:
    score: Optional[float] = None                 # 0-100 composite (one decimal), None if insufficient data
    breakdown: PredictabilityBreakdown = field(default_factory=PredictabilityBreakdown)
    sprints: list[SprintAudit] = field(default_factory=list)
    reason_hidden: Optional[str] = None
    narrative: Optional[str] = None               # one-sentence human summary
    cap: CapInfo = field(default_factory=CapInfo)
    velocity_trend: VelocityTrend = field(default_factory=VelocityTrend)
    throughput: Throughput = field(default_factory=Throughput)

    def to_dict(self) -> dict:
        d = asdict(self)
        # dataclass-to-dict converts the sprints list fine; snake_case keys
        # are turned into camelCase by the API router at the serialisation
        # boundary.
        return d


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def compute_predictability(
    db: AsyncSession,
    org_id: str,
    project_id: Optional[str],
) -> PredictabilityResult:
    """Compute the delivery predictability score for a project.

    ``project_id=None`` falls back to all iterations in the org, which is the
    stakeholder portfolio view. The caller typically scopes by project.
    """
    # ---- 1. Load recent completed sprints ------------------------------
    sprint_rows = await _load_recent_completed_sprints(db, org_id, project_id)
    if not sprint_rows:
        return PredictabilityResult(
            reason_hidden="no_completed_sprints",
            narrative="No completed sprints yet — predictability needs sprint history.",
        )

    # ---- 2. For each sprint compute ratio / accuracy / hit ------------
    # Skip sprints with zero committed work — they're unmeasurable, not
    # "bad", and shouldn't consume a recency-weight slot. The recency
    # weights below are applied by MEASURABLE position (0 = most recent
    # measurable sprint) so "we only have 2 measurable sprints, they get
    # the top two weights" stays intuitive for the stakeholder tooltip.
    audits: list[SprintAudit] = []
    for sp in sprint_rows:
        planned_sp, completed_sp = await _sprint_planned_done_sp(db, sp.id)
        if planned_sp <= 0:
            planned_sp, completed_sp = await _sprint_planned_done_items(db, sp.id)
        if planned_sp <= 0:
            continue
        ratio = completed_sp / planned_sp
        accuracy = max(0.0, 1.0 - abs(ratio - 1.0))
        hit = 1.0 - GOAL_HIT_TOLERANCE <= ratio <= 1.0 + GOAL_HIT_TOLERANCE
        audits.append(SprintAudit(
            sprint_id=sp.id,
            sprint_name=sp.name or f"Sprint {len(audits) + 1}",
            end_date=sp.end_date.isoformat() if sp.end_date else None,
            planned_sp=round(planned_sp, 2),
            completed_sp=round(completed_sp, 2),
            ratio=round(ratio, 3),
            accuracy=round(accuracy * 100),
            hit_goal=bool(hit),
            weight=0.0,  # assigned below once the final measurable list is known
        ))

    # Assign recency weights now that we know the measurable set — most
    # recent audit = RECENCY_WEIGHTS[0], next = RECENCY_WEIGHTS[1], ...
    for idx, a in enumerate(audits):
        a.weight = RECENCY_WEIGHTS[idx] if idx < len(RECENCY_WEIGHTS) else 0.0

    if not audits:
        return PredictabilityResult(
            reason_hidden="no_measurable_sprints",
            narrative="Completed sprints exist but none had committed work to measure.",
        )

    # ---- 3. Components ------------------------------------------------
    # Rescale recency weights over whatever sprints we actually have.
    weight_sum = sum(a.weight for a in audits) or 1.0
    commitment_accuracy = sum(a.accuracy * a.weight for a in audits) / weight_sum

    hit_rate = sum(1 for a in audits if a.hit_goal) / len(audits) * 100.0

    # Stability: stdev of accuracies (expressed as 0-1 fraction).
    acc_fractions = [a.accuracy / 100.0 for a in audits]
    mean_acc = sum(acc_fractions) / len(acc_fractions)
    variance = sum((x - mean_acc) ** 2 for x in acc_fractions) / len(acc_fractions)
    stdev = math.sqrt(variance)
    stability = max(0.0, 1.0 - 2.0 * stdev) * 100.0

    breakdown = PredictabilityBreakdown(
        commitment_accuracy=round(commitment_accuracy),
        sprint_goal_hit_rate=round(hit_rate),
        stability=round(stability),
    )

    # ---- 4. Composite score ------------------------------------------
    # Stability always contributes at its computed value with the new
    # 10% weight (Hotfix 12 reweighting). No accuracy-coupling: a team
    # that consistently delivers 0% genuinely IS predictable at a low
    # level, and the math should reflect that ("you can confidently
    # predict ~zero output, but at least there's a pattern").
    #
    # For n<3 the breakdown still reports stability=None so the UI
    # renders "—" instead of a misleading "100%" — single-point variance
    # is mathematically meaningless even though the value defaults to
    # 100 and naturally contributes +10 to the composite as a small
    # baseline ("process exists, the team is showing up").
    n_sprints = len(audits)
    if n_sprints < 3:
        breakdown.stability = None  # mark N/A in the per-component view
    overall_raw = (
        commitment_accuracy * W_ACCURACY
        + hit_rate * W_HIT_RATE
        + stability * W_STABILITY
    )
    overall_raw = max(0.0, min(100.0, overall_raw))

    # Sample-size confidence cap. With only 1–2 completed sprints the
    # stakeholder shouldn't see a high-confidence reading no matter how
    # well those sprints went — there isn't enough evidence yet. The
    # realism ceiling (below) only kicks in when n >= 3.
    cap_info = CapInfo(applied=False, raw=round(overall_raw, 1))
    if n_sprints == 1:
        confidence_cap = 75.0
        cap_reason = "Only 1 completed sprint of evidence — needs 3+ for full confidence."
    elif n_sprints == 2:
        confidence_cap = 85.0
        cap_reason = "Only 2 completed sprints of evidence — needs 3+ for full confidence."
    else:
        confidence_cap = None
        cap_reason = None

    if confidence_cap is not None:
        if overall_raw > confidence_cap:
            overall = confidence_cap
            cap_info = CapInfo(
                applied=True,
                raw=round(overall_raw, 1),
                capped_at=confidence_cap,
                reason=cap_reason,
            )
        else:
            overall = overall_raw
    else:
        # Realism ceiling for n>=3 — perfect predictability across
        # multiple sprints is functionally impossible; cap below 100
        # by an amount that scales with √N and observed stdev so the
        # number reads as real measurement, not a rounded artifact.
        realism_penalty = (
            REALISM_BASE_PENALTY
            + REALISM_SAMPLE_K / math.sqrt(n_sprints)
            + REALISM_VARIANCE_K * stdev
        )
        realism_ceiling = max(REALISM_FLOOR, 100.0 - realism_penalty)
        if overall_raw >= REALISM_FLOOR and overall_raw > realism_ceiling:
            overall = realism_ceiling
            cap_info = CapInfo(
                applied=True,
                raw=round(overall_raw, 1),
                capped_at=round(realism_ceiling, 1),
                reason="Perfect predictability across multiple sprints is functionally impossible — capped to a realistic ceiling.",
            )
        else:
            overall = overall_raw

    # Round to one decimal so the UI gets fractional precision (96.4
    # rather than 96 or 100).
    overall = round(overall, 1)

    # Velocity trend — split the audit list in half (most recent vs older)
    # and compare avg completed SP. ``up`` if the recent half is ≥10%
    # higher than the older half, ``down`` if ≥10% lower, ``flat`` else.
    velocity = VelocityTrend()
    if n_sprints >= 2:
        half = max(1, n_sprints // 2)
        recent = audits[:half]
        prior = audits[half:] if half < n_sprints else audits[half - 1 :]
        recent_avg = sum(a.completed_sp for a in recent) / len(recent)
        prior_avg = sum(a.completed_sp for a in prior) / len(prior) if prior else recent_avg
        if prior_avg > 0:
            delta = (recent_avg - prior_avg) / prior_avg * 100.0
        elif recent_avg > 0:
            delta = 100.0  # going from 0 → something is "up"
        else:
            delta = 0.0
        if delta >= 10.0:
            direction = "up"
        elif delta <= -10.0:
            direction = "down"
        else:
            direction = "flat"
        velocity = VelocityTrend(
            direction=direction,
            delta_pct=round(delta, 1),
            current_avg_sp=round(recent_avg, 1),
            prior_avg_sp=round(prior_avg, 1),
        )

    # Throughput — absolute output averaged across the audit window.
    total_completed = sum(a.completed_sp for a in audits)
    throughput = Throughput(
        avg_completed_sp=round(total_completed / n_sprints, 1) if n_sprints else None,
        total_completed_sp=round(total_completed, 1),
        sprint_count=n_sprints,
    )

    narrative = _build_narrative(overall, breakdown, audits)

    return PredictabilityResult(
        score=overall,
        breakdown=breakdown,
        sprints=audits,
        narrative=narrative,
        cap=cap_info,
        velocity_trend=velocity,
        throughput=throughput,
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _load_recent_completed_sprints(
    db: AsyncSession,
    org_id: str,
    project_id: Optional[str],
) -> list[Iteration]:
    """Return up to LOOKBACK_SPRINTS completed iterations, most recent first.

    "Completed" here means EITHER:
      (a) the iteration's `state` field is one of completed/closed/past
          (the trustworthy signal when the PM tool is well-configured), OR
      (b) the iteration's `end_date` is already in the past.

    Why (b) exists: real ADO projects routinely leave `timeFrame=future`
    set on sprints whose end_date has long passed, especially when the
    team uses ADO's iteration tree without rolling timeFrames forward.
    Without (b), a project whose iterations have all been worked on but
    never marked "past" in ADO returns `no_completed_sprints` and the
    delivery predictability bar is permanently empty — even though the
    raw history needed to compute predictability is right there.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    q = select(Iteration).where(
        Iteration.organization_id == org_id,
        or_(
            func.lower(Iteration.state).in_(("completed", "closed", "past")),
            and_(
                Iteration.end_date.isnot(None),
                Iteration.end_date < now,
            ),
        ),
    )
    if project_id:
        q = q.where(Iteration.imported_project_id == project_id)
    q = q.order_by(Iteration.end_date.desc()).limit(LOOKBACK_SPRINTS)
    result = await db.execute(q)
    return list(result.scalars().all())


async def _sprint_planned_done_sp(
    db: AsyncSession,
    iteration_id: str,
) -> tuple[float, float]:
    """Sum of story points: (planned, completed) for one sprint."""
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
        ).where(WorkItem.iteration_id == iteration_id)
    )
    row = q.first() or (0.0, 0.0)
    return float(row[0] or 0.0), float(row[1] or 0.0)


async def _sprint_planned_done_items(
    db: AsyncSession,
    iteration_id: str,
) -> tuple[float, float]:
    """Count-based fallback when story points aren't tracked: (planned, completed)."""
    q = await db.execute(
        select(
            func.count(WorkItem.id),
            func.sum(
                case(
                    (WorkItem.status.in_(("DONE", "CLOSED", "RESOLVED")), 1),
                    else_=0,
                )
            ),
        ).where(WorkItem.iteration_id == iteration_id)
    )
    row = q.first() or (0, 0)
    return float(row[0] or 0), float(row[1] or 0)


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------

def _build_narrative(
    overall: float,
    b: PredictabilityBreakdown,
    audits: list[SprintAudit],
) -> str:
    """One-sentence summary for the stakeholder page + weekly PDF."""
    n = len(audits)
    if overall >= 85:
        tone = "Team is delivering what it commits to."
    elif overall >= 60:
        tone = "Team usually hits its commitments with some slippage."
    else:
        tone = "Commitments are routinely missed or overshot."

    # Flag the biggest contributor that pulled the score DOWN.
    parts: list[str] = []
    if b.commitment_accuracy is not None and b.commitment_accuracy < 70:
        parts.append("commitments land off-target")
    if b.sprint_goal_hit_rate is not None and b.sprint_goal_hit_rate < 50:
        parts.append("fewer than half of recent sprints hit their goal")
    if b.stability is not None and b.stability < 60:
        parts.append("recent sprints swing between under- and over-delivery")

    hint = (" Specifically: " + "; ".join(parts) + ".") if parts else ""
    return f"{tone} Measured across the last {n} completed sprint{'' if n == 1 else 's'}.{hint}"

"""AI phase classifier — semantic placement when rules don't match.

Why this exists
---------------
Plan2Sprint's phase resolution chain is:

    1. Manual override (PO drag) → use it
    2. Rules engine (keyword + board_column) → use match
    3. AI classifier (this module) → use match
    4. Status fallback (terminal → last work phase, else → first)

Tier 3 fires only when keyword + board_column rules return None. The
classifier reads the feature's title, description, acceptance criteria,
and the list of phases available on the project, and asks Grok to pick
the slug that best fits.

Result is cached on the WorkItem (``ai_classified_phase_id`` plus an
``ai_classified_input_hash`` so we know when to re-run). Cache hits
skip the LLM entirely; cache misses pay one round-trip per feature.

Determinism notes
-----------------
LLM responses are non-deterministic by design. We mitigate with:
  * temperature=0.1 — very conservative
  * the prompt asks for STRICT JSON with one field (``phase_slug``)
  * we validate the slug against the project's actual phase list and
    reject hallucinated slugs (skip cache write, fall back to status
    rule), so a flaky model can't poison the cache with garbage.

Failure modes
-------------
Network / quota / parse errors are caught and the function returns
``None``. Caller falls back to the next tier. The classifier never
raises — dashboard reads must not crash because Grok had a bad day.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


# Use the same Grok model the sprint generator uses, with a tighter
# temperature/timeout because this is a single-classification task with a
# tiny output.
AI_MODEL = settings.azure_ai_model or "grok-4-fast-reasoning"
AI_TIMEOUT_S = 25.0  # short — this is a fast classification call
AI_MAX_TOKENS = 256  # output is just {"phase_slug": "...", "confidence": ...}
AI_TEMPERATURE = 0.1


def compute_input_hash(
    title: str,
    description: Optional[str],
    acceptance_criteria: Optional[str],
    phase_slugs: list[str],
) -> str:
    """Hash the inputs we'd send to the LLM. Cache key for the classifier.

    Includes the project's phase slug list so that adding a new phase
    invalidates the cache (the classifier might pick the new phase).
    Stable across runs for the same inputs — ``hashlib.sha256`` is
    deterministic.
    """
    payload = json.dumps(
        {
            "t": title or "",
            "d": (description or "")[:4000],
            "a": (acceptance_criteria or "")[:4000],
            "p": sorted(phase_slugs),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_prompt(
    title: str,
    description: Optional[str],
    acceptance_criteria: Optional[str],
    phases: list[dict],
) -> str:
    """Assemble the classification prompt.

    ``phases`` is a list of dicts with keys ``slug``, ``name`` (and
    optionally ``description``) — the candidate phases for this project.
    The model is asked to pick exactly one slug from this list.
    """
    phase_lines = "\n".join(
        f"  - {p['slug']}: {p['name']}" for p in phases
    )

    desc_block = (description or "(no description provided)").strip()[:2000]
    ac_block = (acceptance_criteria or "(no acceptance criteria provided)").strip()[:2000]

    return f"""You are classifying a software work item into the project's lifecycle phase.

PROJECT PHASES (you must pick exactly one slug from this list):
{phase_lines}

WORK ITEM:
Title: {title}

Description:
{desc_block}

Acceptance Criteria:
{ac_block}

Pick the phase slug that best matches what the work item is about. Use the
description and acceptance criteria — not just the title — to decide.

Return STRICT JSON only, no markdown, no commentary:
{{"phase_slug": "<one of the slugs above>", "confidence": <0.0-1.0>, "reasoning": "<one short sentence>"}}
"""


async def classify_feature_phase(
    title: str,
    description: Optional[str],
    acceptance_criteria: Optional[str],
    phases: list[dict],
) -> Optional[dict]:
    """Classify a single feature into one of the project's phases.

    Returns ``None`` on any failure (network, quota, malformed response,
    hallucinated slug). Returns ``{"phase_slug", "confidence", "reasoning"}``
    on success. Caller is responsible for resolving slug → phase_id and
    persisting the cache fields.

    ``phases`` must be a list of ``{"slug": str, "name": str}`` dicts.
    Empty/missing phases → returns None (nothing to classify into).

    Hotfix 30 — uses ``call_ai`` with primary→secondary failover. The
    classifier task is narrow enough that we don't want o4-mini's
    reasoning effort here even when it serves the request, so we pass
    ``reasoning_effort="low"`` (ignored by Grok, harmless to o4-mini).
    """
    if not phases:
        return None
    if not (settings.azure_ai_api_key or settings.azure_ai_key) or not settings.azure_ai_endpoint:
        logger.info("AI phase classifier skipped — Azure AI credentials not configured")
        return None

    valid_slugs = {p["slug"] for p in phases}
    prompt = _build_prompt(title, description, acceptance_criteria, phases)

    from .ai_caller import call_ai
    try:
        # Hotfix 33i — JSON mode for stricter output. The classifier
        # always returns ``{"phase_slug", "confidence", "reasoning"}``.
        ai_text = await call_ai(
            messages=[{"role": "user", "content": prompt}],
            mode="primary",
            max_tokens=AI_MAX_TOKENS,
            temperature=AI_TEMPERATURE,
            reasoning_effort="low",  # narrow task, no deep thinking needed
            response_format={"type": "json_object"},
            timeout_s=AI_TIMEOUT_S,
        )
        if not ai_text:
            logger.warning(f"[ai_phase_classifier] both models exhausted for '{title[:60]}'")
            return None
    except Exception as e:  # noqa: BLE001 - never crash dashboard on classifier failure
        logger.warning(f"[ai_phase_classifier] AI call failed for '{title[:60]}': {e}")
        return None

    # Parse JSON, tolerating markdown wrapping.
    try:
        clean = ai_text.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?\s*\n?", "", clean)
            clean = re.sub(r"\n?```\s*$", "", clean)
        parsed = json.loads(clean)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ai_phase_classifier] Could not parse response for '{title[:60]}': {e!r}")
        return None

    slug = parsed.get("phase_slug")
    if not slug or slug not in valid_slugs:
        # Hallucinated slug — don't write to cache, let caller fall through.
        logger.warning(
            f"[ai_phase_classifier] Invalid slug '{slug}' returned for '{title[:60]}'. "
            f"Valid: {sorted(valid_slugs)}"
        )
        return None

    return {
        "phase_slug": slug,
        "confidence": float(parsed.get("confidence", 0.5)),
        "reasoning": str(parsed.get("reasoning", ""))[:300],
    }


async def classify_unmatched_features_in_background(
    project_id: str,
    org_id: str,
) -> None:
    """Background entry-point: classify all unmatched features for a project.

    Pass-2 pattern. Called via FastAPI ``BackgroundTasks`` after the
    dashboard response is sent. Opens a fresh DB session (the request
    session is gone by the time this fires), loads every feature for
    the project, and for any feature whose phase was decided by the
    status fallback (or which has no cache yet), runs the LLM
    classifier and writes the result.

    Idempotent — if two background runs collide on the same feature,
    they'll both compute the same hash and either both succeed (cheap
    duplicate) or one writes and the other no-ops. Worst case is a
    couple of duplicate Grok calls per feature; not enough to bother
    with locking infrastructure.

    Never raises — wraps the whole body in a try/except so a failure
    here can't crash anything else.

    Hotfix 22 — removed the "skip if phase_id is set" guard that was
    preventing classification entirely. The resolver persists ANY tier
    of decision (rules match, AI cache hit, status fallback) into
    ``phase_id`` so the dashboard renders consistently. That meant by
    the time the background task ran, every feature already had a
    phase_id and the classifier short-circuited. We can't distinguish
    "manually placed by PO" from "fallback placed" at this layer
    without a marker column, so we simply DON'T skip on phase_id.
    Manual placements still win at the resolver level (tier 1) — the
    AI verdict goes into ``ai_classified_phase_id`` separately and only
    surfaces when there's no manual override AND no rule match.
    Hash-cache check still skips features whose AI verdict is current,
    so we don't pay repeatedly for the same input.
    """
    from ..database import AsyncSessionLocal
    from ..models.work_item import WorkItem
    from ..models.project_phase import ProjectPhase
    from ..routers.phases import resolve_phase_for_feature, _load_rules_flat
    from sqlalchemy import select as _select

    logger.info(
        f"[ai_phase_classifier] background task START project={project_id}"
    )
    try:
        async with AsyncSessionLocal() as db:
            phase_rows = (
                await db.execute(
                    _select(ProjectPhase).where(
                        ProjectPhase.project_id == project_id,
                        ProjectPhase.organization_id == org_id,
                    )
                )
            ).scalars().all()
            if not phase_rows:
                logger.info(
                    f"[ai_phase_classifier] no phases for project {project_id}, "
                    "skipping classification"
                )
                return
            phases = [
                {"id": p.id, "slug": p.slug, "name": p.name}
                for p in phase_rows
            ]
            phase_slugs = [p["slug"] for p in phases]

            rules = await _load_rules_flat(db, project_id, org_id)

            features = (
                await db.execute(
                    _select(WorkItem).where(
                        WorkItem.imported_project_id == project_id,
                        WorkItem.organization_id == org_id,
                        WorkItem.type.in_(["feature", "epic"]),
                    )
                )
            ).scalars().all()

            considered = 0
            skipped_rule_match = 0
            skipped_cache_fresh = 0
            classified_count = 0

            for f in features:
                considered += 1
                # Skip if rules currently match — features that have a
                # solid rule match don't need an LLM second opinion.
                rule_match = resolve_phase_for_feature(
                    title=f.title,
                    source_status=f.source_status,
                    iteration_path=None,
                    rules=rules,
                    item_type=getattr(f, "type", None),
                )
                if rule_match:
                    skipped_rule_match += 1
                    continue
                # Skip if AI cache is already fresh for the current inputs.
                fresh_hash = compute_input_hash(
                    f.title or "",
                    getattr(f, "description", None),
                    getattr(f, "acceptance_criteria", None),
                    phase_slugs,
                )
                if (
                    f.ai_classified_input_hash == fresh_hash
                    and f.ai_classified_phase_id
                ):
                    skipped_cache_fresh += 1
                    continue
                # Classify.
                got = await classify_and_cache(f, phases, db)
                if got:
                    classified_count += 1

            if classified_count > 0:
                await db.commit()

            logger.info(
                f"[ai_phase_classifier] background DONE project={project_id} "
                f"considered={considered} skipped_rule_match={skipped_rule_match} "
                f"skipped_cache_fresh={skipped_cache_fresh} "
                f"classified={classified_count}"
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"[ai_phase_classifier] background classification failed for "
            f"project {project_id}: {e!r}"
        )


async def classify_and_cache(
    feature,
    phases: list[dict],
    db,
) -> Optional[str]:
    """High-level entry point.

    1. Hash the inputs; if they match the cached hash AND the cached
       phase_id is still in the available phases, return the cached
       phase_id directly (no LLM call).
    2. Otherwise call the classifier, validate the returned slug, write
       the phase_id + hash + timestamp back onto the work item, return
       the resolved phase_id.
    3. On any failure, return None — caller falls back to status rule.

    The caller is responsible for ``db.commit()`` (typically the dashboard
    request commits at end of the handler).
    """
    phase_slugs = [p["slug"] for p in phases]
    slug_to_id = {p["slug"]: p["id"] for p in phases}
    valid_phase_ids = set(slug_to_id.values())

    new_hash = compute_input_hash(
        feature.title or "",
        getattr(feature, "description", None),
        getattr(feature, "acceptance_criteria", None),
        phase_slugs,
    )

    # Cache hit?
    cached_hash = getattr(feature, "ai_classified_input_hash", None)
    cached_phase_id = getattr(feature, "ai_classified_phase_id", None)
    if (
        cached_hash == new_hash
        and cached_phase_id
        and cached_phase_id in valid_phase_ids
    ):
        return cached_phase_id

    # Cache miss — call the classifier.
    result = await classify_feature_phase(
        title=feature.title or "",
        description=getattr(feature, "description", None),
        acceptance_criteria=getattr(feature, "acceptance_criteria", None),
        phases=phases,
    )
    if not result:
        return None

    phase_id = slug_to_id.get(result["phase_slug"])
    if not phase_id:
        return None

    # Persist cache so future reads skip the LLM.
    feature.ai_classified_phase_id = phase_id
    feature.ai_classified_at = datetime.now(timezone.utc)
    feature.ai_classified_input_hash = new_hash

    logger.info(
        f"[ai_phase_classifier] '{feature.title[:60]}' → {result['phase_slug']} "
        f"(conf={result['confidence']:.2f}): {result['reasoning']}"
    )
    return phase_id

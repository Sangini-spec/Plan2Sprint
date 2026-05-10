"""Unified AI caller with two-model failover (Hotfix 30).

Why this exists
---------------
We run two AI models on Azure:

  * **Primary**: Grok-4-1-fast-reasoning on Azure AI Foundry (Inference API)
    - Endpoint: ``…services.ai.azure.com/models/chat/completions?api-version=…``
    - Request body uses ``model`` field, ``max_tokens``, no reasoning_effort
  * **Secondary**: o4-mini on Azure OpenAI Service
    - Endpoint: ``…cognitiveservices.azure.com/openai/deployments/{name}/chat/completions?api-version=…``
    - Request body uses ``max_completion_tokens``, supports ``reasoning_effort``,
      no ``model`` in body (deployment is in URL path)

The two APIs are subtly different. This module hides that difference so
callers (sprint generator, rebalancer, classifier) can stay clean.

Routing
-------
``call_ai`` picks an order based on ``mode``:

  * ``mode="primary"`` (default)  → try Grok first, fall back to o4-mini
  * ``mode="reasoning"``           → try o4-mini first, fall back to Grok
  * ``mode="secondary_only"``      → only try o4-mini (used for the
    rebalancer where deeper reasoning is worth the latency)

A try is considered failed (and the next model is attempted) on:
  * httpx.TimeoutException
  * HTTP 429 (rate-limited)
  * HTTP 5xx
  * Empty response body
  * Body that doesn't parse as the expected chat-completion shape

A try is NOT retried on HTTP 400 (caller's prompt is broken — failing over
won't help) or HTTP 401 (auth issue, both models would fail the same way).

Reasoning effort
----------------
o4-mini supports ``reasoning_effort: "low" | "medium" | "high"``. We
expose that as a kwarg so callers can dial it per call site:

  * Phase classifier  → ``"low"`` (one-shot, cheap, narrow task)
  * Sprint generator  → ``"medium"`` (constraints to weigh)
  * Rebalancer        → ``"high"`` (project-saving stakes)

Grok ignores this parameter — only o4-mini uses it.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Endpoint shape detection
# ---------------------------------------------------------------------------

def _is_azure_openai_style(endpoint: str) -> bool:
    """True for Azure OpenAI Service endpoints (cognitiveservices.azure.com/openai/…).

    These take a different request body shape than the Inference API used
    for Grok. Detection via URL pattern is robust enough — we own both
    endpoints and the host parts are stable.
    """
    if not endpoint:
        return False
    return "cognitiveservices.azure.com/openai/" in endpoint


# ---------------------------------------------------------------------------
# Per-protocol request shaping
# ---------------------------------------------------------------------------

def _build_inference_body(
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float,
    response_format: Optional[dict],
) -> dict:
    """Body shape for Azure AI Inference API (Grok)."""
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format:
        body["response_format"] = response_format
    return body


def _build_openai_body(
    messages: list[dict],
    max_tokens: int,
    reasoning_effort: Optional[str],
    response_format: Optional[dict],
) -> dict:
    """Body shape for Azure OpenAI Service (o-series).

    Notable differences vs. the Inference API:
      * ``max_completion_tokens`` instead of ``max_tokens``
      * No ``model`` field — deployment name lives in the URL path
      * No ``temperature`` (o-series ignores it; harmless to omit)
      * Optional ``reasoning_effort`` ∈ {"low", "medium", "high"}

    Hotfix 33i — reasoning headroom. o-series models consume hidden
    "reasoning tokens" BEFORE producing visible output, and those count
    toward ``max_completion_tokens``. Empirically, ``reasoning_effort=
    "high"`` on a 10-12 KB prompt can eat 5-15K reasoning tokens; if we
    pass the same budget the caller wanted for visible output, the
    model exhausts the limit on internal thinking and returns empty
    content (this happened on the rebalancer call).
    We auto-scale the budget here so callers don't have to know about
    reasoning-token accounting:
      * effort=low    → output × 1.5  (some thinking, mostly direct)
      * effort=medium → output × 2.5
      * effort=high   → output × 4.0
      * no effort     → unchanged (pass through caller's budget)
    Floor of 4096 to avoid degenerate tiny budgets.
    """
    if reasoning_effort == "high":
        effective_max = max(int(max_tokens * 4.0), 4096)
    elif reasoning_effort == "medium":
        effective_max = max(int(max_tokens * 2.5), 4096)
    elif reasoning_effort == "low":
        effective_max = max(int(max_tokens * 1.5), 4096)
    else:
        effective_max = max_tokens

    body: dict[str, Any] = {
        "messages": messages,
        "max_completion_tokens": effective_max,
    }
    if reasoning_effort in ("low", "medium", "high"):
        body["reasoning_effort"] = reasoning_effort
    if response_format:
        body["response_format"] = response_format
    return body


# ---------------------------------------------------------------------------
# Single-model invocation
# ---------------------------------------------------------------------------

async def _try_call(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    reasoning_effort: Optional[str],
    response_format: Optional[dict],
    timeout_s: float,
    label: str,
) -> Optional[str]:
    """Make one call to one model. Returns the assistant's content on
    success, or ``None`` on a failure that should trigger failover.

    Caller is responsible for trying the next model when this returns
    ``None``. Raises only on programmer errors (e.g. missing config) —
    everything else is logged and turned into ``None``.
    """
    if not endpoint or not api_key:
        logger.info(f"[ai_caller] {label} skipped — endpoint or key not configured")
        return None

    if _is_azure_openai_style(endpoint):
        body = _build_openai_body(messages, max_tokens, reasoning_effort, response_format)
    else:
        body = _build_inference_body(messages, model, max_tokens, temperature, response_format)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            resp = await client.post(
                endpoint,
                headers={"Content-Type": "application/json", "api-key": api_key},
                json=body,
            )
    except httpx.TimeoutException:
        logger.warning(f"[ai_caller] {label} timeout after {timeout_s}s — will failover")
        return None
    except Exception as e:  # noqa: BLE001 — network, DNS, TLS, anything weird
        logger.warning(f"[ai_caller] {label} request crashed: {e!r} — will failover")
        return None

    if resp.status_code == 401 or resp.status_code == 400:
        # Don't bother failing over — auth or prompt is broken either way.
        # Log loudly so the caller's exception handler sees it in logs.
        body_excerpt = resp.text[:300] if resp.text else "(empty)"
        logger.error(
            f"[ai_caller] {label} HTTP {resp.status_code} (no failover): {body_excerpt}"
        )
        return None

    if resp.status_code == 429 or resp.status_code >= 500:
        body_excerpt = resp.text[:200] if resp.text else "(empty)"
        logger.warning(
            f"[ai_caller] {label} HTTP {resp.status_code}: {body_excerpt} — will failover"
        )
        return None

    if resp.status_code >= 400:
        body_excerpt = resp.text[:200] if resp.text else "(empty)"
        logger.warning(
            f"[ai_caller] {label} HTTP {resp.status_code}: {body_excerpt}"
        )
        return None

    try:
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ai_caller] {label} non-JSON body: {e!r}")
        return None

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        logger.warning(f"[ai_caller] {label} unexpected schema: {e!r}; keys={list(data) if isinstance(data, dict) else type(data)}")
        return None

    if not content or not isinstance(content, str):
        logger.warning(f"[ai_caller] {label} empty content")
        return None

    # Useful telemetry — log token usage when present so we can spot
    # runaway prompts.
    usage = data.get("usage") or {}
    if usage:
        logger.info(
            f"[ai_caller] {label} ok — prompt_tokens={usage.get('prompt_tokens')} "
            f"completion_tokens={usage.get('completion_tokens')}"
        )
    return content


# ---------------------------------------------------------------------------
# Public API — failover-aware caller
# ---------------------------------------------------------------------------

async def call_ai(
    messages: list[dict],
    *,
    mode: str = "primary",
    max_tokens: int = 4096,
    temperature: float = 0.2,
    reasoning_effort: Optional[str] = None,
    response_format: Optional[dict] = None,
    timeout_s: float = 90.0,
) -> Optional[str]:
    """Call AI with two-model failover.

    Args
    ----
    messages: chat-style messages list, e.g. [{"role": "user", "content": "..."}].
    mode: ``"primary"`` (Grok → o4-mini), ``"reasoning"`` (o4-mini → Grok),
          or ``"secondary_only"`` (o4-mini, no fallback).
    max_tokens: hard cap on output tokens. Maps to ``max_tokens`` for Grok
                and ``max_completion_tokens`` for o4-mini.
    temperature: only used by Grok. o-series ignores it.
    reasoning_effort: only used by o4-mini. ``"low"``/``"medium"``/``"high"``.
    response_format: optional, e.g. ``{"type": "json_object"}``. Both
                     endpoints accept it.
    timeout_s: per-call timeout. Total wall time can be 2×this in the
               worst-case failover.

    Returns
    -------
    The assistant's content string on success, or ``None`` if both models
    failed. Callers must handle ``None`` (typically by raising a clear
    error to the request handler).
    """
    primary = (
        settings.azure_ai_endpoint,
        settings.azure_ai_api_key or settings.azure_ai_key,
        settings.azure_ai_model,
        "grok",
    )
    secondary = (
        settings.azure_ai_endpoint_2,
        settings.azure_ai_api_key_2 or settings.azure_ai_key_2,
        settings.azure_ai_model_2,
        "o4-mini",
    )

    if mode == "secondary_only":
        order = [secondary]
    elif mode == "reasoning":
        order = [secondary, primary]
    else:
        order = [primary, secondary]

    for endpoint, api_key, model, label in order:
        if not endpoint or not api_key:
            continue
        result = await _try_call(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            response_format=response_format,
            timeout_s=timeout_s,
            label=label,
        )
        if result is not None:
            return result

    logger.error("[ai_caller] all models exhausted, returning None")
    return None

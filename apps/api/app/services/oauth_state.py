"""
OAuth state store — Redis-backed with in-memory fallback.

Stores CSRF state tokens for OAuth flows (Jira, ADO, GitHub, Slack, Teams).
Uses Redis with a 10-minute TTL when available; falls back to a size-limited
in-memory dict when Redis is disabled or unreachable.

Usage:
    from ..services.oauth_state import save_oauth_state, pop_oauth_state

    await save_oauth_state(state_key, {"org_id": "...", "user_id": "..."})
    data = await pop_oauth_state(state_key)  # returns dict or None
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# In-memory fallback (used when Redis is unavailable)
_memory_store: dict[str, dict[str, Any]] = {}
_MAX_MEMORY_ENTRIES = 500
_TTL_SECONDS = 600  # 10 minutes

REDIS_KEY_PREFIX = "p2s:oauth_state:"


async def save_oauth_state(state: str, data: dict[str, Any]) -> None:
    """Persist an OAuth state token with associated data."""
    from .redis_pool import get_redis

    redis = await get_redis()
    if redis:
        try:
            await redis.setex(
                f"{REDIS_KEY_PREFIX}{state}",
                _TTL_SECONDS,
                json.dumps(data, default=str),
            )
            return
        except Exception:
            logger.warning("[OAuthState] Redis write failed, using memory fallback")

    # In-memory fallback — prune expired entries first
    now = time.time()
    expired = [k for k, v in _memory_store.items() if v.get("_expires", 0) < now]
    for k in expired:
        del _memory_store[k]

    # Evict oldest if over limit
    if len(_memory_store) >= _MAX_MEMORY_ENTRIES:
        oldest = min(_memory_store, key=lambda k: _memory_store[k].get("_expires", 0))
        del _memory_store[oldest]

    data["_expires"] = now + _TTL_SECONDS
    _memory_store[state] = data


async def pop_oauth_state(state: str) -> dict[str, Any] | None:
    """Retrieve and delete an OAuth state token. Returns None if not found or expired."""
    from .redis_pool import get_redis

    redis = await get_redis()
    if redis:
        try:
            raw = await redis.getdel(f"{REDIS_KEY_PREFIX}{state}")
            if raw:
                return json.loads(raw)
            # Also check memory fallback (state might have been saved before Redis connected)
        except Exception:
            logger.warning("[OAuthState] Redis read failed, checking memory fallback")

    # In-memory fallback
    data = _memory_store.pop(state, None)
    if data is None:
        return None

    # Check expiry
    if data.get("_expires", 0) < time.time():
        return None

    data.pop("_expires", None)
    return data

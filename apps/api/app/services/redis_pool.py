"""
Redis connection pool singleton.

Provides a shared async Redis client for the event bus, sync scheduler,
and distributed locking. Gracefully returns None when Redis is not
configured or unreachable — callers must always check the return value.

Usage:
    from .redis_pool import get_redis, close_redis

    redis = await get_redis()
    if redis:
        await redis.set("key", "value")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..config import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_pool: "Redis | None" = None


async def get_redis() -> "Redis | None":
    """
    Return the shared async Redis client.

    Returns None if Redis is disabled (no REDIS_URL) or unreachable.
    Lazily creates the pool on first call with a health-check ping.
    """
    global _pool

    if not settings.redis_enabled:
        return None

    if _pool is not None:
        return _pool

    try:
        from redis.asyncio import Redis as AsyncRedis

        client = AsyncRedis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        await client.ping()
        _pool = client
        logger.info("[Redis] Connected to %s", settings.redis_url.split("@")[-1])
        return _pool
    except Exception:
        logger.warning(
            "[Redis] Cannot connect to %s — falling back to in-memory",
            settings.redis_url.split("@")[-1],
            exc_info=True,
        )
        return None


async def close_redis() -> None:
    """Close the Redis connection pool. Safe to call even if not connected."""
    global _pool
    if _pool is not None:
        try:
            await _pool.aclose()
        except Exception:
            pass
        _pool = None
        logger.info("[Redis] Connection pool closed")

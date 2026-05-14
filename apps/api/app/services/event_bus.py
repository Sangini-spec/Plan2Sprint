"""
Redis Streams event bus — durable, ordered event log with consumer groups.

All Plan2Sprint real-time events flow through a single Redis Stream
("events:all") with org_id as a field. Consumer groups enable multiple
independent consumers (WebSocket relay, notification delivery, analytics).

If Redis is unavailable, all functions are no-ops — callers don't need
to handle errors.

Usage:
    from .event_bus import publish, ensure_group, STREAM_KEY, CONSUMER_GROUP

    await publish("org-123", {"type": "sync_complete", "data": {...}})
"""

from __future__ import annotations

import json
import logging

from ..config import settings
from .redis_pool import get_redis

logger = logging.getLogger(__name__)

# Single stream for all events across all orgs.
# org_id is embedded as a field in each entry.
STREAM_KEY = "events:all"

# Consumer group name — all Plan2Sprint workers share this group.
CONSUMER_GROUP = "p2s-consumers"


async def ensure_group() -> bool:
    """
    Create the consumer group if it doesn't exist.

    Returns True if the group exists (created or already present),
    False if Redis is unavailable.
    """
    redis = await get_redis()
    if not redis:
        return False

    try:
        await redis.xgroup_create(
            STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True,
        )
        logger.info("[EventBus] Created consumer group '%s' on '%s'", CONSUMER_GROUP, STREAM_KEY)
    except Exception as e:
        if "BUSYGROUP" in str(e):
            pass  # Group already exists — normal
        else:
            logger.warning("[EventBus] Failed to create consumer group: %s", e)
            return False

    return True


async def publish(org_id: str, event: dict, origin_worker: str | None = None) -> str | None:
    """
    Publish an event to the Redis Stream.

    Args:
        org_id: Organization ID for event scoping.
        event: Event dict (must include "type" and optionally "data").
        origin_worker: Worker ID of the publisher (for deduplication).

    Returns:
        Redis message ID (e.g., "1678886400000-0") or None if unavailable.
    """
    redis = await get_redis()
    if not redis:
        return None

    try:
        # Embed origin for cross-worker deduplication
        payload = {**event}
        if origin_worker:
            payload["_origin"] = origin_worker

        msg_id = await redis.xadd(
            STREAM_KEY,
            {"org_id": org_id, "payload": json.dumps(payload)},
            maxlen=settings.event_stream_max_len,
            approximate=True,
        )
        return msg_id
    except Exception:
        logger.warning("[EventBus] XADD failed for org=%s type=%s", org_id, event.get("type"), exc_info=True)
        return None


async def read_new_messages(
    consumer_name: str,
    count: int = 50,
    block_ms: int = 2000,
) -> list[tuple[str, str, dict]]:
    """
    Read new messages from the stream using consumer group.

    Returns list of (message_id, org_id, event_dict) tuples.
    """
    redis = await get_redis()
    if not redis:
        return []

    try:
        results = await redis.xreadgroup(
            CONSUMER_GROUP, consumer_name,
            {STREAM_KEY: ">"},
            count=count,
            block=block_ms,
        )
    except Exception as e:
        # Azure Cache for Redis Enterprise uses cluster mode; the
        # redis-py async client we use isn't cluster-aware and every
        # XREADGROUP raises ``MovedError``. Propagate that exception
        # to the caller (ws_relay) so the caller can exit the loop
        # cleanly. Other exceptions are logged + swallowed so a
        # transient hiccup doesn't bring down the loop.
        if type(e).__name__ == "MovedError":
            raise
        logger.warning("[EventBus] XREADGROUP failed", exc_info=True)
        return []

    messages = []
    for _stream_name, entries in (results or []):
        for msg_id, fields in entries:
            try:
                org_id = fields.get("org_id", "")
                event = json.loads(fields.get("payload", "{}"))
                messages.append((msg_id, org_id, event))
            except (json.JSONDecodeError, TypeError):
                logger.warning("[EventBus] Malformed message %s — skipping", msg_id)

    return messages


async def ack(message_id: str) -> None:
    """Acknowledge a processed message."""
    redis = await get_redis()
    if redis:
        try:
            await redis.xack(STREAM_KEY, CONSUMER_GROUP, message_id)
        except Exception:
            pass


async def stream_info() -> dict | None:
    """Return stream metadata for monitoring (length, groups, etc.)."""
    redis = await get_redis()
    if not redis:
        return None

    try:
        info = await redis.xinfo_stream(STREAM_KEY)
        return {
            "length": info.get("length", 0),
            "first_entry": info.get("first-entry"),
            "last_entry": info.get("last-entry"),
        }
    except Exception:
        return None

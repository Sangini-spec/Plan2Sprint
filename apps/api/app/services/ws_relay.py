"""
WebSocket relay consumer — reads events from Redis Stream and pushes
them to local WebSocket connections.

This enables multi-worker deployments: when Worker A broadcasts an event,
it publishes to Redis. Worker B's relay consumer picks it up and pushes
to its own local WebSocket connections.

Self-originated events are skipped (dedup via _origin worker_id) since
they were already pushed locally by broadcast().

Usage:
    # In app lifespan startup:
    from .ws_relay import start_ws_relay
    task = await start_ws_relay()

    # In shutdown:
    if task:
        task.cancel()
"""

from __future__ import annotations

import asyncio
import logging

from .event_bus import ensure_group, read_new_messages, ack
from .redis_pool import get_redis
from .ws_manager import ws_manager

logger = logging.getLogger(__name__)


async def start_ws_relay() -> asyncio.Task | None:
    """
    Start the WebSocket relay background task.

    Returns the asyncio.Task, or None if Redis is unavailable.
    """
    redis = await get_redis()
    if not redis:
        logger.info("[WS-Relay] Redis unavailable — relay disabled")
        return None

    if not await ensure_group():
        logger.warning("[WS-Relay] Failed to ensure consumer group — relay disabled")
        return None

    consumer_name = f"ws-relay-{ws_manager.worker_id}"
    task = asyncio.create_task(_relay_loop(consumer_name))
    logger.info("[WS-Relay] Started consumer '%s'", consumer_name)
    return task


async def _relay_loop(consumer_name: str) -> None:
    """
    Main consumer loop — reads from Redis Stream and relays to local WS.

    Runs indefinitely until cancelled. Handles errors gracefully.

    Azure Cache for Redis Enterprise uses the OSS Cluster API, but the
    redis-py async client we use isn't cluster-aware. Every XREADGROUP
    raises ``MovedError`` and the loop tight-spins log lines. Detect that
    once and EXIT the loop cleanly — cross-replica WS broadcasts will be
    disabled until the client is upgraded, but a single replica still
    serves the WebSocket protocol locally via direct broadcasts. The
    standup digest data path doesn't depend on this loop at all.
    """
    moved_error_seen = False
    while True:
        try:
            messages = await read_new_messages(
                consumer_name=consumer_name,
                count=50,
                block_ms=2000,
            )

            for msg_id, org_id, event in messages:
                # Skip self-originated events (already broadcast locally)
                origin = event.pop("_origin", None)
                if origin == ws_manager.worker_id:
                    await ack(msg_id)
                    continue

                # Relay to local WebSocket connections
                try:
                    await ws_manager._local_broadcast(org_id, event)
                except Exception:
                    logger.warning(
                        "[WS-Relay] Failed to relay msg=%s to org=%s",
                        msg_id, org_id, exc_info=True,
                    )

                await ack(msg_id)

        except asyncio.CancelledError:
            logger.info("[WS-Relay] Consumer '%s' shutting down", consumer_name)
            break
        except Exception as e:
            # Detect Azure Redis Enterprise cluster-mode mismatch and
            # stop the loop entirely so we don't tight-spin error logs
            # every 2 seconds for the lifetime of the container.
            if type(e).__name__ == "MovedError":
                if not moved_error_seen:
                    logger.warning(
                        "[WS-Relay] Redis is in cluster mode; this "
                        "client isn't cluster-aware. Disabling the "
                        "cross-replica relay. Direct same-replica WS "
                        "broadcasts continue to work; the standup "
                        "digest doesn't depend on this loop. To re-"
                        "enable, switch the redis client to "
                        "RedisCluster or run a non-cluster Redis."
                    )
                    moved_error_seen = True
                logger.info("[WS-Relay] Exiting consumer '%s' (cluster-mode redis)", consumer_name)
                break
            logger.warning("[WS-Relay] Error in consumer loop — retrying in 1s", exc_info=True)
            await asyncio.sleep(1)

"""
Async delivery queue with retry logic.

All notification sends go through this queue — never direct API calls
from the main request thread. This ensures:
  1. Non-blocking response times (API returns immediately)
  2. Automatic retries with exponential backoff
  3. Audit logging for every delivery attempt
  4. Graceful degradation (in-app fallback if external channels fail)

Usage:
    from ..services.delivery_queue import enqueue_notification
    await enqueue_notification(db, org_id, recipient_email, "blocker_alert", slack_payload, teams_payload)
"""

from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from ..config import settings
from ..database import engine

# Queue for pending deliveries
_delivery_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
_worker_task: Optional[asyncio.Task] = None

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 15]  # seconds between retries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def enqueue_notification(
    org_id: str,
    recipient_email: str,
    notification_type: str,
    slack_payload: dict | None = None,
    teams_payload: dict | None = None,
    in_app_payload: dict | None = None,
) -> None:
    """
    Enqueue a notification for async delivery.
    Returns immediately — delivery happens in the background worker.
    """
    item = {
        "org_id": org_id,
        "recipient_email": recipient_email,
        "notification_type": notification_type,
        "slack_payload": slack_payload,
        "teams_payload": teams_payload,
        "in_app_payload": in_app_payload,
        "retry_count": 0,
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        _delivery_queue.put_nowait(item)
        print(f"[DeliveryQueue] Enqueued: {notification_type} -> {recipient_email} (queue size: {_delivery_queue.qsize()})")
    except asyncio.QueueFull:
        print(f"[DeliveryQueue] WARNING Queue full! Dropping: {notification_type} -> {recipient_email}")


async def start_delivery_worker() -> None:
    """Start the background delivery worker. Called on app startup."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_delivery_worker())
        print("[DeliveryQueue] Worker started")


async def stop_delivery_worker() -> None:
    """Stop the background delivery worker. Called on app shutdown."""
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        print("[DeliveryQueue] Worker stopped")


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

async def _delivery_worker() -> None:
    """
    Long-running background task that processes the delivery queue.
    Each item is delivered via message_router.deliver_notification().
    Failed deliveries are retried with exponential backoff.
    """
    # Create a session factory for the worker (independent of request lifecycle)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    while True:
        try:
            item = await _delivery_queue.get()

            async with SessionFactory() as db:
                try:
                    from .message_router import deliver_notification

                    result = await deliver_notification(
                        db=db,
                        org_id=item["org_id"],
                        recipient_email=item["recipient_email"],
                        notification_type=item["notification_type"],
                        slack_payload=item.get("slack_payload"),
                        teams_payload=item.get("teams_payload"),
                        in_app_payload=item.get("in_app_payload"),
                    )

                    # Check if any external channel succeeded
                    channels = result.get("channels", {})
                    any_sent = any(v == "sent" for v in channels.values())
                    errors = result.get("errors", [])

                    if any_sent:
                        print(
                            f"[DeliveryQueue] OK Delivered: {item['notification_type']} -> "
                            f"{item['recipient_email']} | channels: {channels}"
                        )
                    elif errors and item["retry_count"] < MAX_RETRIES:
                        # Retry with backoff
                        item["retry_count"] += 1
                        delay = RETRY_DELAYS[min(item["retry_count"] - 1, len(RETRY_DELAYS) - 1)]
                        print(
                            f"[DeliveryQueue] RETRY {item['retry_count']}/{MAX_RETRIES} "
                            f"in {delay}s: {item['notification_type']} | errors: {errors}"
                        )
                        await asyncio.sleep(delay)
                        await _delivery_queue.put(item)
                    else:
                        print(
                            f"[DeliveryQueue] FAILED (final): {item['notification_type']} -> "
                            f"{item['recipient_email']} | channels: {channels} | errors: {errors}"
                        )

                except Exception as e:
                    print(f"[DeliveryQueue] EXCEPTION: {e}")
                    traceback.print_exc()

                    # Retry on exception
                    if item["retry_count"] < MAX_RETRIES:
                        item["retry_count"] += 1
                        delay = RETRY_DELAYS[min(item["retry_count"] - 1, len(RETRY_DELAYS) - 1)]
                        await asyncio.sleep(delay)
                        await _delivery_queue.put(item)

            _delivery_queue.task_done()

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[DeliveryQueue] Worker error: {e}")
            await asyncio.sleep(1)

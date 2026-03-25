"""
WebSocket connection manager for real-time push events.

Manages per-organization connection pools and broadcasts events to all
connected clients in an org.

When Redis is available, broadcast() dual-writes:
  1. Local WebSocket push (immediate, in-process)
  2. Redis Stream XADD (durable, cross-worker)

A separate relay consumer (ws_relay.py) reads from the Redis Stream and
pushes events from *other* workers to local WebSocket connections.

Event types broadcasted:
  - sync_complete        (after Jira/ADO/GitHub sync finishes)
  - work_item_updated    (field change written back or synced)
  - sprint_updated       (iteration data changed)
  - standup_generated    (new standup report created)
  - health_signal        (new health signal detected)
  - writeback_success    (write-back completed)
  - writeback_undo       (write-back undone)
  - notification         (new in-app notification)

Usage:
    from ..services.ws_manager import ws_manager

    # In a router, after completing an action:
    await ws_manager.broadcast(org_id, {
        "type": "sync_complete",
        "data": {"tool": "ado", "items_synced": 42},
    })
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections grouped by organization_id.

    Each connected client is stored as (websocket, user_id) so we can
    optionally target messages or filter by user.
    """

    def __init__(self) -> None:
        # org_id -> list of (websocket, user_id)
        self._connections: dict[str, list[tuple[WebSocket, str]]] = {}
        self._lock = asyncio.Lock()
        # Unique worker ID for cross-worker deduplication
        self.worker_id: str = f"{os.getpid()}-{uuid4().hex[:8]}"

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, ws: WebSocket, org_id: str, user_id: str) -> None:
        """Accept a WebSocket and register it under the org."""
        await ws.accept()
        async with self._lock:
            if org_id not in self._connections:
                self._connections[org_id] = []
            self._connections[org_id].append((ws, user_id))
        logger.info(
            "[WS] Connected: user=%s org=%s (total=%d)",
            user_id, org_id, len(self._connections[org_id]),
        )

    async def disconnect(self, ws: WebSocket, org_id: str, user_id: str) -> None:
        """Remove a WebSocket from the org pool."""
        async with self._lock:
            conns = self._connections.get(org_id, [])
            self._connections[org_id] = [
                (w, u) for w, u in conns if w is not ws
            ]
            if not self._connections[org_id]:
                del self._connections[org_id]
        logger.info("[WS] Disconnected: user=%s org=%s", user_id, org_id)

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def broadcast(self, org_id: str, event: dict[str, Any]) -> None:
        """
        Send an event to ALL connected clients in the organization.

        Dual-write:
          1. Push to local WebSocket connections immediately.
          2. Publish to Redis Stream for cross-worker relay (fire-and-forget).

        Event format:
        {
            "type": "sync_complete",
            "data": { ... },
            "ts": "2026-02-24T12:00:00Z"
        }
        """
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())

        # 1. Local push (existing behavior — always happens first)
        await self._local_broadcast(org_id, event)

        # 2. Publish to Redis Stream (non-blocking, graceful on failure)
        try:
            from .event_bus import publish
            await publish(org_id, event, origin_worker=self.worker_id)
        except Exception:
            pass  # Redis unavailable — local broadcast already happened

    async def _local_broadcast(self, org_id: str, event: dict[str, Any]) -> None:
        """
        Push event to all WebSocket connections in this process for the org.

        This is the original broadcast logic, now extracted so the Redis
        relay consumer can also call it for cross-worker events.
        """
        message = json.dumps(event) if isinstance(event, dict) else event

        conns = self._connections.get(org_id, [])
        if not conns:
            return

        dead: list[tuple[WebSocket, str]] = []

        for ws, user_id in conns:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append((ws, user_id))

        # Prune dead connections
        if dead:
            async with self._lock:
                current = self._connections.get(org_id, [])
                self._connections[org_id] = [
                    (w, u) for w, u in current if (w, u) not in dead
                ]
                if not self._connections[org_id]:
                    del self._connections[org_id]
            logger.info(
                "[WS] Pruned %d dead connections for org=%s", len(dead), org_id,
            )

    async def send_to_user(
        self, org_id: str, user_id: str, event: dict[str, Any]
    ) -> None:
        """Send an event to a specific user within the org."""
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        message = json.dumps(event)

        conns = self._connections.get(org_id, [])
        for ws, uid in conns:
            if uid == user_id:
                try:
                    await ws.send_text(message)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def connection_count(self, org_id: str | None = None) -> int:
        """Return the number of active connections."""
        if org_id:
            return len(self._connections.get(org_id, []))
        return sum(len(v) for v in self._connections.values())

    def stats(self) -> dict:
        """Return connection stats for monitoring."""
        return {
            "total_connections": self.connection_count(),
            "organizations": {
                org_id: len(conns)
                for org_id, conns in self._connections.items()
            },
        }


# Singleton instance — imported by routers and services
ws_manager = ConnectionManager()

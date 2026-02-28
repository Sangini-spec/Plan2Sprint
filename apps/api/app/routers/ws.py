"""
WebSocket endpoint — /api/ws

Clients connect with a JWT token as a query parameter:
    ws://localhost:8000/api/ws?token=<jwt>

On connection, the server authenticates, joins the user to their org room,
and pushes real-time events. Clients can also send messages (e.g., ping).

The connection automatically sends a heartbeat every 30 seconds to keep
proxies and load balancers from closing idle connections.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import jwt, JWTError

from ..config import settings
from ..services.ws_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()

HEARTBEAT_INTERVAL = 30  # seconds


def _authenticate_ws(token: str | None) -> dict | None:
    """Validate JWT and return user claims, or None on failure."""
    # Demo / debug mode: allow connection without token
    if settings.is_demo_mode or (settings.debug and not token):
        return {
            "sub": "demo-user-1",
            "email": "demo@plan2sprint.app",
            "organization_id": "demo-org",
        }

    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        if "organization_id" not in payload:
            payload["organization_id"] = "demo-org"
        return payload
    except JWTError:
        return None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(None),
):
    """
    Main WebSocket endpoint.

    Protocol:
      1. Client connects with ?token=JWT
      2. Server authenticates, sends {"type":"connected"} on success
      3. Server pushes events as they happen
      4. Server sends {"type":"heartbeat"} every 30s
      5. Client can send {"type":"ping"} — server replies {"type":"pong"}
    """
    # Authenticate
    user = _authenticate_ws(token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    org_id = user.get("organization_id", "demo-org")
    user_id = user.get("sub", user.get("id", "unknown"))

    # Register connection
    await ws_manager.connect(websocket, org_id, user_id)

    # Send connected confirmation
    try:
        await websocket.send_text(json.dumps({
            "type": "connected",
            "data": {
                "userId": user_id,
                "orgId": org_id,
                "message": "Real-time connection established",
            },
        }))
    except Exception:
        await ws_manager.disconnect(websocket, org_id, user_id)
        return

    # Start heartbeat task
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(websocket, org_id, user_id)
    )

    try:
        # Listen for client messages
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif msg_type == "subscribe":
                # Future: subscribe to specific channels
                await websocket.send_text(json.dumps({
                    "type": "subscribed",
                    "data": {"channel": msg.get("channel", "all")},
                }))
            else:
                # Echo unknown types for debugging
                logger.debug("[WS] Unknown message type: %s", msg_type)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("[WS] Connection error: %s", e)
    finally:
        heartbeat_task.cancel()
        await ws_manager.disconnect(websocket, org_id, user_id)


async def _heartbeat_loop(ws: WebSocket, org_id: str, user_id: str) -> None:
    """Send periodic heartbeats to keep the connection alive."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await ws.send_text(json.dumps({"type": "heartbeat"}))
            except Exception:
                break
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# REST endpoint for stats (for admin/debugging)
# ---------------------------------------------------------------------------

@router.get("/ws/stats")
async def ws_stats():
    """Return WebSocket connection statistics."""
    return ws_manager.stats()

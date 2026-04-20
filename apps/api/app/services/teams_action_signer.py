"""
HMAC-signed URL helper for Teams Adaptive Card actions.

Teams doesn't support interactive bot-free buttons, so we use Action.OpenUrl
with a signed URL. The URL hits our backend, which verifies the signature,
performs the action (escalate/resolve), and shows a confirmation page.

URL format:
  {base}/api/integrations/teams/blocker-action?blocker_id=...&action=...&org_id=...&t=...&sig=...
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

from ..config import settings


# Max lifetime of a signed URL (days). After this the signature is rejected
# even if valid — prevents stale Teams messages from triggering actions.
MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _secret() -> bytes:
    """The signing secret — reuse the existing integration encryption key."""
    key = settings.integration_encryption_key or "plan2sprint-fallback-dev-secret"
    return key.encode("utf-8")


def _canonical(blocker_id: str, action: str, org_id: str, t: str) -> bytes:
    return f"{blocker_id}|{action}|{org_id}|{t}".encode("utf-8")


def sign(blocker_id: str, action: str, org_id: str, t: str) -> str:
    """Return the HMAC-SHA256 signature (hex) for the given parameters."""
    mac = hmac.new(_secret(), _canonical(blocker_id, action, org_id, t), hashlib.sha256)
    return mac.hexdigest()


def verify(blocker_id: str, action: str, org_id: str, t: str, sig: str) -> bool:
    """Constant-time verify. Also rejects if the timestamp is too old."""
    try:
        ts = int(t)
    except (ValueError, TypeError):
        return False
    if time.time() - ts > MAX_AGE_SECONDS:
        return False
    expected = sign(blocker_id, action, org_id, t)
    return hmac.compare_digest(expected, sig or "")


def build_signed_action_url(blocker_id: str, action: str, org_id: str) -> str:
    """Build a signed URL suitable for use in a Teams Action.OpenUrl button."""
    base = settings.frontend_url.rstrip("/") if settings.frontend_url else ""
    # Route through the API (not the Next.js proxy) since we want the backend
    # to handle it directly without Supabase auth.
    api_base = (settings.teams_redirect_uri or "").rsplit("/api/", 1)[0] if settings.teams_redirect_uri else base
    if not api_base:
        api_base = base
    t = str(int(time.time()))
    sig = sign(blocker_id, action, org_id, t)
    params = urlencode({
        "blocker_id": blocker_id,
        "action": action,
        "org_id": org_id,
        "t": t,
        "sig": sig,
    })
    return f"{api_base}/api/integrations/teams/blocker-action?{params}"

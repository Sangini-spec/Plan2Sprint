"""
Shared helpers for verifying inbound webhook signatures.

Each upstream provider uses a different convention. We centralise the
constant-time-compare logic here so:

    - Jira  (X-Atlassian-Webhook-Signature)  -> HMAC-SHA256 of raw body
    - ADO   (X-Hook-Secret)                  -> shared-secret token compare
    - Teams (clientState in body)            -> shared-secret token compare
    - GitHub                                 -> already implemented in github.py
                                                (kept there for symmetry with
                                                its per-connection webhook_secret
                                                stored on ToolConnection)

All comparisons go through ``hmac.compare_digest`` so we never leak timing
information about how many leading characters matched.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def verify_hmac_sha256(
    body: bytes,
    signature_header: Optional[str],
    secret: str,
    *,
    prefix: str = "",
) -> bool:
    """Constant-time HMAC-SHA256 verify of a raw request body.

    Args:
        body: raw request bytes (must be the exact bytes the sender signed —
              don't decode, re-encode, or re-serialise JSON).
        signature_header: value of the provider's signature header. May be
              ``None``/empty.
        secret: shared secret used to sign.
        prefix: optional literal prefix the provider includes (e.g. GitHub
              uses ``"sha256="``, Atlassian sometimes prepends a version tag).

    Returns ``True`` only when the signature matches. Returns ``False`` for
    any malformed input — callers should then return 401/403.
    """
    if not signature_header or not secret:
        return False

    try:
        expected_hex = hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
    except Exception:
        logger.exception("HMAC computation failed")
        return False

    expected = f"{prefix}{expected_hex}"
    # ``compare_digest`` requires both args to be the same type; encode to
    # bytes so heterogeneous str/bytes inputs don't false-fail.
    try:
        return hmac.compare_digest(
            expected.encode("utf-8"), signature_header.encode("utf-8")
        )
    except Exception:
        return False


def verify_shared_secret(provided: Optional[str], expected: str) -> bool:
    """Constant-time compare of a plain shared-secret token.

    Used for headers / payload fields that ARE the secret (rather than
    a signature derived from the secret). ADO's ``X-Hook-Secret`` and
    Microsoft Graph's ``clientState`` notification field both fall in
    this category.
    """
    if not provided or not expected:
        return False
    try:
        return hmac.compare_digest(
            provided.encode("utf-8"), expected.encode("utf-8")
        )
    except Exception:
        return False


def is_strict_mode_enabled() -> bool:
    """Honour the same env flag GitHub already uses, so all webhooks
    flip together when an operator turns on strict verification."""
    import os
    return os.environ.get(
        "STRICT_WEBHOOK_VERIFICATION", "false"
    ).strip().lower() in ("true", "1", "yes", "on")

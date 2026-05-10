"""
AES-256-GCM token encryption/decryption.
Port of apps/web/src/lib/integrations/encryption.ts

Wire format: iv_b64:ciphertext_b64:tag_b64
Compatible with the TypeScript version — tokens encrypted by one can be decrypted by the other.
"""

import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from ..config import settings


def encrypt_token(token: str) -> str:
    """Encrypt a token using AES-256-GCM. Falls back to base64 in demo mode."""
    if settings.is_demo_mode or not settings.integration_encryption_key:
        return base64.b64encode(token.encode()).decode()

    key = bytes.fromhex(settings.integration_encryption_key)
    iv = os.urandom(12)  # 96-bit IV for GCM
    aesgcm = AESGCM(key)
    ciphertext_with_tag = aesgcm.encrypt(iv, token.encode(), None)

    # GCM appends 16-byte auth tag to ciphertext
    ciphertext = ciphertext_with_tag[:-16]
    tag = ciphertext_with_tag[-16:]

    iv_b64 = base64.b64encode(iv).decode()
    ct_b64 = base64.b64encode(ciphertext).decode()
    tag_b64 = base64.b64encode(tag).decode()

    return f"{iv_b64}:{ct_b64}:{tag_b64}"


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a token encrypted with encrypt_token()."""
    if settings.is_demo_mode or not settings.integration_encryption_key:
        return base64.b64decode(encrypted_token).decode()

    parts = encrypted_token.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid encrypted token format — expected iv:ciphertext:tag")

    iv = base64.b64decode(parts[0])
    ciphertext = base64.b64decode(parts[1])
    tag = base64.b64decode(parts[2])

    key = bytes.fromhex(settings.integration_encryption_key)
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)

    return plaintext.decode()


# Hotfix 57 — token-format detection helpers
#
# Plan2Sprint accumulated three storage shapes for OAuth/PAT tokens
# over time:
#   1. Modern AES-GCM ciphertext: ``iv_b64:ciphertext_b64:tag_b64`` —
#      written by the current encrypt_token().
#   2. Demo-mode base64: a single base64 blob (no colons).
#   3. Plaintext: the raw provider value (``gho_...``, ``ghp_...``,
#      ``github_pat_...``, raw access tokens from before encryption was
#      added). Found in production for several connections during the
#      schema-drift audit.
#
# All read paths must tolerate (3) so existing data isn't broken.
# These helpers centralise that.

_RAW_TOKEN_PREFIXES = ("gho_", "ghp_", "ghu_", "ghs_", "github_pat_")


def _looks_plaintext(token: str) -> bool:
    """Heuristic: does this string look like an unencrypted provider token?"""
    if not token:
        return True
    if token.startswith(_RAW_TOKEN_PREFIXES):
        return True
    # AES-GCM ciphertext always has exactly two colons (iv:ct:tag).
    # Anything else is definitely not our ciphertext.
    if token.count(":") != 2:
        return True
    return False


def decrypt_token_safe(token: str) -> str:
    """Read-side wrapper: decrypt ciphertext, return plaintext as-is.

    Use this everywhere a stored token is read. Never raises on legacy
    plaintext rows. If decryption fails on a value that LOOKS like
    ciphertext, we still return the raw value rather than crashing —
    the upstream HTTP call will then fail with a clear 401 from the
    provider, which is more debuggable than a Python KeyError.
    """
    if not token:
        return ""
    if _looks_plaintext(token):
        return token
    try:
        return decrypt_token(token)
    except Exception:
        return token


def ensure_encrypted(token: str) -> str:
    """Write-side wrapper: idempotently return the AES-GCM ciphertext.

    If ``token`` looks plaintext, encrypt and return ciphertext. If it
    already looks like ciphertext (iv:ct:tag) we return it unchanged so
    re-saving an already-encrypted row doesn't double-encrypt.
    """
    if not token:
        return ""
    if _looks_plaintext(token):
        return encrypt_token(token)
    return token

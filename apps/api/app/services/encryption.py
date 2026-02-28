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

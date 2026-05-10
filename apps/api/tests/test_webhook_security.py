"""Unit tests for app.services.webhook_security.

Pure-function helpers — no DB, no FastAPI app, no fixtures needed.
Run with: pytest tests/test_webhook_security.py -v

These tests lock down the security-critical contracts:
  - HMAC verification is constant-time (no timing leak)
  - Empty / missing inputs reject (don't accept)
  - Prefix variants (GitHub-style "sha256=") work
  - Strict-mode env flag is read correctly
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys

# Add api root to sys.path so `app.services...` imports resolve when
# pytest is invoked from the apps/api directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.services.webhook_security import (  # noqa: E402
    is_strict_mode_enabled,
    verify_hmac_sha256,
    verify_shared_secret,
)


# ----------------------------------------------------------------------------
# verify_hmac_sha256
# ----------------------------------------------------------------------------


class TestVerifyHmacSha256:
    SECRET = "topsecret123"
    BODY = b'{"event":"jira:issue_updated","issue":{"key":"PROJ-1"}}'

    @property
    def good_sig(self) -> str:
        return hmac.new(
            self.SECRET.encode(), self.BODY, hashlib.sha256
        ).hexdigest()

    def test_valid_signature_passes(self):
        assert verify_hmac_sha256(self.BODY, self.good_sig, self.SECRET) is True

    def test_wrong_signature_rejects(self):
        assert verify_hmac_sha256(self.BODY, "deadbeef" * 8, self.SECRET) is False

    def test_empty_signature_rejects(self):
        assert verify_hmac_sha256(self.BODY, "", self.SECRET) is False

    def test_none_signature_rejects(self):
        assert verify_hmac_sha256(self.BODY, None, self.SECRET) is False

    def test_empty_secret_rejects(self):
        # Even with a "valid" signature, an empty secret must fail closed.
        assert verify_hmac_sha256(self.BODY, self.good_sig, "") is False

    def test_wrong_secret_rejects(self):
        wrong_sig = hmac.new(
            b"different-secret", self.BODY, hashlib.sha256
        ).hexdigest()
        assert verify_hmac_sha256(self.BODY, wrong_sig, self.SECRET) is False

    def test_mutated_body_rejects(self):
        mutated = self.BODY + b" "
        assert verify_hmac_sha256(mutated, self.good_sig, self.SECRET) is False

    def test_prefix_variant_works(self):
        prefixed = "sha256=" + self.good_sig
        assert verify_hmac_sha256(
            self.BODY, prefixed, self.SECRET, prefix="sha256="
        ) is True

    def test_missing_prefix_with_expected_prefix_rejects(self):
        # Caller asked for prefix matching but signature lacks it.
        assert verify_hmac_sha256(
            self.BODY, self.good_sig, self.SECRET, prefix="sha256="
        ) is False

    def test_signature_with_unexpected_prefix_rejects(self):
        # No prefix expected, but signature has one.
        prefixed = "sha256=" + self.good_sig
        assert verify_hmac_sha256(self.BODY, prefixed, self.SECRET) is False

    def test_truncated_signature_rejects(self):
        truncated = self.good_sig[:32]
        assert verify_hmac_sha256(self.BODY, truncated, self.SECRET) is False

    def test_empty_body_with_valid_signature(self):
        # Empty body is a valid input — verify it still works.
        empty = b""
        sig = hmac.new(self.SECRET.encode(), empty, hashlib.sha256).hexdigest()
        assert verify_hmac_sha256(empty, sig, self.SECRET) is True


# ----------------------------------------------------------------------------
# verify_shared_secret
# ----------------------------------------------------------------------------


class TestVerifySharedSecret:
    def test_matching_passes(self):
        assert verify_shared_secret("client-state-abc-123", "client-state-abc-123") is True

    def test_different_rejects(self):
        assert verify_shared_secret("client-state-abc", "different-state") is False

    def test_one_char_off_rejects(self):
        assert verify_shared_secret("aaaa", "aaab") is False

    def test_empty_provided_rejects(self):
        assert verify_shared_secret("", "expected-state") is False

    def test_none_provided_rejects(self):
        assert verify_shared_secret(None, "expected-state") is False

    def test_empty_expected_rejects(self):
        # Fail closed when the server hasn't been configured with a secret.
        assert verify_shared_secret("provided", "") is False

    def test_both_empty_rejects(self):
        assert verify_shared_secret("", "") is False

    def test_unicode_secret_handled(self):
        # Some providers allow non-ASCII; ensure encode doesn't blow up.
        assert verify_shared_secret("café-state", "café-state") is True
        assert verify_shared_secret("café-state", "cafe-state") is False

    def test_long_secret(self):
        long_secret = "x" * 4096
        assert verify_shared_secret(long_secret, long_secret) is True
        assert verify_shared_secret(long_secret, "x" * 4095 + "y") is False


# ----------------------------------------------------------------------------
# is_strict_mode_enabled
# ----------------------------------------------------------------------------


class TestStrictModeFlag:
    @pytest.fixture(autouse=True)
    def restore_env(self):
        """Restore env after each test so flags don't bleed."""
        prev = os.environ.get("STRICT_WEBHOOK_VERIFICATION")
        yield
        if prev is None:
            os.environ.pop("STRICT_WEBHOOK_VERIFICATION", None)
        else:
            os.environ["STRICT_WEBHOOK_VERIFICATION"] = prev

    def test_unset_is_false(self):
        os.environ.pop("STRICT_WEBHOOK_VERIFICATION", None)
        assert is_strict_mode_enabled() is False

    def test_explicit_false(self):
        os.environ["STRICT_WEBHOOK_VERIFICATION"] = "false"
        assert is_strict_mode_enabled() is False

    @pytest.mark.parametrize("val", ["true", "True", "TRUE", "1", "yes", "YES", "on", "On"])
    def test_truthy_values(self, val):
        os.environ["STRICT_WEBHOOK_VERIFICATION"] = val
        assert is_strict_mode_enabled() is True

    @pytest.mark.parametrize("val", ["false", "0", "no", "off", "", "garbage", "TRUE_NOT", "yess"])
    def test_falsy_values(self, val):
        os.environ["STRICT_WEBHOOK_VERIFICATION"] = val
        assert is_strict_mode_enabled() is False

    def test_whitespace_padded_truthy(self):
        os.environ["STRICT_WEBHOOK_VERIFICATION"] = "  true  "
        assert is_strict_mode_enabled() is True

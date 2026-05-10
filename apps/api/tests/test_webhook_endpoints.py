"""Integration tests for the inbound webhook endpoints.

These exist to catch *wiring* regressions: if the helpers in
``webhook_security.py`` are correct (covered by ``test_webhook_security.py``)
but the router code in jira.py / ado.py / teams.py imports them wrong or
checks the wrong header, signatures could silently pass without these
tests catching it.

Each test patches ``settings`` to simulate different security postures
(secret configured / not configured, strict mode on / off) and asserts
the endpoint's HTTP response code.

No DB is touched — webhook endpoints don't read any tables before
signature verification, so we don't need the conftest.py fixtures.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys

# Set env vars BEFORE app import so config picks them up.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5433/p2s_test",
)
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-not-real")
os.environ.setdefault("DEMO_MODE", "false")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.config import settings  # noqa: E402


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def restore_settings():
    """Snapshot + restore the security-related settings around each test."""
    saved = {
        "jira_webhook_secret": settings.jira_webhook_secret,
        "ado_webhook_secret": settings.ado_webhook_secret,
        "teams_webhook_client_state": settings.teams_webhook_client_state,
        "strict_webhook_verification": settings.strict_webhook_verification,
    }
    saved_env = os.environ.get("STRICT_WEBHOOK_VERIFICATION")
    yield
    for k, v in saved.items():
        setattr(settings, k, v)
    if saved_env is None:
        os.environ.pop("STRICT_WEBHOOK_VERIFICATION", None)
    else:
        os.environ["STRICT_WEBHOOK_VERIFICATION"] = saved_env


# ----------------------------------------------------------------------------
# Jira webhook — HMAC-SHA256
# ----------------------------------------------------------------------------


class TestJiraWebhook:
    URL = "/api/integrations/jira/webhooks"
    SECRET = "jira-test-secret-abc123"
    PAYLOAD = {"webhookEvent": "jira:issue_updated", "issue": {"key": "P-1"}}

    def _body_and_sig(self):
        body = json.dumps(self.PAYLOAD).encode("utf-8")
        sig = hmac.new(self.SECRET.encode(), body, hashlib.sha256).hexdigest()
        return body, sig

    def test_valid_signature_accepted(self, client, restore_settings):
        settings.jira_webhook_secret = self.SECRET
        body, sig = self._body_and_sig()
        res = client.post(
            self.URL,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Atlassian-Webhook-Signature": sig,
            },
        )
        assert res.status_code == 200
        assert res.json()["received"] is True

    def test_invalid_signature_rejected(self, client, restore_settings):
        settings.jira_webhook_secret = self.SECRET
        body, _ = self._body_and_sig()
        res = client.post(
            self.URL,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Atlassian-Webhook-Signature": "deadbeef" * 8,
            },
        )
        assert res.status_code == 401

    def test_missing_signature_rejected_when_secret_set(self, client, restore_settings):
        settings.jira_webhook_secret = self.SECRET
        body, _ = self._body_and_sig()
        res = client.post(
            self.URL,
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 401

    def test_no_secret_strict_mode_rejects(self, client, restore_settings):
        settings.jira_webhook_secret = ""
        settings.strict_webhook_verification = True
        body, _ = self._body_and_sig()
        res = client.post(
            self.URL, content=body, headers={"Content-Type": "application/json"}
        )
        assert res.status_code == 401

    def test_no_secret_lax_mode_accepts(self, client, restore_settings):
        settings.jira_webhook_secret = ""
        settings.strict_webhook_verification = False
        os.environ.pop("STRICT_WEBHOOK_VERIFICATION", None)
        body, _ = self._body_and_sig()
        res = client.post(
            self.URL, content=body, headers={"Content-Type": "application/json"}
        )
        # Backwards-compat: pre-hardening behaviour preserved.
        assert res.status_code == 200

    def test_signature_mismatch_returns_401_not_500(self, client, restore_settings):
        """Regression: the pre-hardening code wrapped the verify check
        in a broad try/except that turned 403 into 500. Lock that
        bug-fix in."""
        settings.jira_webhook_secret = self.SECRET
        body, _ = self._body_and_sig()
        res = client.post(
            self.URL,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Atlassian-Webhook-Signature": "wrong-sig",
            },
        )
        assert res.status_code == 401, (
            f"Expected 401 (Invalid signature) but got {res.status_code} "
            f"({res.text}). The signature check may have been swallowed by "
            f"a broad try/except again."
        )


# ----------------------------------------------------------------------------
# ADO webhook — shared-secret X-Hook-Secret (constant-time compare)
# ----------------------------------------------------------------------------


class TestAdoWebhook:
    URL = "/api/integrations/ado/webhooks"
    SECRET = "ado-test-secret-xyz789"
    PAYLOAD = {"eventType": "workitem.updated", "id": "evt-1"}

    def test_valid_secret_accepted(self, client, restore_settings):
        settings.ado_webhook_secret = self.SECRET
        res = client.post(
            self.URL, json=self.PAYLOAD, headers={"X-Hook-Secret": self.SECRET}
        )
        assert res.status_code == 200
        assert res.json()["received"] is True

    def test_wrong_secret_rejected(self, client, restore_settings):
        settings.ado_webhook_secret = self.SECRET
        res = client.post(
            self.URL,
            json=self.PAYLOAD,
            headers={"X-Hook-Secret": "wrong-secret"},
        )
        assert res.status_code == 401

    def test_missing_header_rejected_when_secret_set(self, client, restore_settings):
        settings.ado_webhook_secret = self.SECRET
        res = client.post(self.URL, json=self.PAYLOAD)
        assert res.status_code == 401

    def test_no_secret_strict_mode_rejects(self, client, restore_settings):
        settings.ado_webhook_secret = ""
        settings.strict_webhook_verification = True
        res = client.post(self.URL, json=self.PAYLOAD)
        assert res.status_code == 401

    def test_no_secret_lax_mode_accepts(self, client, restore_settings):
        settings.ado_webhook_secret = ""
        settings.strict_webhook_verification = False
        os.environ.pop("STRICT_WEBHOOK_VERIFICATION", None)
        res = client.post(self.URL, json=self.PAYLOAD)
        assert res.status_code == 200

    def test_partial_match_rejected(self, client, restore_settings):
        """Constant-time compare must reject prefix matches — the old
        ``!=`` check would also reject these but leak timing info."""
        settings.ado_webhook_secret = self.SECRET
        res = client.post(
            self.URL,
            json=self.PAYLOAD,
            headers={"X-Hook-Secret": self.SECRET[:-1]},
        )
        assert res.status_code == 401


# ----------------------------------------------------------------------------
# Teams webhook — Microsoft Graph clientState
# ----------------------------------------------------------------------------


class TestTeamsWebhook:
    URL = "/api/integrations/teams/webhook"
    STATE = "teams-client-state-deadbeef-cafe"

    def _payload(self, client_state: str | None) -> dict:
        n = {
            "subscriptionId": "sub-1",
            "changeType": "updated",
            "resource": "chats('1')/messages('2')",
        }
        if client_state is not None:
            n["clientState"] = client_state
        return {"value": [n]}

    def test_valid_clientstate_accepted(self, client, restore_settings):
        settings.teams_webhook_client_state = self.STATE
        res = client.post(self.URL, json=self._payload(self.STATE))
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_wrong_clientstate_rejected(self, client, restore_settings):
        settings.teams_webhook_client_state = self.STATE
        res = client.post(self.URL, json=self._payload("forged-state"))
        assert res.status_code == 401

    def test_missing_clientstate_rejected_when_configured(self, client, restore_settings):
        settings.teams_webhook_client_state = self.STATE
        res = client.post(self.URL, json=self._payload(None))
        assert res.status_code == 401

    def test_one_bad_among_many_rejects_all(self, client, restore_settings):
        """A batch is rejected wholesale even if only one notification's
        clientState is wrong — fail-closed for batch tampering."""
        settings.teams_webhook_client_state = self.STATE
        body = {
            "value": [
                {
                    "subscriptionId": "s1",
                    "changeType": "u",
                    "resource": "r1",
                    "clientState": self.STATE,
                },
                {
                    "subscriptionId": "s2",
                    "changeType": "u",
                    "resource": "r2",
                    "clientState": "tampered",
                },
            ]
        }
        res = client.post(self.URL, json=body)
        assert res.status_code == 401

    def test_validation_handshake_bypasses_secret(self, client, restore_settings):
        """Subscription validation must work even without a clientState
        configured — Microsoft uses it during subscription setup."""
        settings.teams_webhook_client_state = self.STATE
        res = client.post(
            self.URL + "?validationToken=abc-123-validation",
            json={},
        )
        assert res.status_code == 200
        assert res.text == "abc-123-validation"

    def test_no_state_strict_mode_rejects(self, client, restore_settings):
        settings.teams_webhook_client_state = ""
        settings.strict_webhook_verification = True
        res = client.post(self.URL, json=self._payload("any"))
        assert res.status_code == 401

    def test_no_state_lax_mode_accepts(self, client, restore_settings):
        settings.teams_webhook_client_state = ""
        settings.strict_webhook_verification = False
        os.environ.pop("STRICT_WEBHOOK_VERIFICATION", None)
        res = client.post(self.URL, json=self._payload(None))
        assert res.status_code == 200

    def test_invalid_json_rejected(self, client, restore_settings):
        settings.teams_webhook_client_state = self.STATE
        res = client.post(
            self.URL,
            content=b"not-json{",
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 400

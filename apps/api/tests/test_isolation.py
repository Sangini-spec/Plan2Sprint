"""
Isolation + RBAC test suite.

Each test pins a specific CRIT (or HIGH) finding from the security audit
as a regression-proof assertion. If a future refactor reintroduces a
bug, the corresponding test fails. The expected behaviour is:

  - All tests should PASS against the codebase post-Hotfix 51.
  - Removing any of the Hotfix 51 fixes should make the corresponding
    test FAIL.

Run with::

    docker compose -f docker-compose.test.yml up -d
    cd apps/api
    DATABASE_URL=postgresql+asyncpg://test:test@localhost:5433/p2s_test \
        alembic upgrade head
    DATABASE_URL=postgresql+asyncpg://test:test@localhost:5433/p2s_test \
        python scripts/seed_test_data.py
    DATABASE_URL=postgresql+asyncpg://test:test@localhost:5433/p2s_test \
        pytest tests/ -v
"""
from __future__ import annotations

from tests.conftest import fake_user


# -----------------------------------------------------------------------------
# CRIT-1 — stakeholder my-projects no longer accepts an `email=` query param
# -----------------------------------------------------------------------------

class TestCrit1StakeholderEmailLeak:
    def test_my_projects_ignores_email_query_param(self, app_with_user):
        """An attacker can't pass ?email=victim@target.com and exfiltrate
        another email's project assignments."""
        client = app_with_user(fake_user("acme", "stakeholder"))
        # Try to leak Wayne's stakeholder assignments by passing their email.
        resp = client.get(
            "/api/projects/stakeholder-assignments/my-projects",
            params={"email": "stake@wayne.test"},
        )
        # Endpoint should reply with the caller's OWN projects only (or empty).
        # Either way, the response must NOT contain Wayne's project name.
        assert resp.status_code == 200
        body = resp.json()
        names = [p.get("name", "") for p in body.get("projects", [])]
        assert not any("Wayne" in n for n in names), (
            f"CRIT-1 regression: Wayne's project leaked via ?email= param. "
            f"Got project names: {names}"
        )


# -----------------------------------------------------------------------------
# CRIT-2 — sprint mutations require PO/admin role
# -----------------------------------------------------------------------------

class TestCrit2SprintMutationsRoleGated:
    def test_stakeholder_cannot_generate_sprint(self, app_with_user):
        client = app_with_user(fake_user("acme", "stakeholder"))
        resp = client.post("/api/sprints", json={"projectId": "x"})
        assert resp.status_code == 403, (
            f"CRIT-2 regression: stakeholder hit POST /api/sprints "
            f"without 403. Status: {resp.status_code}, Body: {resp.text[:200]}"
        )

    def test_developer_cannot_generate_sprint(self, app_with_user):
        client = app_with_user(fake_user("acme", "developer"))
        resp = client.post("/api/sprints", json={"projectId": "x"})
        assert resp.status_code == 403

    def test_stakeholder_cannot_approve_sprint_plan(self, app_with_user):
        client = app_with_user(fake_user("acme", "stakeholder"))
        resp = client.patch("/api/sprints", json={"planId": "x", "status": "APPROVED"})
        assert resp.status_code == 403

    def test_stakeholder_cannot_complete_sprint(self, app_with_user):
        client = app_with_user(fake_user("acme", "stakeholder"))
        resp = client.post("/api/sprints/complete", json={"projectId": "x"})
        assert resp.status_code == 403

    def test_stakeholder_cannot_trigger_rebalance(self, app_with_user):
        client = app_with_user(fake_user("acme", "stakeholder"))
        resp = client.post("/api/sprints/rebalance", json={"planId": "x"})
        assert resp.status_code == 403

    def test_stakeholder_cannot_approve_rebalance(self, app_with_user):
        client = app_with_user(fake_user("acme", "stakeholder"))
        resp = client.post(
            "/api/sprints/rebalance/approve",
            json={"proposalId": "x"},
        )
        assert resp.status_code == 403

    def test_developer_cannot_change_team_member_role(self, app_with_user):
        """CRIT-5 is also covered here — update_team_member_role is PO/admin only."""
        client = app_with_user(fake_user("acme", "developer"))
        resp = client.patch(
            "/api/sprints/team-member",
            json={"memberId": "m", "action": "exclude"},
        )
        assert resp.status_code == 403

    def test_po_can_generate_sprint(self, app_with_user):
        """Sanity: PO is NOT blocked by the role check (may fail for other
        reasons — missing project — but not 403 from role gating)."""
        client = app_with_user(fake_user("acme", "product_owner"))
        resp = client.post("/api/sprints", json={"projectId": "nonexistent"})
        # Anything except 403 is acceptable here. 400 / 404 / 500 from
        # downstream is fine; we're only checking the role gate.
        assert resp.status_code != 403


# -----------------------------------------------------------------------------
# CRIT-3 — standup note submission no longer falls back to a stranger TM
# -----------------------------------------------------------------------------

class TestCrit3StandupNoteFallback:
    def test_unmapped_email_cannot_submit_note(self, app_with_user):
        """A user whose email doesn't match any TeamMember in the org must
        not be able to silently submit a note attributed to someone else."""
        client = app_with_user(
            fake_user("acme", "developer", email="nobody@nowhere.test")
        )
        resp = client.post("/api/standups", json={"note": "hostile note"})
        assert resp.status_code == 403, (
            f"CRIT-3 regression: standup note from unmapped email accepted. "
            f"Status: {resp.status_code}, Body: {resp.text[:200]}"
        )


# -----------------------------------------------------------------------------
# CRIT-4 — flag_blocker validates that report_id belongs to caller's org
# -----------------------------------------------------------------------------

class TestCrit4FlagBlockerIDOR:
    def test_cannot_flag_blocker_on_unknown_report_id(self, app_with_user):
        client = app_with_user(fake_user("acme", "developer"))
        resp = client.post(
            "/api/standups/blocker",
            json={"description": "stuck", "reportId": "report_from_another_org_xxx"},
        )
        # Either 403 or 404 — both close the IDOR; 200 would mean the bug
        # is back.
        assert resp.status_code in (403, 404), (
            f"CRIT-4 regression: blocker accepted on a foreign reportId. "
            f"Status: {resp.status_code}, Body: {resp.text[:200]}"
        )


# -----------------------------------------------------------------------------
# CRIT-5 — covered by TestCrit2 (update_team_member_role role gate)
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# CRIT-6 — new-org signup role hardcoded to product_owner; cannot be
# self-elected via user_metadata. This one is exercised at JWT-decode time
# rather than at endpoint time, so a unit test of the helper is the right
# shape.
# -----------------------------------------------------------------------------

class TestCrit6SignupRoleNotSelfElectable:
    def test_role_default_does_not_consult_user_meta(self):
        """Open the supabase.py source and assert the literal hardcoded
        default. This is a string-based check rather than a runtime check
        because exercising the resolver requires real Supabase JWTs."""
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "auth", "supabase.py",
        )
        src = open(path, encoding="utf-8").read()
        # The vulnerable form was: role_from_signup = user_meta.get("role", ...)
        assert 'user_meta.get("role"' not in src, (
            "CRIT-6 regression: signup metadata is being consulted for "
            "role assignment again, allowing self-elected escalation."
        )
        # And the safe form is present:
        assert 'role_from_signup = "product_owner"' in src, (
            "CRIT-6 regression: hardcoded role_from_signup default missing."
        )


# -----------------------------------------------------------------------------
# Cross-tenant: an Acme stakeholder calling a Wayne-scoped endpoint must
# never receive Wayne data. (Sanity check on dashboard / projects endpoints.)
# -----------------------------------------------------------------------------

class TestCrossTenantIsolation:
    def test_acme_user_cannot_list_wayne_projects(self, app_with_user):
        """Listing /api/projects must filter to caller's org only."""
        client = app_with_user(fake_user("acme", "product_owner"))
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        body = resp.json()
        # Whatever shape comes back, no Wayne project names allowed.
        text = str(body).lower()
        assert "wayne" not in text, (
            f"Cross-tenant regression: Wayne data leaked into Acme PO's "
            f"/api/projects response. Body sample: {text[:500]}"
        )


# -----------------------------------------------------------------------------
# NEW-USER EMPTY-STATE GUARANTEES
#
# Pins the user's specific concern: "when someone signs up for the first
# time, NOTHING from any other tenant should be visible. Every panel
# should be empty / not-connected. The previous bug pattern was
# data from one org leaking into another org's first-login dashboard."
#
# These tests use the "fresh" org fixture which has:
#   - No ImportedProject rows
#   - No TeamMember rows for the user
#   - No ToolConnection rows (no Slack/Teams/Jira/ADO/GitHub connected)
#   - No StandupReport / WorkItem / Iteration / Sprint data
#
# Acme/Wayne/Stark exist in the same DB with full data — so any leak
# from those orgs into Fresh's response means we have a tenancy bug.
# -----------------------------------------------------------------------------

OTHER_ORG_NEEDLES = ["acme", "wayne", "stark"]


def _no_other_tenant_leak(body, msg_prefix: str) -> None:
    """Assert that the response body contains zero references to any
    other test org's name, slug, or project keys."""
    text = str(body).lower()
    for needle in OTHER_ORG_NEEDLES:
        assert needle not in text, (
            f"{msg_prefix} — '{needle}' found in fresh-user response. "
            f"Other tenant leaked. Sample: {text[:400]}"
        )


class TestNewUserNoLeak:
    """For each role of a brand-new tenant: no leakage, no data, just
    empty / not-connected responses."""

    @staticmethod
    def _all_fresh_users():
        return [
            ("po", fake_user("fresh", "product_owner")),
            ("dev", fake_user("fresh", "developer")),
            ("stk", fake_user("fresh", "stakeholder")),
            ("owner", fake_user("fresh", "owner")),
        ]

    # ── Integration status endpoints ──────────────────────────────────────
    # Fresh user must see "connected: false" for every integration. No
    # data from any other tenant should appear in the responses.

    def test_slack_status_not_connected(self, app_with_user):
        for label, user in self._all_fresh_users():
            client = app_with_user(user)
            resp = client.get("/api/integrations/slack/status")
            assert resp.status_code == 200, f"slack status [{label}]: {resp.status_code}"
            body = resp.json()
            assert body.get("connected") is False, f"slack status [{label}] not False: {body}"
            _no_other_tenant_leak(body, f"slack/status [{label}]")

    def test_teams_status_not_connected(self, app_with_user):
        for label, user in self._all_fresh_users():
            client = app_with_user(user)
            resp = client.get("/api/integrations/teams/status")
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("connected") is False, f"teams status [{label}]: {body}"
            _no_other_tenant_leak(body, f"teams/status [{label}]")

    def test_jira_status_not_connected(self, app_with_user):
        for label, user in self._all_fresh_users():
            client = app_with_user(user)
            resp = client.get("/api/integrations/jira/status")
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("connected") is False, f"jira status [{label}]: {body}"
            _no_other_tenant_leak(body, f"jira/status [{label}]")

    def test_ado_status_not_connected(self, app_with_user):
        for label, user in self._all_fresh_users():
            client = app_with_user(user)
            resp = client.get("/api/integrations/ado/status")
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("connected") is False, f"ado status [{label}]: {body}"
            _no_other_tenant_leak(body, f"ado/status [{label}]")

    def test_github_status_not_connected(self, app_with_user):
        for label, user in self._all_fresh_users():
            client = app_with_user(user)
            resp = client.get("/api/integrations/github/status")
            assert resp.status_code == 200
            body = resp.json()
            # Some implementations return {"connected": False, "repos": []};
            # the contract is just "no other tenant's data".
            _no_other_tenant_leak(body, f"github/status [{label}]")

    # ── Project / dashboard endpoints ────────────────────────────────────

    def test_projects_list_empty(self, app_with_user):
        for label, user in self._all_fresh_users():
            client = app_with_user(user)
            resp = client.get("/api/projects")
            assert resp.status_code == 200, f"projects [{label}]: {resp.status_code}"
            body = resp.json()
            projects = body.get("projects") if isinstance(body, dict) else body
            if projects is None:
                projects = []
            assert len(projects) == 0, (
                f"Fresh user [{label}] saw {len(projects)} projects: {projects}"
            )
            _no_other_tenant_leak(body, f"/api/projects [{label}]")

    def test_jira_projects_list_empty(self, app_with_user):
        """Even before connecting, /api/integrations/jira/projects must
        not expose other tenants' projects."""
        for label, user in self._all_fresh_users():
            client = app_with_user(user)
            resp = client.get("/api/integrations/jira/projects")
            # 200 with [] OR 4xx because not connected — both acceptable.
            # What's NOT acceptable is 200 with another tenant's data.
            if resp.status_code == 200:
                body = resp.json()
                _no_other_tenant_leak(body, f"jira/projects [{label}]")

    def test_ado_projects_list_empty(self, app_with_user):
        for label, user in self._all_fresh_users():
            client = app_with_user(user)
            resp = client.get("/api/integrations/ado/projects")
            if resp.status_code == 200:
                body = resp.json()
                _no_other_tenant_leak(body, f"ado/projects [{label}]")

    # ── Standup / sprint / dashboard data endpoints ──────────────────────

    def test_standups_empty(self, app_with_user):
        for label, user in self._all_fresh_users():
            client = app_with_user(user)
            resp = client.get("/api/standups")
            assert resp.status_code == 200, f"standups [{label}]: {resp.status_code}"
            body = resp.json()
            reports = body.get("individualReports", [])
            assert len(reports) == 0, (
                f"Fresh user [{label}] saw {len(reports)} standup reports"
            )
            _no_other_tenant_leak(body, f"/api/standups [{label}]")

    def test_github_overview_empty(self, app_with_user):
        for label, user in self._all_fresh_users():
            client = app_with_user(user)
            resp = client.get("/api/github/overview")
            # 200 with zeros, OR 4xx for not-connected. Either's fine.
            if resp.status_code == 200:
                body = resp.json()
                _no_other_tenant_leak(body, f"/api/github/overview [{label}]")
                # Counts should be zero
                if isinstance(body, dict):
                    for k in ("repos", "openPRs", "mergedPRs"):
                        v = body.get(k)
                        if isinstance(v, int):
                            assert v == 0, (
                                f"Fresh user [{label}] saw {k}={v} on github/overview"
                            )

    # ── Stakeholder-specific empty state ─────────────────────────────────

    def test_stakeholder_my_projects_empty(self, app_with_user):
        client = app_with_user(fake_user("fresh", "stakeholder"))
        resp = client.get("/api/projects/stakeholder-assignments/my-projects")
        assert resp.status_code == 200
        body = resp.json()
        projects = body.get("projects", [])
        assert len(projects) == 0, (
            f"Fresh stakeholder saw {len(projects)} assigned projects"
        )
        _no_other_tenant_leak(body, "stakeholder-assignments/my-projects")

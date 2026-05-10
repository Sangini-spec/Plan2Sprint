"""
Pytest fixtures for the isolation/RBAC test suite.

Approach: rather than minting real Supabase JWTs, we override the
``get_current_user`` FastAPI dependency in the test app so each test can
inject an arbitrary "current user" dict. This mirrors what the real
auth helper produces (organization_id, email, role, sub, etc.) and lets
us simulate a stakeholder, a developer, a PO of a different org, etc.
without ever touching Supabase.
"""
from __future__ import annotations

import os
import sys
import pytest

# Pin the test DB URL before app modules import. Same URL as
# scripts/seed_test_data.py expects.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5433/p2s_test",
)
# Disable demo bypass so endpoints exercise real auth.
os.environ.setdefault("DEMO_MODE", "false")
# Stub out external integrations so requests never hit Slack/Teams/Jira/ADO.
os.environ.setdefault("SLACK_SIGNING_SECRET", "test_signing_secret")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mirrors fixture catalogue in scripts/seed_test_data.py
TEST_ORGS = {
    "acme":  "org_acme_test_xxxxxxxxx"[:25],
    "wayne": "org_wayne_test_xxxxxxxxx"[:25],
    "stark": "org_stark_test_xxxxxxxxx"[:25],
    # Fresh org — no projects, no team_members, no integrations.
    # Used by TestNewUserNoLeak to verify empty tenant isolation.
    "fresh": "org_fresh_test_xxxxxxxxx"[:25],
}


def fake_user(org: str, role: str, email: str | None = None) -> dict:
    """Construct a current_user dict matching what get_current_user returns."""
    org_id = TEST_ORGS[org]
    eml = email or f"{role}@{org}.test"
    return {
        "sub": f"sub_{org}_{role}",
        "id": f"sub_{org}_{role}",
        "user_id": f"sub_{org}_{role}",
        "email": eml,
        "full_name": f"{org.title()} {role}",
        "role": role,
        "organization_id": org_id,
    }


@pytest.fixture
def app_with_user():
    """Returns a callable: `set_user(current_user_dict) -> TestClient`.

    Each call to set_user installs dependency overrides for both
    ``get_current_user`` (identity injection) and ``get_db`` (fresh
    NullPool engine).

    The NullPool override is critical: by default the FastAPI app uses
    a shared async ``engine`` whose pool retains connections across
    requests. Pytest closes the asyncio event loop between tests, which
    invalidates any connections still in the pool and causes flaky
    "Event loop is closed" / RuntimeError teardowns when the next test
    tries to reuse them. NullPool opens a fresh connection per request
    and closes it after, eliminating the shared state.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.pool import NullPool
    from app.main import app
    from app.auth.supabase import get_current_user
    from app.database import get_db

    test_engine = create_async_engine(
        os.environ["DATABASE_URL"],
        echo=False,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )

    async def _override_get_db():
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            yield s

    def _set(current_user: dict) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: current_user
        app.dependency_overrides[get_db] = _override_get_db
        return TestClient(app)

    yield _set

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)

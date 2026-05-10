"""
Seed deterministic test fixtures into a sandboxed Postgres for isolation
tests.

Creates THREE independent organizations with the full role pyramid in
each. Each user has a stable, predictable id + supabase_user_id so the
isolation tests can mint their own JWTs / bypass auth via dependency
override and run clean assertions.

DO NOT run this against the production database. It auto-checks that
DATABASE_URL points at port 5433 (the docker-compose.test.yml setup) to
prevent accidental misuse.

Usage::

    docker compose -f docker-compose.test.yml up -d
    cd apps/api
    DATABASE_URL=postgresql+asyncpg://test:test@localhost:5433/p2s_test \
        alembic upgrade head
    DATABASE_URL=postgresql+asyncpg://test:test@localhost:5433/p2s_test \
        python scripts/seed_test_data.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

# ----------------------------------------------------------------------------
# Safety guardrails
# ----------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)

# The test docker-compose binds Postgres to localhost:5433. If the URL
# doesn't include 5433, refuse to proceed — likely pointing at prod.
if ":5433/" not in DATABASE_URL and ":5433?" not in DATABASE_URL:
    print(
        f"ERROR: DATABASE_URL does NOT point at the test Postgres "
        f"(:5433). Refusing to run seed against unknown DB.\n"
        f"Got: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}\n"
        f"Expected something like:\n"
        f"  postgresql+asyncpg://test:test@localhost:5433/p2s_test",
        file=sys.stderr,
    )
    sys.exit(1)

# ----------------------------------------------------------------------------
# Fixture catalogue — three orgs, four roles each
# ----------------------------------------------------------------------------

FIXTURES = {
    "acme": {
        "org_id": "org_acme_test_xxxxxxxxx"[:25],
        "org_name": "Acme Corp",
        "org_slug": "acme-corp-test",
        "users": [
            ("u_acme_owner_xxxxxxxxxx"[:25], "owner@acme.test", "Acme Owner", "owner"),
            ("u_acme_po_xxxxxxxxxxxxx"[:25], "po@acme.test", "Acme PO", "product_owner"),
            ("u_acme_dev_xxxxxxxxxxxx"[:25], "dev@acme.test", "Acme Dev", "developer"),
            ("u_acme_stk_xxxxxxxxxxxx"[:25], "stake@acme.test", "Acme Stakeholder", "stakeholder"),
        ],
    },
    "wayne": {
        "org_id": "org_wayne_test_xxxxxxxxx"[:25],
        "org_name": "Wayne Industries",
        "org_slug": "wayne-industries-test",
        "users": [
            ("u_wayne_owner_xxxxxxxxx"[:25], "owner@wayne.test", "Wayne Owner", "owner"),
            ("u_wayne_po_xxxxxxxxxxxx"[:25], "po@wayne.test", "Wayne PO", "product_owner"),
            ("u_wayne_dev_xxxxxxxxxxx"[:25], "dev@wayne.test", "Wayne Dev", "developer"),
            ("u_wayne_stk_xxxxxxxxxxx"[:25], "stake@wayne.test", "Wayne Stakeholder", "stakeholder"),
        ],
    },
    "stark": {
        "org_id": "org_stark_test_xxxxxxxxx"[:25],
        "org_name": "Stark Labs",
        "org_slug": "stark-labs-test",
        "users": [
            ("u_stark_owner_xxxxxxxxx"[:25], "owner@stark.test", "Stark Owner", "owner"),
            ("u_stark_po_xxxxxxxxxxxx"[:25], "po@stark.test", "Stark PO", "product_owner"),
            ("u_stark_dev_xxxxxxxxxxx"[:25], "dev@stark.test", "Stark Dev", "developer"),
            ("u_stark_stk_xxxxxxxxxxx"[:25], "stake@stark.test", "Stark Stakeholder", "stakeholder"),
        ],
    },
    # FRESH org — used by TestNewUserNoLeak. The org row exists, the
    # users exist, but there are NO projects, NO TeamMember rows, NO
    # ToolConnections, NO standup data. Mimics a real brand-new
    # signup post-Hotfix-51 where Plan2Sprint auto-creates the org
    # record but nothing else has been imported yet.
    "fresh": {
        "org_id": "org_fresh_test_xxxxxxxxx"[:25],
        "org_name": "Fresh Co",
        "org_slug": "fresh-co-test",
        "users": [
            ("u_fresh_owner_xxxxxxxxx"[:25], "owner@fresh.test", "Fresh Owner", "owner"),
            ("u_fresh_po_xxxxxxxxxxxx"[:25], "po@fresh.test", "Fresh PO", "product_owner"),
            ("u_fresh_dev_xxxxxxxxxxx"[:25], "dev@fresh.test", "Fresh Dev", "developer"),
            ("u_fresh_stk_xxxxxxxxxxx"[:25], "stake@fresh.test", "Fresh Stakeholder", "stakeholder"),
        ],
        "no_resources": True,  # Skip ImportedProject + TeamMember inserts
    },
}


async def main() -> int:
    # Add the api app dir to sys.path so we can import models / database.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # NB: importing here (after sys.path setup) so models pick up the
    # right base.
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy import select
    from app.models.organization import Organization
    from app.models.user import User
    from app.models.team_member import TeamMember
    from app.models.imported_project import ImportedProject

    engine = create_async_engine(DATABASE_URL, echo=False)
    async with AsyncSession(engine) as session:
        # 1. Wipe any prior fixture rows (idempotent re-runs).
        for fix in FIXTURES.values():
            for (uid, _, _, _) in fix["users"]:
                await session.execute(
                    User.__table__.delete().where(User.id == uid)
                )
            await session.execute(
                TeamMember.__table__.delete().where(
                    TeamMember.organization_id == fix["org_id"]
                )
            )
            await session.execute(
                ImportedProject.__table__.delete().where(
                    ImportedProject.organization_id == fix["org_id"]
                )
            )
            await session.execute(
                Organization.__table__.delete().where(
                    Organization.id == fix["org_id"]
                )
            )
        await session.commit()

        # 2. Insert orgs.
        for fix in FIXTURES.values():
            session.add(Organization(
                id=fix["org_id"],
                name=fix["org_name"],
                slug=fix["org_slug"],
            ))
        await session.commit()

        # 3. Insert users (one per role per org). supabase_user_id mirrors
        # user.id so JWTs minted in tests can use either as `sub`.
        for fix in FIXTURES.values():
            for (uid, email, name, role) in fix["users"]:
                session.add(User(
                    id=uid,
                    email=email,
                    full_name=name,
                    role=role,
                    supabase_user_id=uid,
                    organization_id=fix["org_id"],
                    onboarding_completed=True,
                ))
        await session.commit()

        # 4. Insert one ImportedProject per org so isolation tests can
        # probe project-scoped endpoints without 404s. SKIPS the "fresh"
        # org so the new-user empty-state tests can verify a truly empty
        # tenant.
        for slug, fix in FIXTURES.items():
            if fix.get("no_resources"):
                continue
            session.add(ImportedProject(
                id=f"proj_{slug}_test_xxxxxxxxxxxxxxxxx"[:25],
                organization_id=fix["org_id"],
                external_id=f"{slug.upper()}-1",
                name=f"{fix['org_name']} Project",
                key=slug.upper(),
                source_tool="JIRA",
                is_active=True,
            ))
        await session.commit()

        # 5. Insert TeamMember rows for each developer so standup endpoints
        # have something to bind to. Same skip for "fresh".
        for slug, fix in FIXTURES.items():
            if fix.get("no_resources"):
                continue
            proj_id = f"proj_{slug}_test_xxxxxxxxxxxxxxxxx"[:25]
            for (uid, email, name, role) in fix["users"]:
                if role not in ("developer", "engineering_manager", "product_owner"):
                    continue
                session.add(TeamMember(
                    id=f"tm_{uid}"[:25],
                    organization_id=fix["org_id"],
                    imported_project_id=proj_id,
                    external_id=f"ext_{uid[:10]}",
                    email=email,
                    display_name=name,
                    role=role,
                    skill_tags=[],
                ))
        await session.commit()

        # 6. Print summary.
        for slug, fix in FIXTURES.items():
            print(f"[{slug}] org={fix['org_id']} users={len(fix['users'])}")
            for (uid, email, name, role) in fix["users"]:
                print(f"   - {role:20s} {email:25s} ({uid})")

    await engine.dispose()
    print("\n[OK] Seed complete. Run pytest tests/ next.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

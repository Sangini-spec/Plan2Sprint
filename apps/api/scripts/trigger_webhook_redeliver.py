"""Redeliver the most recent failed GitHub webhook delivery, then poll
the DB to confirm new commits land.

Uses the decrypted access token from the DB (same token the OAuth flow
provisioned). Read mostly — only side effect is triggering GitHub to
re-POST the latest stored delivery back to our webhook URL.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # type: ignore
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


ORG = "61d14720752b4ee8a8f834c16"
REPO_FULL = "Sangini-spec/Plan2Sprint"
HOOK_ID = 617188414


async def main():
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(db_url, echo=False)

    from app.models.tool_connection import ToolConnection
    from app.models.repository import Commit, Repository
    from app.services.encryption import decrypt_token_safe

    async with AsyncSession(engine) as db:
        conn = (await db.execute(
            select(ToolConnection).where(
                ToolConnection.organization_id == ORG,
                func.upper(ToolConnection.source_tool) == "GITHUB",
            )
        )).scalar_one_or_none()
        token = decrypt_token_safe(conn.access_token) if conn else None
        if not token:
            print("No token — abort"); return

        # Snapshot the latest commit BEFORE redeliver
        latest_before = (await db.execute(
            select(func.max(Commit.committed_at))
            .join(Repository, Repository.id == Commit.repository_id)
            .where(Repository.organization_id == ORG)
        )).scalar()
        commits_before = (await db.execute(
            select(func.count(Commit.id))
            .join(Repository, Repository.id == Commit.repository_id)
            .where(Repository.organization_id == ORG)
        )).scalar() or 0
        print(f"BEFORE redeliver:  commits={commits_before} latest={latest_before}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1) Get list of deliveries (most recent first)
        list_url = f"https://api.github.com/repos/{REPO_FULL}/hooks/{HOOK_ID}/deliveries?per_page=10"
        r = await client.get(list_url, headers=headers)
        if r.status_code != 200:
            print(f"list deliveries failed: {r.status_code} {r.text[:200]}")
            return
        deliveries = r.json()
        if not deliveries:
            print("No deliveries on file"); return

        # Pick the most recent push delivery that failed
        target = None
        for d in deliveries:
            if d.get("event") == "push" and (d.get("status_code") in (500, 504, 0) or not d.get("status_code")):
                target = d
                break
        if not target:
            print("No failed push to redeliver"); return
        delivery_id = target["id"]
        print(f"Redelivering delivery_id={delivery_id} (was sc={target.get('status_code')} {target.get('status')!r} at {target.get('delivered_at')})")

        # 2) Trigger redelivery
        rd_url = f"https://api.github.com/repos/{REPO_FULL}/hooks/{HOOK_ID}/deliveries/{delivery_id}/attempts"
        r2 = await client.post(rd_url, headers=headers)
        if r2.status_code not in (200, 202):
            print(f"redeliver POST failed: {r2.status_code} {r2.text[:400]}")
            return
        print(f"redeliver POST accepted: {r2.status_code}")

        # 3) Wait a bit, then poll the new delivery's status
        await asyncio.sleep(8)
        r3 = await client.get(list_url, headers=headers)
        if r3.status_code == 200:
            new_deliveries = r3.json()
            recent_redeliveries = [d for d in new_deliveries if d.get("redelivery") is True][:5]
            print()
            print("Recent redeliveries:")
            for d in recent_redeliveries:
                print(f"  {d.get('delivered_at')} sc={d.get('status_code')} status={d.get('status')!r} dur={d.get('duration')}s")

    # Re-check DB for new commits
    await asyncio.sleep(2)
    async with AsyncSession(engine) as db2:
        from app.models.repository import Commit, Repository
        commits_after = (await db2.execute(
            select(func.count(Commit.id))
            .join(Repository, Repository.id == Commit.repository_id)
            .where(Repository.organization_id == ORG)
        )).scalar() or 0
        latest_after = (await db2.execute(
            select(func.max(Commit.committed_at))
            .join(Repository, Repository.id == Commit.repository_id)
            .where(Repository.organization_id == ORG)
        )).scalar()
        print()
        print(f"AFTER  redeliver:  commits={commits_after} latest={latest_after}")
        delta = commits_after - commits_before
        if delta > 0:
            print(f"  +{delta} commits landed!")
        elif delta == 0:
            print("  no new commits (maybe the delivery had no new SHAs to ingest)")
        else:
            print("  unexpected: commit count decreased")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

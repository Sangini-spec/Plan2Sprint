"""Redeliver every failed GitHub push webhook from the recent history.

After deploying the conn.config_ typo fix, replay the 9 stored failed
deliveries so the DB catches up on the commits that were silently
dropped during the broken-handler window.
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

        before = (await db.execute(
            select(func.count(Commit.id))
            .join(Repository, Repository.id == Commit.repository_id)
            .where(Repository.organization_id == ORG)
        )).scalar() or 0
        latest_before = (await db.execute(
            select(func.max(Commit.committed_at))
            .join(Repository, Repository.id == Commit.repository_id)
            .where(Repository.organization_id == ORG)
        )).scalar()
        print(f"BEFORE: commits={before} latest={latest_before}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        list_url = f"https://api.github.com/repos/{REPO_FULL}/hooks/{HOOK_ID}/deliveries?per_page=30"
        r = await client.get(list_url, headers=headers)
        deliveries = r.json() if r.status_code == 200 else []

        # Get every failed push (skip the one we already redelivered)
        failed = [
            d for d in deliveries
            if d.get("event") == "push"
            and d.get("status_code") in (500, 504, 0, None)
            and not d.get("redelivery")
        ]
        print(f"Found {len(failed)} failed push deliveries to redeliver")

        for d in failed:
            delivery_id = d["id"]
            url = f"https://api.github.com/repos/{REPO_FULL}/hooks/{HOOK_ID}/deliveries/{delivery_id}/attempts"
            r2 = await client.post(url, headers=headers)
            print(f"  redelivered {delivery_id}: {r2.status_code}")
            # GitHub rate-limits redeliveries; small breather
            await asyncio.sleep(2)

        # Give the API a couple seconds per delivery to process
        wait_s = max(15, len(failed) * 3)
        print(f"Waiting {wait_s}s for processing…")
        await asyncio.sleep(wait_s)

    async with AsyncSession(engine) as db2:
        after = (await db2.execute(
            select(func.count(Commit.id))
            .join(Repository, Repository.id == Commit.repository_id)
            .where(Repository.organization_id == ORG)
        )).scalar() or 0
        latest_after = (await db2.execute(
            select(func.max(Commit.committed_at))
            .join(Repository, Repository.id == Commit.repository_id)
            .where(Repository.organization_id == ORG)
        )).scalar()
        print(f"AFTER:  commits={after} latest={latest_after}  (+{after - before})")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

"""Query GitHub for the webhook delivery history on the user's repo.

Uses the decrypted access token from the DB to call:
  GET /repos/{owner}/{repo}/hooks/{hook_id}/deliveries

Reports recent deliveries with status_code, event, action, delivered_at.
Tells us whether GitHub is even attempting deliveries, and what code
the API is responding with.

Read-only. Run from apps/api/.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # type: ignore
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import httpx
from sqlalchemy import select
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
    from app.services.encryption import decrypt_token_safe
    from sqlalchemy import func

    async with AsyncSession(engine) as db:
        conn_q = await db.execute(
            select(ToolConnection).where(
                ToolConnection.organization_id == ORG,
                func.upper(ToolConnection.source_tool) == "GITHUB",
            )
        )
        conn = conn_q.scalar_one_or_none()
        if not conn or not conn.access_token:
            print("No GitHub connection found"); return
        token = decrypt_token_safe(conn.access_token)
        if not token:
            print("Failed to decrypt token"); return

    await engine.dispose()

    # Query GitHub deliveries
    url = f"https://api.github.com/repos/{REPO_FULL}/hooks/{HOOK_ID}/deliveries?per_page=30"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
        print(f"GET {url}")
        print(f"  status={resp.status_code}")
        if resp.status_code != 200:
            print(f"  body={resp.text[:500]}")
            return
        deliveries = resp.json()
        if not isinstance(deliveries, list):
            print(f"  unexpected body: {deliveries}")
            return
        print(f"  delivery_count={len(deliveries)}")
        print()
        for d in deliveries:
            status = d.get("status")
            sc = d.get("status_code")
            event = d.get("event")
            action = d.get("action")
            delivered = d.get("delivered_at")
            redelivery = d.get("redelivery")
            duration = d.get("duration")
            print(f"  {delivered}  event={event!r:25s} action={(action or '-')!r:15s} sc={sc} status={status!r} dur={duration}s redelivery={redelivery}")

        # Drill into the latest 500 failure to see the response body
        print()
        print("=" * 70)
        print("DRILL-DOWN INTO LATEST 500 DELIVERY")
        print("=" * 70)
        latest_500 = next((d for d in deliveries if d.get("status_code") == 500), None)
        if latest_500:
            delivery_id = latest_500["id"]
            durl = f"https://api.github.com/repos/{REPO_FULL}/hooks/{HOOK_ID}/deliveries/{delivery_id}"
            r2 = await client.get(durl, headers=headers)
            if r2.status_code == 200:
                d2 = r2.json()
                req = d2.get("request", {})
                resp_obj = d2.get("response", {})
                print(f"  delivered_at={d2.get('delivered_at')} event={d2.get('event')}")
                print(f"  REQUEST HEADERS (selected):")
                req_headers = req.get("headers", {}) or {}
                for k in ("X-GitHub-Event", "X-GitHub-Delivery", "Content-Type", "User-Agent", "X-Hub-Signature-256"):
                    v = req_headers.get(k) or req_headers.get(k.lower())
                    if v:
                        print(f"    {k}: {(str(v)[:60])}")
                print(f"  RESPONSE status={resp_obj.get('status')}")
                resp_headers = resp_obj.get("headers", {}) or {}
                for k, v in resp_headers.items():
                    print(f"    {k}: {v}")
                resp_body = resp_obj.get("payload") or ""
                print(f"  RESPONSE BODY:")
                print(f"    {resp_body[:600]}")
            else:
                print(f"  Failed to fetch delivery: {r2.status_code} {r2.text[:200]}")


if __name__ == "__main__":
    asyncio.run(main())

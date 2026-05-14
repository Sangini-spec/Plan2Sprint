"""Inspect the GitHub webhook installation state for the org.

Reports:
  - Tool connection rows in this org
  - webhooks_by_repo config (what hook IDs we believe are installed)
  - Access-token sanity (decryptable? non-empty?)

Read-only. Run from apps/api/.
"""
from __future__ import annotations

import asyncio
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # type: ignore
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


ORG = "61d14720752b4ee8a8f834c16"


async def main():
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(db_url, echo=False)

    from app.models.tool_connection import ToolConnection
    from app.services.encryption import decrypt_token_safe

    async with AsyncSession(engine) as db:
        conns = (await db.execute(
            select(ToolConnection).where(ToolConnection.organization_id == ORG)
        )).scalars().all()
        print(f"ToolConnection rows in org={ORG}: {len(conns)}")
        for c in conns:
            print(f"\n  source_tool={c.source_tool!r} id={c.id}")
            print(f"    has_access_token={bool(c.access_token)}")
            if c.access_token:
                try:
                    decrypted = decrypt_token_safe(c.access_token)
                    if decrypted:
                        print(f"    token decrypt: OK (len={len(decrypted)}, starts={decrypted[:4]}…)")
                    else:
                        print(f"    token decrypt: returned None/empty")
                except Exception as e:
                    print(f"    token decrypt: FAILED ({e})")
            cfg = c.config or {}
            print(f"    config keys: {sorted(cfg.keys())}")
            wbr = cfg.get("webhooks_by_repo") or {}
            print(f"    webhooks_by_repo: {len(wbr)} entries")
            for repo_full, info in wbr.items():
                print(f"      repo={repo_full!r}: {json.dumps(info, default=str)[:200]}")
            secret = cfg.get("webhook_secret") or ""
            print(f"    webhook_secret set: {bool(secret)} (len={len(secret) if secret else 0})")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

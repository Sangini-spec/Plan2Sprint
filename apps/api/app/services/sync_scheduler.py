"""
Sync scheduler — periodic automatic sync for connected tools (ADO/Jira/GitHub).

Uses Redis distributed locks to prevent duplicate syncs across workers.
Reuses the existing sync_project_data() pipeline and post-sync side effects
(health signals, sprint completion, forecast refresh).

The scheduler ticks every 30 seconds and checks each ToolConnection to see
if it's overdue for a sync based on the configured interval.

Requires:
  - Redis (for distributed locking)
  - SYNC_SCHEDULER_ENABLED=true in .env

Usage:
    # In app lifespan:
    from .sync_scheduler import start_sync_scheduler
    task = await start_sync_scheduler()
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..config import settings
from ..database import engine
from ..models import ToolConnection
from ..models.imported_project import ImportedProject
from .redis_pool import get_redis
from .ws_manager import ws_manager

logger = logging.getLogger(__name__)

# Tool -> interval setting lookup
_TOOL_INTERVALS: dict[str, str] = {
    "ADO": "sync_interval_ado",
    "JIRA": "sync_interval_jira",
    "GITHUB": "sync_interval_github",
}

TICK_INTERVAL = 30  # seconds between scheduler checks
LOCK_TTL = 300      # 5 minutes — auto-release if worker crashes


async def start_sync_scheduler() -> asyncio.Task | None:
    """
    Start the sync scheduler background task.

    Returns None if disabled or Redis is unavailable.
    """
    if not settings.sync_scheduler_enabled:
        logger.info("[SyncScheduler] Disabled (SYNC_SCHEDULER_ENABLED=false)")
        return None

    redis = await get_redis()
    if not redis:
        logger.warning("[SyncScheduler] Redis unavailable — scheduler disabled")
        return None

    task = asyncio.create_task(_scheduler_loop())
    logger.info("[SyncScheduler] Started (ADO=%ds, JIRA=%ds, GitHub=%ds)",
                settings.sync_interval_ado, settings.sync_interval_jira, settings.sync_interval_github)
    return task


async def _scheduler_loop() -> None:
    """Main scheduler loop — ticks every TICK_INTERVAL seconds."""
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    while True:
        try:
            await asyncio.sleep(TICK_INTERVAL)
            await _tick(SessionFactory)
        except asyncio.CancelledError:
            logger.info("[SyncScheduler] Shutting down")
            break
        except Exception:
            logger.exception("[SyncScheduler] Tick error — retrying in 5s")
            await asyncio.sleep(5)


async def _tick(SessionFactory: async_sessionmaker) -> None:
    """Single scheduler tick — find and sync overdue connections."""
    now = datetime.now(timezone.utc)

    async with SessionFactory() as db:
        # Find all tool connections not currently syncing
        result = await db.execute(
            select(ToolConnection).where(ToolConnection.sync_status != "syncing")
        )
        connections = result.scalars().all()

        for conn in connections:
            interval_attr = _TOOL_INTERVALS.get(conn.source_tool)
            if not interval_attr:
                continue

            interval = getattr(settings, interval_attr, 300)

            # Check if overdue
            if conn.last_sync_at:
                elapsed = (now - conn.last_sync_at).total_seconds()
                if elapsed < interval:
                    continue

            # Try to acquire distributed lock
            redis = await get_redis()
            if not redis:
                return

            lock_key = f"sync_lock:{conn.organization_id}:{conn.source_tool}"
            acquired = await redis.set(lock_key, ws_manager.worker_id, nx=True, ex=LOCK_TTL)
            if not acquired:
                continue  # Another worker is handling this sync

            logger.info(
                "[SyncScheduler] Triggering sync: org=%s tool=%s (last=%s)",
                conn.organization_id, conn.source_tool,
                conn.last_sync_at.isoformat() if conn.last_sync_at else "never",
            )

            # Run sync in background (don't block the tick loop)
            asyncio.create_task(
                _execute_sync(conn.organization_id, conn.source_tool, conn.id)
            )


async def _execute_sync(org_id: str, tool: str, connection_id: str) -> None:
    """
    Execute a full sync for a tool connection.

    Fetches projects for the org, syncs each one, then runs post-sync
    side effects (signals, sprint completion, forecast).
    """
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    lock_key = f"sync_lock:{org_id}:{tool}"

    try:
        async with SessionFactory() as db:
            # Mark syncing
            result = await db.execute(
                select(ToolConnection).where(ToolConnection.id == connection_id)
            )
            conn = result.scalar_one_or_none()
            if not conn:
                return

            conn.sync_status = "syncing"
            await db.commit()

            # Find all active projects for this org+tool
            projects = (await db.execute(
                select(ImportedProject).where(
                    ImportedProject.organization_id == org_id,
                    ImportedProject.source_tool == tool,
                    ImportedProject.is_active == True,
                )
            )).scalars().all()

            synced_count = 0
            for project in projects:
                try:
                    await _sync_single_project(db, org_id, project, conn)
                    synced_count += 1
                except Exception:
                    logger.warning(
                        "[SyncScheduler] Failed to sync project=%s (%s)",
                        project.id, project.name, exc_info=True,
                    )

            # Mark complete
            conn.sync_status = "idle"
            conn.last_sync_at = datetime.now(timezone.utc)
            await db.commit()

            # Broadcast sync_complete
            await ws_manager.broadcast(org_id, {
                "type": "sync_complete",
                "data": {
                    "sourceTool": tool,
                    "projectsSynced": synced_count,
                    "trigger": "scheduler",
                },
            })

            logger.info(
                "[SyncScheduler] Sync complete: org=%s tool=%s projects=%d",
                org_id, tool, synced_count,
            )

    except Exception:
        logger.exception("[SyncScheduler] Sync failed: org=%s tool=%s", org_id, tool)

        # Reset sync status on failure
        try:
            async with SessionFactory() as db:
                result = await db.execute(
                    select(ToolConnection).where(ToolConnection.id == connection_id)
                )
                conn = result.scalar_one_or_none()
                if conn:
                    conn.sync_status = "error"
                    await db.commit()
        except Exception:
            pass

    finally:
        # Always release the lock
        redis = await get_redis()
        if redis:
            try:
                await redis.delete(lock_key)
            except Exception:
                pass


async def _sync_single_project(db, org_id: str, project, conn) -> None:
    """
    Sync a single project by fetching fresh data from the external tool
    and running the normalize + upsert pipeline.
    """
    tool = conn.source_tool.upper()

    if tool == "ADO":
        from ..services.ado_fetch import fetch_ado_project_data
        raw = await fetch_ado_project_data(db, org_id, project.external_id, conn)
    elif tool == "JIRA":
        from ..services.jira_fetch import fetch_jira_project_data
        raw = await fetch_jira_project_data(db, org_id, project.external_id, conn)
    else:
        logger.debug("[SyncScheduler] Skipping unsupported tool: %s", tool)
        return

    if not raw:
        return

    # Run the standard sync pipeline
    from ..adapters.sync import sync_project_data
    await sync_project_data(
        db=db,
        org_id=org_id,
        project_id=project.id,
        source_tool=tool,
        raw_iterations=raw.get("iterations"),
        raw_members=raw.get("members"),
        raw_work_items=raw.get("workItems"),
    )

    # Post-sync side effects
    try:
        from ..services.activity_engine import evaluate_all_signals
        await evaluate_all_signals(db, org_id)
    except Exception:
        pass

    try:
        from ..services.sprint_completion import check_and_complete_sprints
        await check_and_complete_sprints(db, org_id, project.id)
    except Exception:
        pass

    try:
        from ..services.sprint_forecast import refresh_forecast
        await refresh_forecast(db, org_id, project.id)
    except Exception:
        pass

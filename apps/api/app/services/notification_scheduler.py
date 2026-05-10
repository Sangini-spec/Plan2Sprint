"""
Notification Scheduler — fires daily digest messages at 9 AM and 5 PM,
and nudge messages for inactive POs.

Runs as a background asyncio task (same pattern as sync_scheduler.py).
Ticks every 60 seconds, checks if it's time to send.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from ..database import AsyncSessionLocal

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_running = False

# Track what was sent today to avoid duplicates
_sent_today: dict[str, set[str]] = {}  # {"morning": {"org1", "org2"}, "evening": {...}}
_last_reset_date: str = ""

TICK_INTERVAL = 60  # seconds

# Configure morning/evening hours (UTC)
# Adjust these based on target timezone
# IST = UTC+5:30, so 9 AM IST = 3:30 AM UTC, 5 PM IST = 11:30 AM UTC
MORNING_HOUR_UTC = 3   # ~9 AM IST
MORNING_MINUTE = 30
EVENING_HOUR_UTC = 11  # ~5 PM IST
EVENING_MINUTE = 30
NUDGE_CHECK_HOUR_UTC = 4  # ~10 AM IST

# Weekly stakeholder report — every Friday at 5 PM IST (11:30 UTC).
# Python's weekday(): Monday=0 ... Friday=4 ... Sunday=6.
WEEKLY_REPORT_WEEKDAY = 4  # Friday
WEEKLY_REPORT_HOUR_UTC = 11
WEEKLY_REPORT_MINUTE = 30


async def _reset_daily_tracker():
    """Reset sent tracker at midnight."""
    global _sent_today, _last_reset_date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != _last_reset_date:
        _sent_today = {"morning": set(), "evening": set(), "nudge": set(), "weekly_report": set(), "overdue_alerts": set()}
        _last_reset_date = today


async def _send_morning_digests():
    """Send morning digest to all connected orgs."""
    from .daily_digest import (
        get_connected_orgs, get_org_projects, get_po_email,
        generate_morning_digest,
    )
    from .card_builders import slack_morning_digest, teams_morning_digest
    from .delivery_queue import enqueue_notification

    async with AsyncSessionLocal() as db:
        org_ids = await get_connected_orgs(db)

        for org_id in org_ids:
            if org_id in _sent_today.get("morning", set()):
                continue  # Already sent today

            try:
                po_email = await get_po_email(db, org_id)
                if not po_email:
                    continue

                projects = await get_org_projects(db, org_id)
                for proj in projects:
                    data = await generate_morning_digest(db, org_id, proj["id"], proj["name"])

                    await enqueue_notification(
                        org_id=org_id,
                        recipient_email=po_email,
                        notification_type="daily_digest",
                        slack_payload=slack_morning_digest(data),
                        teams_payload=teams_morning_digest(data),
                        in_app_payload={
                            "title": f"📋 {proj['name']} — Morning Status",
                            "body": f"{data['completionPct']}% complete, {data['riskLabel']}",
                            "type": "daily_digest",
                        },
                    )

                _sent_today.setdefault("morning", set()).add(org_id)
                logger.info(f"Morning digest sent for org {org_id} ({len(projects)} projects)")

            except Exception as e:
                logger.warning(f"Morning digest failed for org {org_id}: {e}")


async def _send_evening_summaries():
    """Send evening summary to all connected orgs."""
    from .daily_digest import (
        get_connected_orgs, get_org_projects, get_po_email,
        generate_evening_summary,
    )
    from .card_builders import slack_evening_summary, teams_evening_summary
    from .delivery_queue import enqueue_notification

    async with AsyncSessionLocal() as db:
        org_ids = await get_connected_orgs(db)

        for org_id in org_ids:
            if org_id in _sent_today.get("evening", set()):
                continue

            try:
                po_email = await get_po_email(db, org_id)
                if not po_email:
                    continue

                projects = await get_org_projects(db, org_id)
                for proj in projects:
                    data = await generate_evening_summary(db, org_id, proj["id"], proj["name"])

                    await enqueue_notification(
                        org_id=org_id,
                        recipient_email=po_email,
                        notification_type="daily_digest",
                        slack_payload=slack_evening_summary(data),
                        teams_payload=teams_evening_summary(data),
                        in_app_payload={
                            "title": f"📋 {proj['name']} — End of Day",
                            "body": f"{data['completedToday']} stories completed today",
                            "type": "daily_digest",
                        },
                    )

                _sent_today.setdefault("evening", set()).add(org_id)
                logger.info(f"Evening summary sent for org {org_id} ({len(projects)} projects)")

            except Exception as e:
                logger.warning(f"Evening summary failed for org {org_id}: {e}")


async def _check_nudges():
    """Check for inactive POs and send nudge messages."""
    from .daily_digest import (
        get_connected_orgs, get_po_email, check_nudge_needed,
        generate_nudge_data,
    )
    from .card_builders import slack_nudge_message, teams_nudge_message
    from .delivery_queue import enqueue_notification

    async with AsyncSessionLocal() as db:
        org_ids = await get_connected_orgs(db)

        for org_id in org_ids:
            if org_id in _sent_today.get("nudge", set()):
                continue

            try:
                po_email = await get_po_email(db, org_id)
                if not po_email:
                    continue

                nudge_info = await check_nudge_needed(db, org_id, po_email)
                if not nudge_info:
                    continue

                days_inactive, nudge_level = nudge_info
                data = await generate_nudge_data(db, org_id, po_email, days_inactive, nudge_level)

                await enqueue_notification(
                    org_id=org_id,
                    recipient_email=po_email,
                    notification_type="inactivity_nudge",
                    slack_payload=slack_nudge_message(data),
                    teams_payload=teams_nudge_message(data),
                    in_app_payload={
                        "title": f"👋 {data['greeting']}",
                        "body": " | ".join(data["highlights"]),
                        "type": "inactivity_nudge",
                    },
                )

                _sent_today.setdefault("nudge", set()).add(org_id)
                logger.info(f"Nudge level {nudge_level} sent for org {org_id} ({days_inactive} days inactive)")

            except Exception as e:
                logger.warning(f"Nudge check failed for org {org_id}: {e}")


async def _notification_tick():
    """Main tick — runs every 60 seconds, checks time-based triggers."""
    await _reset_daily_tracker()

    now = datetime.now(timezone.utc)
    h, m = now.hour, now.minute

    # Morning digest window (2 minute window to avoid missing)
    if h == MORNING_HOUR_UTC and MORNING_MINUTE <= m < MORNING_MINUTE + 2:
        logger.info("Notification scheduler: morning digest window")
        await _send_morning_digests()
        # Hotfix 83 — once per morning, look for projects that have just
        # passed their target launch and email the PO. Idempotent: each
        # (project, target_date) combination is emailed at most once
        # (enforced via ImportedProject.last_overdue_alert_target_date).
        if "overdue_alerts" not in _sent_today.get("overdue_alerts", set()):
            try:
                from .overdue_alert import check_and_send_overdue_alerts
                async with AsyncSessionLocal() as _db:
                    report = await check_and_send_overdue_alerts(_db)
                logger.info(f"Overdue alerts: {report}")
                _sent_today.setdefault("overdue_alerts", set()).add("overdue_alerts")
            except Exception as e:
                logger.warning(f"Overdue alert check failed: {e}", exc_info=True)

    # Evening summary window
    if h == EVENING_HOUR_UTC and EVENING_MINUTE <= m < EVENING_MINUTE + 2:
        logger.info("Notification scheduler: evening summary window")
        await _send_evening_summaries()

    # Nudge check (once daily, 30 min after morning)
    if h == NUDGE_CHECK_HOUR_UTC and 0 <= m < 2:
        logger.info("Notification scheduler: nudge check")
        await _check_nudges()

    # Weekly stakeholder report — Fridays at 5 PM IST
    if (now.weekday() == WEEKLY_REPORT_WEEKDAY
            and h == WEEKLY_REPORT_HOUR_UTC
            and WEEKLY_REPORT_MINUTE <= m < WEEKLY_REPORT_MINUTE + 2
            and "weekly_report" not in _sent_today.get("weekly_report", set())):
        logger.info("Notification scheduler: weekly stakeholder report window")
        try:
            from ..routers.reports import send_friday_weekly_reports
            result = await send_friday_weekly_reports()
            logger.info(f"Friday reports dispatched: {result.get('total_sent', 0)} emails sent")
            _sent_today.setdefault("weekly_report", set()).add("weekly_report")
        except Exception as e:
            logger.warning(f"Friday reports failed: {e}")


async def _scheduler_loop():
    """Background loop that ticks every TICK_INTERVAL seconds."""
    global _running
    _running = True
    logger.info("Notification scheduler started")

    while _running:
        try:
            await _notification_tick()
        except Exception as e:
            logger.exception(f"Notification scheduler tick error: {e}")
        await asyncio.sleep(TICK_INTERVAL)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def start_notification_scheduler():
    """Start the notification scheduler background task."""
    global _task
    if _task is not None:
        return
    _task = asyncio.create_task(_scheduler_loop())
    logger.info("Notification scheduler task created")


async def stop_notification_scheduler():
    """Stop the notification scheduler."""
    global _running, _task
    _running = False
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    logger.info("Notification scheduler stopped")


# ---------------------------------------------------------------------------
# Manual Trigger (for testing)
# ---------------------------------------------------------------------------

async def trigger_morning_digest_now(org_id: str | None = None):
    """Manually trigger morning digests (for testing)."""
    from .daily_digest import (
        get_connected_orgs, get_org_projects, get_po_email,
        generate_morning_digest,
    )
    from .card_builders import slack_morning_digest, teams_morning_digest
    from .delivery_queue import enqueue_notification

    async with AsyncSessionLocal() as db:
        if org_id:
            org_ids = [org_id]
        else:
            org_ids = await get_connected_orgs(db)

        results = []
        for oid in org_ids:
            po_email = await get_po_email(db, oid)
            if not po_email:
                results.append({"org": oid, "status": "no_po_email"})
                continue

            projects = await get_org_projects(db, oid)
            for proj in projects:
                data = await generate_morning_digest(db, oid, proj["id"], proj["name"])
                await enqueue_notification(
                    org_id=oid,
                    recipient_email=po_email,
                    notification_type="daily_digest",
                    slack_payload=slack_morning_digest(data),
                    teams_payload=teams_morning_digest(data),
                    in_app_payload={
                        "title": f"📋 {proj['name']} — Morning Status",
                        "body": f"{data['completionPct']}% complete",
                        "type": "daily_digest",
                    },
                )
                results.append({"org": oid, "project": proj["name"], "status": "sent", "data": data})

        return results

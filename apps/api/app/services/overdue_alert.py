"""Overdue project alert (Hotfix 83).

Daily check: for every active project whose ``target_launch_date`` has
passed (with a 24h grace) and whose stories aren't all done, email the
PO ONCE with a project summary. The "once" is enforced by storing the
target_launch_date that triggered the email on
``ImportedProject.last_overdue_alert_target_date``.

Behaviour matrix:

    target_launch_date  |  last_overdue_alert  |  action
    --------------------|----------------------|------------------------
    in the future       |  any                 |  no-op
    past + complete     |  any                 |  no-op (delivered late)
    past + incomplete   |  matches target      |  no-op (already alerted)
    past + incomplete   |  null OR != target   |  send email + record

This means: the PO gets exactly one email per (project, target_date)
pair. If they rebalance to a new target and that ALSO slips, they'll
get a fresh email — different target, different idempotency key.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.imported_project import ImportedProject
from .project_status import OVERDUE_GRACE, compute_overdue_status

logger = logging.getLogger(__name__)


async def check_and_send_overdue_alerts(db: AsyncSession) -> dict:
    """Scan every active project, fire any pending overdue emails.

    Returns a small report dict so the caller (the cron tick) can log
    how many emails were considered / sent / suppressed:

        {"considered": N, "sent": M, "skipped_already_alerted": K, ...}
    """
    now = datetime.now(timezone.utc)
    cutoff = now - OVERDUE_GRACE

    # Pre-filter at the SQL layer: we only care about projects whose
    # target date is at least ``OVERDUE_GRACE`` in the past AND we
    # haven't already alerted for this exact target.
    q = await db.execute(
        select(ImportedProject).where(
            ImportedProject.is_active.is_(True),
            ImportedProject.target_launch_date.isnot(None),
            ImportedProject.target_launch_date < cutoff,
            or_(
                ImportedProject.last_overdue_alert_target_date.is_(None),
                ImportedProject.last_overdue_alert_target_date
                != ImportedProject.target_launch_date,
            ),
        )
    )
    candidates: list[ImportedProject] = list(q.scalars().all())

    sent = 0
    skipped_delivered = 0
    skipped_no_po = 0
    failed = 0

    for proj in candidates:
        # Build the summary now (also gives us completion_pct so we can
        # cleanly skip "delivered late" projects without sending email).
        from ..routers.retrospectives import _build_project_summary

        summary = await _build_project_summary(db, proj)

        # Belt-and-suspenders: status from the shared helper (matches UI).
        if summary["lifecycleStatus"] != "overdue":
            skipped_delivered += 1
            # Still record so we don't recheck this project every morning.
            proj.last_overdue_alert_target_date = proj.target_launch_date
            continue

        po_email = await _resolve_po_email(db, proj.organization_id)
        if not po_email:
            skipped_no_po += 1
            logger.warning(
                "[overdue_alert] no PO email for org=%s project=%s — skipping",
                proj.organization_id, proj.name,
            )
            continue

        ok = await _send_overdue_email(po_email, summary)
        if ok:
            sent += 1
            proj.last_overdue_alert_target_date = proj.target_launch_date
            logger.info(
                "[overdue_alert] sent for project=%s to=%s days_past=%s pct=%.1f",
                proj.name, po_email, summary["daysPastTarget"], summary["completionPct"],
            )
        else:
            failed += 1

    await db.commit()

    return {
        "considered": len(candidates),
        "sent": sent,
        "skipped_delivered_late": skipped_delivered,
        "skipped_no_po": skipped_no_po,
        "failed": failed,
    }


async def _resolve_po_email(db: AsyncSession, org_id: str) -> str | None:
    """Find the org's Product Owner email.

    Same resolution path the daily digest uses: prefer User-table rows
    with PO/admin/owner role; fall back to TeamMember rows. Returns the
    first match's email or None.

    Role values are case-inconsistent across the codebase (some rows
    store ``"PRODUCT_OWNER"`` upper, others ``"product_owner"`` lower),
    so we match case-insensitively via ``func.lower``.
    """
    from sqlalchemy import func
    from ..models.user import User
    from ..models.team_member import TeamMember

    PO_ROLES = ("product_owner", "owner", "admin")

    res = await db.execute(
        select(User.email).where(
            User.organization_id == org_id,
            func.lower(User.role).in_(PO_ROLES),
        ).limit(1)
    )
    row = res.scalar_one_or_none()
    if row:
        return row

    res = await db.execute(
        select(TeamMember.email).where(
            TeamMember.organization_id == org_id,
            func.lower(TeamMember.role).in_(PO_ROLES),
        ).limit(1)
    )
    return res.scalar_one_or_none()


async def _send_overdue_email(to_email: str, summary: dict) -> bool:
    """Send the project-overdue email. Returns True on SMTP success."""
    import asyncio
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from ..email.sender import _smtp_send, _executor, _html_to_plain

    if not settings.smtp_host or not settings.smtp_user:
        logger.warning("SMTP not configured — overdue alert NOT sent")
        return False

    project = summary["projectName"]
    target = summary["targetLaunchDate"] or ""
    target_short = target.split("T")[0] if target else "(unknown)"
    days = summary["daysPastTarget"]
    pct = summary["completionPct"]
    totals = summary["totals"]
    completed = summary["completedItems"]
    outstanding = summary["outstandingItems"]
    outstanding_phases = summary["outstandingPhases"]

    html = _render_html(project, target_short, days, pct, totals,
                        completed, outstanding, outstanding_phases)

    msg = MIMEMultipart("alternative")
    msg["From"] = settings.email_from_address
    msg["To"] = to_email
    msg["Subject"] = (
        f"Plan2Sprint: '{project}' has passed its target launch date"
    )
    msg.attach(MIMEText(_html_to_plain(html), "plain"))
    msg.attach(MIMEText(html, "html"))

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _smtp_send, msg, to_email)


def _render_html(
    project: str,
    target_short: str,
    days_past: int,
    completion_pct: float,
    totals: dict,
    completed: list[dict],          # kept in signature for back-compat; not rendered
    outstanding: list[dict],        # kept in signature for back-compat; not rendered
    outstanding_phases: list[dict],
) -> str:
    """Build the HTML email body. Inline-styled for broad client support.

    Hotfix 84 — trimmed the email to (1) the headline summary, (2) the
    four-tile counters, (3) the "Where the work sits" phase rollup, and
    (4) the Next-step CTA. The full per-feature completed / outstanding
    lists were too long for an email (some projects have 50+ items each)
    and the same data is one click away on the in-app retrospective
    card. ``completed`` / ``outstanding`` parameters are kept on the
    signature so the call site doesn't change.
    """
    base = "https://plan2sprint-web.purplebeach-150945ee.westus3.azurecontainerapps.io"

    phases_html = ""
    if outstanding_phases:
        rows = "".join(
            f"<li style='margin-bottom:4px;'><b>{p['name']}</b>: "
            f"{p['outstandingCount']} item{'s' if p['outstandingCount'] != 1 else ''} "
            f"still in flight</li>"
            for p in outstanding_phases
        )
        phases_html = (
            f"<h3 style='margin:18px 0 6px;color:#0f172a;font-size:15px;'>"
            f"Where the work sits</h3>"
            f"<ul style='padding-left:20px;color:#334155;'>{rows}</ul>"
        )

    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f5f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
    <div style="max-width:640px;margin:24px auto;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e2e8f0;">
      <div style="background:linear-gradient(135deg,#dc2626 0%,#7f1d1d 100%);color:white;padding:24px 28px;">
        <div style="font-size:11px;letter-spacing:0.18em;text-transform:uppercase;opacity:0.85;">Target Launch Date Passed</div>
        <h1 style="margin:6px 0 0;font-size:22px;line-height:1.3;">{project}</h1>
      </div>
      <div style="padding:24px 28px;color:#0f172a;font-size:14px;line-height:1.55;">
        <p>The project <b>{project}</b> was scheduled to launch on
        <b>{target_short}</b> &mdash; that date has now passed
        <b>{days_past} day{'s' if days_past != 1 else ''} ago</b> with the project
        at <b>{completion_pct}% complete</b>.</p>

        <table style="width:100%;border-collapse:collapse;margin:18px 0;">
          <tr>
            <td style="padding:10px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;text-align:center;width:25%;">
              <div style="font-size:24px;font-weight:700;color:#0f172a;">{totals['stories']}</div>
              <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;">Total stories</div>
            </td>
            <td style="padding:10px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;text-align:center;width:25%;">
              <div style="font-size:24px;font-weight:700;color:#15803d;">{totals['completed']}</div>
              <div style="font-size:11px;color:#15803d;text-transform:uppercase;letter-spacing:0.08em;">Completed</div>
            </td>
            <td style="padding:10px;background:#fff7ed;border:1px solid #fed7aa;border-radius:6px;text-align:center;width:25%;">
              <div style="font-size:24px;font-weight:700;color:#c2410c;">{totals['inProgress']}</div>
              <div style="font-size:11px;color:#c2410c;text-transform:uppercase;letter-spacing:0.08em;">In progress</div>
            </td>
            <td style="padding:10px;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;text-align:center;width:25%;">
              <div style="font-size:24px;font-weight:700;color:#b91c1c;">{totals['notStarted']}</div>
              <div style="font-size:11px;color:#b91c1c;text-transform:uppercase;letter-spacing:0.08em;">Not started</div>
            </td>
          </tr>
        </table>

        {phases_html}

        <div style="margin-top:24px;padding:16px;background:#f1f5f9;border-radius:8px;border-left:3px solid #0f172a;">
          <p style="margin:0 0 8px;font-weight:600;color:#0f172a;">Next step</p>
          <p style="margin:0 0 12px;color:#334155;">
            Generate a new sprint plan with a fresh launch date. The red banner
            on the dashboard clears automatically once a new target is set.
            For the full per-feature breakdown, open the project on Plan2Sprint.
          </p>
          <a href="{base}/po/planning"
             style="display:inline-block;padding:10px 18px;background:#0f172a;color:white;text-decoration:none;border-radius:6px;font-weight:600;font-size:14px;">
            Open Plan2Sprint Planning
          </a>
        </div>
      </div>
      <div style="padding:14px 28px;background:#f8fafc;color:#94a3b8;font-size:11px;text-align:center;border-top:1px solid #e2e8f0;">
        Sent once when a project crosses its target launch &mdash; you will not get this again for the same target date.
      </div>
    </div>
  </body>
</html>"""

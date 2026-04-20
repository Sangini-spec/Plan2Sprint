"""
Weekly stakeholder report — PDF generation and email dispatch.

Endpoints:
  GET  /api/reports/weekly?projectId=...         — download PDF for a project
  POST /api/reports/weekly/send-now?projectId=...— test trigger: generate + email immediately
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models.imported_project import ImportedProject, StakeholderProjectAssignment
from ..models.user import User
from ..services.weekly_report_renderer import (
    collect_weekly_report_data,
    render_weekly_report_pdf,
)
from ..email.sender import send_report_email

logger = logging.getLogger(__name__)
router = APIRouter()


def _safe_filename(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-") or "project"


@router.get("/reports/weekly")
async def download_weekly_report(
    projectId: str = Query(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and return the weekly report PDF as a download."""
    org_id = current_user.get("organization_id", "demo-org")

    # Verify project exists and belongs to this org
    proj_q = await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == projectId,
            ImportedProject.organization_id == org_id,
        )
    )
    project = proj_q.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        data = await collect_weekly_report_data(
            db, org_id, projectId, project.name, project.external_id or ""
        )
        pdf_bytes = render_weekly_report_pdf(data)
    except Exception as e:
        logger.exception("Weekly report generation failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to generate report")

    filename = f"plan2sprint-weekly-{_safe_filename(project.name)}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/reports/weekly/send-now")
async def send_weekly_report_now(
    projectId: str = Query(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin/testing: generate the weekly report and email it to all stakeholders
    assigned to this project RIGHT NOW, regardless of the Friday schedule."""
    org_id = current_user.get("organization_id", "demo-org")

    proj_q = await db.execute(
        select(ImportedProject).where(
            ImportedProject.id == projectId,
            ImportedProject.organization_id == org_id,
        )
    )
    project = proj_q.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    results = await _send_report_to_project_stakeholders(db, org_id, project)
    return {"ok": True, "projectName": project.name, "sent": results}


# ---------------------------------------------------------------------------
# Dispatcher helpers — also used by the Friday scheduler tick
# ---------------------------------------------------------------------------

async def _send_report_to_project_stakeholders(
    db: AsyncSession,
    org_id: str,
    project: ImportedProject,
) -> list[dict]:
    """Generate the PDF for a project and email it to all assigned stakeholders."""
    # Who are this project's stakeholders?
    # StakeholderProjectAssignment stores user_id; cross-reference with users table.
    assign_q = await db.execute(
        select(StakeholderProjectAssignment.user_id).where(
            StakeholderProjectAssignment.organization_id == org_id,
            StakeholderProjectAssignment.imported_project_id == project.id,
        )
    )
    user_ids = [row[0] for row in assign_q.all() if row[0]]

    recipients: list[tuple[str, str]] = []  # (email, name)
    if user_ids:
        users_q = await db.execute(
            select(User).where(User.id.in_(user_ids), User.email.isnot(None))
        )
        for u in users_q.scalars().all():
            recipients.append((u.email, u.full_name or u.email.split("@")[0]))

    # Fallback: if no explicit assignments, send to all stakeholders in the org
    if not recipients:
        fallback_q = await db.execute(
            select(User).where(
                User.organization_id == org_id,
                User.role == "stakeholder",
                User.email.isnot(None),
            )
        )
        for u in fallback_q.scalars().all():
            recipients.append((u.email, u.full_name or u.email.split("@")[0]))

    if not recipients:
        return [{"status": "skipped", "reason": "no_stakeholders"}]

    # Generate PDF once
    data = await collect_weekly_report_data(
        db, org_id, project.id, project.name, project.external_id or ""
    )
    pdf_bytes = render_weekly_report_pdf(data)
    filename = f"plan2sprint-weekly-{_safe_filename(project.name)}.pdf"

    # Email body
    subject = f"Plan2Sprint · Weekly Report — {project.name}"
    body_html = _email_body_html(project.name, data)

    results = []
    for email, name in recipients:
        try:
            ok = await send_report_email(
                to_email=email,
                subject=subject,
                html_body=body_html,
                pdf_bytes=pdf_bytes,
                pdf_filename=filename,
            )
            results.append({"to": email, "status": "sent" if ok else "failed"})
        except Exception as e:  # noqa: BLE001
            logger.warning("Report email to %s failed: %s", email, e)
            results.append({"to": email, "status": "error", "error": str(e)})
    return results


def _email_body_html(project_name: str, data) -> str:
    stamp = data.generated_at.strftime("%A, %d %b %Y")
    return f"""\
<div style="font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; max-width: 560px; margin: 0 auto; padding: 24px; color: #111827;">
  <h2 style="margin: 0 0 8px; color: #111827;">Weekly Report — {project_name}</h2>
  <p style="color: #6B7280; margin: 0 0 20px; font-size: 14px;">{stamp}</p>

  <div style="background: linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%); padding: 20px; border-radius: 12px; color: white; margin-bottom: 20px;">
    <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; opacity: 0.9; margin-bottom: 4px;">Overall Completion</div>
    <div style="font-size: 40px; font-weight: 700; line-height: 1;">{data.overall_completion_pct}%</div>
    <div style="font-size: 13px; opacity: 0.9; margin-top: 8px;">{data.stage_label} · {data.status_label}</div>
  </div>

  <p style="color: #374151; font-size: 14px; line-height: 1.6; margin: 0 0 20px;">
    {data.progress_narrative}
  </p>

  <p style="color: #6B7280; font-size: 13px; margin: 20px 0 0;">
    📎 Full one-page report attached as PDF. View detailed analytics in
    <a href="https://plan2sprint-web.purplebeach-150945ee.westus3.azurecontainerapps.io/stakeholder" style="color: #06b6d4; text-decoration: none; font-weight: 500;">Plan2Sprint</a>.
  </p>

  <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 24px 0;"/>
  <p style="color: #9CA3AF; font-size: 11px; margin: 0;">
    This is an automated weekly summary from Plan2Sprint. Sent every Friday at 5:00 PM IST.
  </p>
</div>
"""


async def send_friday_weekly_reports() -> dict:
    """Scheduler entry — dispatch weekly reports for ALL projects across ALL orgs."""
    from ..database import AsyncSessionLocal

    total = 0
    per_project = []
    async with AsyncSessionLocal() as db:
        proj_q = await db.execute(select(ImportedProject).where(ImportedProject.is_active == True))  # noqa: E712
        projects = list(proj_q.scalars().all())
        for project in projects:
            try:
                res = await _send_report_to_project_stakeholders(db, project.organization_id, project)
                sent_count = sum(1 for r in res if r.get("status") == "sent")
                total += sent_count
                per_project.append({
                    "project": project.name,
                    "org": project.organization_id,
                    "sent": sent_count,
                    "details": res,
                })
            except Exception as e:  # noqa: BLE001
                logger.warning("Friday report failed for project %s: %s", project.id, e)
    return {"total_sent": total, "projects": per_project}

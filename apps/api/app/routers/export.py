"""
Export API — generates PDF and CSV reports for stakeholder project overview.

GET  /api/export/overview   — JSON overview data for a project (used by frontend)
POST /api/export/csv        — Download CSV of project overview
POST /api/export/pdf        — Download PDF of project overview
GET  /api/export/weekly      — Get latest weekly report metadata
POST /api/export/weekly/generate — Force-generate a weekly report
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models.work_item import WorkItem
from ..models.iteration import Iteration
from ..models.team_member import TeamMember
from ..models.imported_project import ImportedProject

router = APIRouter()


async def _get_project_overview(db: AsyncSession, org_id: str, project_id: Optional[str] = None):
    """Gather project overview data for export."""

    # Get project info
    project_name = "All Projects"
    if project_id:
        proj = await db.execute(
            select(ImportedProject).where(
                ImportedProject.id == project_id,
                ImportedProject.organization_id == org_id,
            )
        )
        proj_row = proj.scalar_one_or_none()
        if proj_row:
            project_name = proj_row.name

    # Work item stats
    wi_conds = [WorkItem.organization_id == org_id]
    if project_id:
        wi_conds.append(WorkItem.imported_project_id == project_id)

    total_q = await db.execute(
        select(func.count(WorkItem.id)).where(*wi_conds)
    )
    total_items = total_q.scalar() or 0

    done_q = await db.execute(
        select(func.count(WorkItem.id)).where(
            *wi_conds,
            WorkItem.state.in_(["Done", "Closed", "Completed", "Resolved"])
        )
    )
    done_items = done_q.scalar() or 0

    in_progress_q = await db.execute(
        select(func.count(WorkItem.id)).where(
            *wi_conds,
            WorkItem.state.in_(["Active", "In Progress", "Committed", "Doing"])
        )
    )
    in_progress_items = in_progress_q.scalar() or 0

    total_sp_q = await db.execute(
        select(func.coalesce(func.sum(WorkItem.story_points), 0)).where(*wi_conds)
    )
    total_sp = int(total_sp_q.scalar() or 0)

    done_sp_q = await db.execute(
        select(func.coalesce(func.sum(WorkItem.story_points), 0)).where(
            *wi_conds,
            WorkItem.state.in_(["Done", "Closed", "Completed", "Resolved"])
        )
    )
    done_sp = int(done_sp_q.scalar() or 0)

    completion_pct = round((done_items / total_items * 100) if total_items > 0 else 0, 1)

    # Iterations / Sprints
    iter_conds = [Iteration.organization_id == org_id]
    if project_id:
        iter_conds.append(Iteration.imported_project_id == project_id)

    iters_q = await db.execute(
        select(Iteration).where(*iter_conds).order_by(Iteration.start_date.desc())
    )
    iterations = iters_q.scalars().all()
    total_sprints = len(iterations)

    # Active sprint
    now = datetime.now(timezone.utc)
    active_sprint = None
    for it in iterations:
        if it.start_date and it.end_date:
            if it.start_date <= now <= it.end_date:
                active_sprint = it.name
                break

    # Team members
    tm_conds = [TeamMember.organization_id == org_id]
    tm_q = await db.execute(
        select(func.count(TeamMember.id)).where(*tm_conds)
    )
    team_size = tm_q.scalar() or 0

    # Work items by type
    type_q = await db.execute(
        select(WorkItem.work_item_type, func.count(WorkItem.id)).where(*wi_conds).group_by(WorkItem.work_item_type)
    )
    items_by_type = {row[0]: row[1] for row in type_q.all()}

    # Work items by state
    state_q = await db.execute(
        select(WorkItem.state, func.count(WorkItem.id)).where(*wi_conds).group_by(WorkItem.state)
    )
    items_by_state = {row[0]: row[1] for row in state_q.all()}

    # Epics/Features progress
    epic_conds = [*wi_conds, WorkItem.work_item_type.in_(["Epic", "Feature"])]
    epics_q = await db.execute(
        select(WorkItem.title, WorkItem.state, WorkItem.story_points).where(*epic_conds)
    )
    epics = [{"title": r[0], "state": r[1], "story_points": r[2] or 0} for r in epics_q.all()]

    return {
        "project_name": project_name,
        "generated_at": now.isoformat(),
        "summary": {
            "total_work_items": total_items,
            "completed": done_items,
            "in_progress": in_progress_items,
            "not_started": total_items - done_items - in_progress_items,
            "completion_percentage": completion_pct,
            "total_story_points": total_sp,
            "completed_story_points": done_sp,
            "total_sprints": total_sprints,
            "active_sprint": active_sprint,
            "team_size": team_size,
        },
        "items_by_type": items_by_type,
        "items_by_state": items_by_state,
        "epics": epics,
    }


@router.get("/export/overview")
async def get_export_overview(
    projectId: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return JSON overview data for the selected project."""
    org_id = current_user.get("organization_id", "demo-org")
    return await _get_project_overview(db, org_id, projectId)


@router.post("/export/csv")
async def export_csv(
    projectId: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and download a CSV report of project overview."""
    org_id = current_user.get("organization_id", "demo-org")
    data = await _get_project_overview(db, org_id, projectId)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header section
    writer.writerow(["Plan2Sprint Project Report"])
    writer.writerow(["Project", data["project_name"]])
    writer.writerow(["Generated", data["generated_at"]])
    writer.writerow([])

    # Summary
    writer.writerow(["SUMMARY"])
    writer.writerow(["Metric", "Value"])
    s = data["summary"]
    writer.writerow(["Total Work Items", s["total_work_items"]])
    writer.writerow(["Completed", s["completed"]])
    writer.writerow(["In Progress", s["in_progress"]])
    writer.writerow(["Not Started", s["not_started"]])
    writer.writerow(["Completion %", f"{s['completion_percentage']}%"])
    writer.writerow(["Total Story Points", s["total_story_points"]])
    writer.writerow(["Completed Story Points", s["completed_story_points"]])
    writer.writerow(["Total Sprints", s["total_sprints"]])
    writer.writerow(["Active Sprint", s["active_sprint"] or "None"])
    writer.writerow(["Team Size", s["team_size"]])
    writer.writerow([])

    # Items by type
    writer.writerow(["ITEMS BY TYPE"])
    writer.writerow(["Type", "Count"])
    for type_name, count in data["items_by_type"].items():
        writer.writerow([type_name or "Unknown", count])
    writer.writerow([])

    # Items by state
    writer.writerow(["ITEMS BY STATE"])
    writer.writerow(["State", "Count"])
    for state_name, count in data["items_by_state"].items():
        writer.writerow([state_name or "Unknown", count])
    writer.writerow([])

    # Epics
    if data["epics"]:
        writer.writerow(["EPICS & FEATURES"])
        writer.writerow(["Title", "State", "Story Points"])
        for epic in data["epics"]:
            writer.writerow([epic["title"], epic["state"], epic["story_points"]])

    output.seek(0)
    filename = f"plan2sprint-report-{data['project_name'].replace(' ', '_')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export/pdf")
async def export_pdf(
    projectId: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and download a PDF report of project overview.

    Uses a simple HTML-to-PDF approach with basic styling.
    """
    org_id = current_user.get("organization_id", "demo-org")
    data = await _get_project_overview(db, org_id, projectId)
    s = data["summary"]

    html = f"""<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: Arial, sans-serif; margin: 40px; color: #1e293b; }}
  h1 {{ color: #0f172a; border-bottom: 3px solid #0ea5e9; padding-bottom: 8px; }}
  h2 {{ color: #334155; margin-top: 24px; }}
  .meta {{ color: #64748b; font-size: 13px; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
  th {{ background: #f1f5f9; font-weight: 600; font-size: 13px; }}
  td {{ font-size: 13px; }}
  .stat-grid {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0; }}
  .stat-card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; min-width: 140px; }}
  .stat-value {{ font-size: 28px; font-weight: 700; color: #0f172a; }}
  .stat-label {{ font-size: 11px; text-transform: uppercase; color: #64748b; letter-spacing: 0.05em; }}
  .progress-bar {{ background: #e2e8f0; height: 8px; border-radius: 4px; margin-top: 8px; }}
  .progress-fill {{ background: #10b981; height: 100%; border-radius: 4px; }}
</style>
</head>
<body>
  <h1>Plan2Sprint — {data["project_name"]}</h1>
  <p class="meta">Generated: {data["generated_at"][:10]}</p>

  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-value">{s["total_work_items"]}</div>
      <div class="stat-label">Total Items</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{s["completion_percentage"]}%</div>
      <div class="stat-label">Complete</div>
      <div class="progress-bar"><div class="progress-fill" style="width:{s['completion_percentage']}%"></div></div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{s["total_story_points"]}</div>
      <div class="stat-label">Story Points</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{s["team_size"]}</div>
      <div class="stat-label">Team Members</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{s["total_sprints"]}</div>
      <div class="stat-label">Sprints</div>
    </div>
  </div>

  <h2>Items by State</h2>
  <table>
    <tr><th>State</th><th>Count</th></tr>
    {"".join(f"<tr><td>{state or 'Unknown'}</td><td>{count}</td></tr>" for state, count in data["items_by_state"].items())}
  </table>

  <h2>Items by Type</h2>
  <table>
    <tr><th>Type</th><th>Count</th></tr>
    {"".join(f"<tr><td>{t or 'Unknown'}</td><td>{count}</td></tr>" for t, count in data["items_by_type"].items())}
  </table>

  {"<h2>Epics &amp; Features</h2><table><tr><th>Title</th><th>State</th><th>SP</th></tr>" + "".join(f"<tr><td>{e['title']}</td><td>{e['state']}</td><td>{e['story_points']}</td></tr>" for e in data["epics"]) + "</table>" if data["epics"] else ""}

  <p class="meta" style="margin-top: 32px;">Report generated by Plan2Sprint</p>
</body>
</html>"""

    # Return as HTML that the browser can print-to-PDF
    # (A proper solution would use weasyprint/puppeteer, but this works for MVP)
    filename = f"plan2sprint-report-{data['project_name'].replace(' ', '_')}.html"

    return StreamingResponse(
        iter([html]),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

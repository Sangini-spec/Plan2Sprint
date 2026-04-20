"""
Export API — generates PDF and CSV reports for stakeholder project overview.

GET  /api/export/overview          — JSON overview data for a project
POST /api/export/csv               — Download CSV of project overview
POST /api/export/pdf               — Download HTML report (printable to PDF)
GET  /api/export/weekly            — Get latest weekly report
POST /api/export/weekly/generate   — Force-generate a weekly report
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models.work_item import WorkItem
from ..models.iteration import Iteration
from ..models.team_member import TeamMember
from ..models.imported_project import ImportedProject
from ..models.sprint_plan import SprintPlan

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Comprehensive data gatherer
# ---------------------------------------------------------------------------

async def _get_full_report_data(db: AsyncSession, org_id: str, project_id: Optional[str] = None):
    """Gather all report data: summary, sprints, team, features, risks, AI."""

    now = datetime.now(timezone.utc)

    # --- Project info ---
    project_name = "All Projects"
    source_tool = ""
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
            source_tool = proj_row.source_tool or ""

    # --- Work item base filters ---
    wi_conds = [WorkItem.organization_id == org_id]
    if project_id:
        wi_conds.append(WorkItem.imported_project_id == project_id)

    # Total items (all types)
    total_q = await db.execute(select(func.count(WorkItem.id)).where(*wi_conds))
    total_items = total_q.scalar() or 0

    # Done items
    done_q = await db.execute(
        select(func.count(WorkItem.id)).where(*wi_conds, WorkItem.status.in_(["DONE", "CLOSED"]))
    )
    done_items = done_q.scalar() or 0

    # In progress items
    ip_q = await db.execute(
        select(func.count(WorkItem.id)).where(*wi_conds, WorkItem.status.in_(["IN_PROGRESS", "IN_REVIEW"]))
    )
    in_progress_items = ip_q.scalar() or 0

    # Story points
    total_sp_q = await db.execute(
        select(func.coalesce(func.sum(WorkItem.story_points), 0)).where(*wi_conds)
    )
    total_sp = int(total_sp_q.scalar() or 0)

    done_sp_q = await db.execute(
        select(func.coalesce(func.sum(WorkItem.story_points), 0)).where(
            *wi_conds, WorkItem.status.in_(["DONE", "CLOSED"])
        )
    )
    done_sp = int(done_sp_q.scalar() or 0)

    # Completion % — use same formula as PO dashboard (stories/tasks only, not features/epics)
    # This matches /api/dashboard/feature-progress which counts child stories under features
    story_conds = [*wi_conds, WorkItem.type.in_(["story", "task", "bug", "issue"])]
    story_total_q = await db.execute(select(func.count(WorkItem.id)).where(*story_conds))
    story_done_q = await db.execute(
        select(func.count(WorkItem.id)).where(*story_conds, WorkItem.status.in_(["DONE", "CLOSED"]))
    )
    story_total = story_total_q.scalar() or 0
    story_done = story_done_q.scalar() or 0
    completion_pct = round((story_done / story_total * 100) if story_total > 0 else 0, 1)

    # --- Iterations ---
    iter_conds = [Iteration.organization_id == org_id]
    if project_id:
        iter_conds.append(Iteration.imported_project_id == project_id)
    iters_q = await db.execute(
        select(Iteration).where(*iter_conds).order_by(Iteration.start_date.asc())
    )
    iterations = iters_q.scalars().all()

    sprints_data = []
    active_sprint = None
    for it in iterations:
        # Count items in this iteration
        it_total = await db.execute(
            select(func.count()).select_from(WorkItem).where(
                WorkItem.organization_id == org_id, WorkItem.iteration_id == it.id
            )
        )
        it_done = await db.execute(
            select(func.count()).select_from(WorkItem).where(
                WorkItem.organization_id == org_id, WorkItem.iteration_id == it.id,
                WorkItem.status.in_(["DONE", "CLOSED"])
            )
        )
        t_count = it_total.scalar() or 0
        d_count = it_done.scalar() or 0
        it_pct = round((d_count / t_count * 100) if t_count > 0 else 0, 1)

        is_active = False
        if it.start_date and it.end_date:
            s = it.start_date.replace(tzinfo=timezone.utc) if it.start_date.tzinfo is None else it.start_date
            e = it.end_date.replace(tzinfo=timezone.utc) if it.end_date.tzinfo is None else it.end_date
            if s <= now <= e:
                is_active = True
                active_sprint = it.name

        sprints_data.append({
            "name": it.name,
            "state": it.state,
            "start_date": it.start_date.isoformat() if it.start_date else "",
            "end_date": it.end_date.isoformat() if it.end_date else "",
            "total_items": t_count,
            "done_items": d_count,
            "completion_pct": it_pct,
            "is_active": is_active,
        })

    # --- Team Members ---
    tm_q = await db.execute(
        select(TeamMember).where(TeamMember.organization_id == org_id)
    )
    members = tm_q.scalars().all()

    team_data = []
    for m in members:
        # Assigned SP and status counts per member
        m_sp = await db.execute(
            select(func.coalesce(func.sum(WorkItem.story_points), 0)).where(
                *wi_conds, WorkItem.assignee_id == m.id
            )
        )
        m_ip = await db.execute(
            select(func.count()).select_from(WorkItem).where(
                *wi_conds, WorkItem.assignee_id == m.id, WorkItem.status == "IN_PROGRESS"
            )
        )
        m_done = await db.execute(
            select(func.count()).select_from(WorkItem).where(
                *wi_conds, WorkItem.assignee_id == m.id, WorkItem.status.in_(["DONE", "CLOSED"])
            )
        )
        assigned_sp = int(m_sp.scalar() or 0)
        capacity = int(m.default_capacity or 40)
        util = min(round((assigned_sp / max(capacity, 1)) * 100), 100) if assigned_sp > 0 else 0

        team_data.append({
            "name": m.display_name,
            "email": m.email,
            "role": m.role or "developer",
            "assigned_sp": assigned_sp,
            "in_progress": m_ip.scalar() or 0,
            "done": m_done.scalar() or 0,
            "utilization_pct": util,
        })

    # --- Features/Epics with child counts ---
    features_q = await db.execute(
        select(WorkItem).where(*wi_conds, WorkItem.type.in_(["feature", "epic"]))
        .order_by(WorkItem.priority.asc())
    )
    features = features_q.scalars().all()

    features_data = []
    for f in features:
        # Count children
        child_total = await db.execute(
            select(func.count()).select_from(WorkItem).where(
                WorkItem.organization_id == org_id, WorkItem.epic_id == f.id
            )
        )
        child_done = await db.execute(
            select(func.count()).select_from(WorkItem).where(
                WorkItem.organization_id == org_id, WorkItem.epic_id == f.id,
                WorkItem.status.in_(["DONE", "CLOSED"])
            )
        )
        ct = child_total.scalar() or 0
        cd = child_done.scalar() or 0
        fpct = round((cd / ct * 100) if ct > 0 else 0, 1)

        features_data.append({
            "title": f.title,
            "type": f.type,
            "status": f.status,
            "story_points": f.story_points or 0,
            "child_stories": ct,
            "done_stories": cd,
            "completion_pct": fpct,
        })

    # --- Risk flags (items in progress with no recent activity) ---
    risk_items = []
    active_wis = await db.execute(
        select(WorkItem).where(
            *wi_conds,
            WorkItem.status.in_(["IN_PROGRESS", "IN_REVIEW"]),
        )
    )
    for wi in active_wis.scalars().all():
        risk = wi.spillover_risk or "low"
        reason = wi.spillover_reason or ""
        if risk in ("medium", "high", "critical") or reason:
            assignee_name = ""
            if wi.assignee_id:
                for m in members:
                    if m.id == wi.assignee_id:
                        assignee_name = m.display_name
                        break
            risk_items.append({
                "title": wi.title,
                "external_id": wi.external_id,
                "status": wi.status,
                "risk_level": risk,
                "reason": reason,
                "assignee": assignee_name,
                "story_points": wi.story_points or 0,
            })

    # --- AI Recommendations (from latest sprint plan) ---
    ai_data = None
    if project_id:
        plan_q = await db.execute(
            select(SprintPlan).where(
                SprintPlan.organization_id == org_id,
                SprintPlan.project_id == project_id,
                SprintPlan.status != "REJECTED",
            ).order_by(SprintPlan.created_at.desc()).limit(1)
        )
        plan = plan_q.scalar_one_or_none()
        if plan:
            ai_data = {
                "status": plan.status,
                "rationale": plan.overall_rationale or "",
                "confidence": plan.confidence_score,
                "estimated_sprints": plan.estimated_sprints,
                "estimated_weeks": plan.estimated_weeks_total,
                "estimated_end": plan.estimated_end_date.isoformat() if plan.estimated_end_date else None,
                "success_probability": plan.success_probability,
                "capacity_recommendations": plan.capacity_recommendations,
            }

    # --- All work items (for CSV) ---
    all_wis_q = await db.execute(
        select(WorkItem).where(*wi_conds).order_by(WorkItem.type.asc(), WorkItem.priority.asc())
    )
    all_work_items = []
    for wi in all_wis_q.scalars().all():
        assignee_name = ""
        if wi.assignee_id:
            for m in members:
                if m.id == wi.assignee_id:
                    assignee_name = m.display_name
                    break
        sprint_name = ""
        if wi.iteration_id:
            for s in sprints_data:
                pass  # We'll resolve below
        all_work_items.append({
            "external_id": wi.external_id,
            "title": wi.title,
            "type": wi.type,
            "status": wi.status,
            "story_points": wi.story_points or 0,
            "assignee": assignee_name,
            "priority": wi.priority,
            "labels": ",".join(wi.labels) if wi.labels else "",
        })

    return {
        "project_name": project_name,
        "source_tool": source_tool,
        "generated_at": now.isoformat(),
        "summary": {
            "total_work_items": total_items,
            "completed": done_items,
            "in_progress": in_progress_items,
            "not_started": total_items - done_items - in_progress_items,
            "completion_percentage": completion_pct,
            "total_story_points": total_sp,
            "completed_story_points": done_sp,
            "total_sprints": len(sprints_data),
            "active_sprint": active_sprint,
            "team_size": len(members),
        },
        "sprints": sprints_data,
        "features": features_data,
        "team": team_data,
        "risk_items": risk_items,
        "ai_recommendations": ai_data,
        "work_items": all_work_items,
    }


# ---------------------------------------------------------------------------
# GET /api/export/overview
# ---------------------------------------------------------------------------

@router.get("/export/overview")
async def get_export_overview(
    projectId: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")
    data = await _get_full_report_data(db, org_id, projectId)
    return data


# ---------------------------------------------------------------------------
# POST /api/export/csv
# ---------------------------------------------------------------------------

@router.post("/export/csv")
async def export_csv(
    projectId: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")
    data = await _get_full_report_data(db, org_id, projectId)
    s = data["summary"]

    output = io.StringIO()
    writer = csv.writer(output)

    # 1. PROJECT SUMMARY
    writer.writerow(["PLAN2SPRINT PROJECT REPORT"])
    writer.writerow(["Project", data["project_name"]])
    writer.writerow(["Source", data["source_tool"].upper() or "N/A"])
    writer.writerow(["Generated", data["generated_at"][:19].replace("T", " ")])
    writer.writerow([])
    writer.writerow(["PROJECT SUMMARY"])
    writer.writerow(["Metric", "Value"])
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

    # 2. SPRINTS
    writer.writerow(["SPRINTS"])
    writer.writerow(["Name", "State", "Start Date", "End Date", "Total Items", "Done", "Completion %"])
    for sp in data["sprints"]:
        writer.writerow([
            sp["name"], sp["state"],
            sp["start_date"][:10] if sp["start_date"] else "",
            sp["end_date"][:10] if sp["end_date"] else "",
            sp["total_items"], sp["done_items"], f"{sp['completion_pct']}%"
        ])
    writer.writerow([])

    # 3. FEATURES/EPICS
    writer.writerow(["FEATURES & EPICS"])
    writer.writerow(["Title", "Type", "Status", "Story Points", "Child Stories", "Done Stories", "Completion %"])
    for f in data["features"]:
        writer.writerow([
            f["title"], f["type"], f["status"], f["story_points"],
            f["child_stories"], f["done_stories"], f"{f['completion_pct']}%"
        ])
    writer.writerow([])

    # 4. TEAM MEMBERS
    writer.writerow(["TEAM MEMBERS"])
    writer.writerow(["Name", "Email", "Role", "Assigned SP", "In Progress", "Done", "Utilization %"])
    for m in data["team"]:
        writer.writerow([
            m["name"], m["email"], m["role"], m["assigned_sp"],
            m["in_progress"], m["done"], f"{m['utilization_pct']}%"
        ])
    writer.writerow([])

    # 5. WORK ITEMS
    writer.writerow(["ALL WORK ITEMS"])
    writer.writerow(["External ID", "Title", "Type", "Status", "Story Points", "Assignee", "Priority", "Labels"])
    for wi in data["work_items"]:
        writer.writerow([
            wi["external_id"], wi["title"], wi["type"], wi["status"],
            wi["story_points"], wi["assignee"], wi["priority"], wi["labels"]
        ])
    writer.writerow([])

    # 6. RISK FLAGS
    if data["risk_items"]:
        writer.writerow(["RISK FLAGS"])
        writer.writerow(["Title", "Status", "Risk Level", "Reason", "Assignee"])
        for r in data["risk_items"]:
            writer.writerow([r["title"], r["status"], r["risk_level"], r["reason"], r["assignee"]])

    output.seek(0)
    filename = f"plan2sprint-report-{data['project_name'].replace(' ', '_')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# POST /api/export/pdf
# ---------------------------------------------------------------------------

@router.post("/export/pdf")
async def export_pdf(
    projectId: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")
    data = await _get_full_report_data(db, org_id, projectId)
    s = data["summary"]

    # Build sprint rows
    sprint_rows = ""
    for sp in data["sprints"]:
        active_cls = "background:#e0f2fe;" if sp["is_active"] else ""
        sprint_rows += f"""<tr style="{active_cls}">
            <td>{sp["name"]}</td><td>{sp["state"]}</td>
            <td>{sp["start_date"][:10] if sp["start_date"] else "—"}</td>
            <td>{sp["end_date"][:10] if sp["end_date"] else "—"}</td>
            <td>{sp["total_items"]}</td><td>{sp["done_items"]}</td>
            <td>{sp["completion_pct"]}%</td>
        </tr>"""

    # Build feature rows with progress bars
    feature_rows = ""
    for f in data["features"]:
        pct = f["completion_pct"]
        color = "#10b981" if pct >= 80 else "#f59e0b" if pct >= 40 else "#ef4444"
        feature_rows += f"""<tr>
            <td>{f["title"]}</td><td>{f["type"]}</td><td>{f["status"]}</td>
            <td>{f["child_stories"]}</td><td>{f["done_stories"]}</td>
            <td><div style="display:flex;align-items:center;gap:8px;">
                <div style="flex:1;background:#e2e8f0;height:6px;border-radius:3px;">
                    <div style="width:{pct}%;background:{color};height:100%;border-radius:3px;"></div>
                </div>
                <span style="font-size:12px;font-weight:600;">{pct}%</span>
            </div></td>
            <td>{f["story_points"]}</td>
        </tr>"""

    # Build team rows
    team_rows = ""
    for m in data["team"]:
        team_rows += f"""<tr>
            <td>{m["name"]}</td><td>{m["email"]}</td>
            <td>{m["assigned_sp"]}</td><td>{m["in_progress"]}</td>
            <td>{m["done"]}</td><td>{m["utilization_pct"]}%</td>
        </tr>"""

    # Build risk rows
    risk_rows = ""
    for r in data["risk_items"]:
        level = r["risk_level"]
        badge_color = "#ef4444" if level == "critical" else "#f59e0b" if level == "high" else "#3b82f6"
        risk_rows += f"""<tr>
            <td>{r["title"]}</td><td>{r["status"]}</td>
            <td><span style="background:{badge_color};color:white;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">{level.upper()}</span></td>
            <td style="font-size:12px;">{r["reason"]}</td>
            <td>{r["assignee"]}</td>
        </tr>"""

    # AI section
    ai_section = ""
    ai = data.get("ai_recommendations")
    if ai:
        cap = ai.get("capacity_recommendations") or {}
        ai_section = f"""
        <h2>AI Sprint Recommendations</h2>
        <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:16px;margin:12px 0;">
            <div style="display:flex;gap:24px;margin-bottom:12px;">
                <div><span style="font-size:11px;color:#64748b;text-transform:uppercase;">Status</span><br><strong>{ai["status"]}</strong></div>
                {"<div><span style='font-size:11px;color:#64748b;text-transform:uppercase;'>Confidence</span><br><strong>" + str(round(ai["confidence"] * 100 if ai["confidence"] and ai["confidence"] <= 1 else ai["confidence"] or 0)) + "%</strong></div>" if ai.get("confidence") else ""}
                {"<div><span style='font-size:11px;color:#64748b;text-transform:uppercase;'>Est. Sprints</span><br><strong>" + str(ai["estimated_sprints"]) + "</strong></div>" if ai.get("estimated_sprints") else ""}
                {"<div><span style='font-size:11px;color:#64748b;text-transform:uppercase;'>Est. End</span><br><strong>" + str(ai["estimated_end"][:10] if ai.get("estimated_end") else "—") + "</strong></div>" if ai.get("estimated_end") else ""}
            </div>
            {"<p style='font-size:13px;color:#334155;line-height:1.6;margin:0;'>" + ai["rationale"] + "</p>" if ai.get("rationale") else ""}
            {"<p style='font-size:12px;color:#64748b;margin-top:8px;'>" + cap.get("summary", "") + "</p>" if cap.get("summary") else ""}
        </div>
        """

    source_badge = f"<span style='background:#0078D4;color:white;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;margin-left:8px;'>{data['source_tool'].upper()}</span>" if data["source_tool"] else ""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Plan2Sprint Report - {data["project_name"]}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 40px; color: #1e293b; background: white; }}
  @media print {{ body {{ padding: 20px; }} }}
  h1 {{ color: #0f172a; border-bottom: 3px solid #0ea5e9; padding-bottom: 10px; font-size: 24px; }}
  h2 {{ color: #334155; margin-top: 28px; font-size: 16px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }}
  .meta {{ color: #64748b; font-size: 12px; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0 20px; font-size: 13px; }}
  th {{ background: #f1f5f9; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: #475569; text-align: left; padding: 8px 10px; border-bottom: 2px solid #e2e8f0; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #f1f5f9; }}
  .stat-grid {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 16px 0; }}
  .stat-card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 18px; min-width: 130px; flex: 1; }}
  .stat-value {{ font-size: 26px; font-weight: 700; color: #0f172a; }}
  .stat-label {{ font-size: 10px; text-transform: uppercase; color: #64748b; letter-spacing: 0.08em; margin-top: 2px; }}
  .progress-bar {{ background: #e2e8f0; height: 8px; border-radius: 4px; margin-top: 6px; }}
  .progress-fill {{ background: #10b981; height: 100%; border-radius: 4px; transition: width 0.3s; }}
  .footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 11px; text-align: center; }}
</style>
</head>
<body>

  <h1>{data["project_name"]} {source_badge}</h1>
  <p style="font-size:11px;color:#94a3b8;margin-top:-8px;">Plan2Sprint Project Report</p>
  <p class="meta">Generated: {data["generated_at"][:19].replace("T", " ")} UTC</p>

  <!-- Section 1: Project Summary -->
  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-value">{s["total_work_items"]}</div>
      <div class="stat-label">Total Items</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{s["completed"]}</div>
      <div class="stat-label">Completed</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{s["in_progress"]}</div>
      <div class="stat-label">In Progress</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{s["completion_percentage"]}%</div>
      <div class="stat-label">Complete</div>
      <div class="progress-bar"><div class="progress-fill" style="width:{s['completion_percentage']}%"></div></div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{s["total_story_points"]}</div>
      <div class="stat-label">Total SP</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{s["completed_story_points"]}</div>
      <div class="stat-label">Done SP</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{s["team_size"]}</div>
      <div class="stat-label">Team</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{s["total_sprints"]}</div>
      <div class="stat-label">Sprints</div>
    </div>
  </div>

  <!-- Section 2: Sprint Breakdown -->
  {"<h2>Sprint Breakdown</h2><table><tr><th>Sprint</th><th>State</th><th>Start</th><th>End</th><th>Items</th><th>Done</th><th>Completion</th></tr>" + sprint_rows + "</table>" if sprint_rows else ""}

  <!-- Section 3: Feature Progress -->
  {"<h2>Feature / Epic Progress</h2><table><tr><th>Feature</th><th>Type</th><th>Status</th><th>Stories</th><th>Done</th><th>Progress</th><th>SP</th></tr>" + feature_rows + "</table>" if feature_rows else ""}

  <!-- Section 4: Team Capacity -->
  {"<h2>Team Capacity</h2><table><tr><th>Developer</th><th>Email</th><th>Assigned SP</th><th>In Progress</th><th>Done</th><th>Utilization</th></tr>" + team_rows + "</table>" if team_rows else ""}

  <!-- Section 5: Risk Flags -->
  {"<h2>Risk Flags</h2><table><tr><th>Item</th><th>Status</th><th>Risk</th><th>Reason</th><th>Assignee</th></tr>" + risk_rows + "</table>" if risk_rows else ""}

  <!-- Section 6: AI Recommendations -->
  {ai_section}

  <div class="footer">
    Report generated by Plan2Sprint — The Brain of Your Agile Stack
  </div>

</body>
</html>"""

    # Return as downloadable HTML file with .html extension
    # User opens it in browser and uses Ctrl+P > Save as PDF
    filename = f"Plan2Sprint-Report-{data['project_name'].replace(' ', '-')}.html"
    return StreamingResponse(
        iter([html.encode("utf-8")]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Weekly Report
# ---------------------------------------------------------------------------

async def _generate_weekly_digest(db: AsyncSession, org_id: str, project_id: Optional[str] = None):
    """Generate a weekly sprint health digest for the last 7 days."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    wi_conds = [WorkItem.organization_id == org_id]
    if project_id:
        wi_conds.append(WorkItem.imported_project_id == project_id)

    # Items completed this week
    completed_q = await db.execute(
        select(WorkItem.title, WorkItem.story_points).where(
            *wi_conds,
            WorkItem.status.in_(["DONE", "CLOSED"]),
            WorkItem.updated_at >= week_ago,
        )
    )
    completed_items = [{"title": r[0], "sp": r[1] or 0} for r in completed_q.all()]
    completed_sp = sum(i["sp"] for i in completed_items)

    # Items started this week (moved to IN_PROGRESS)
    started_q = await db.execute(
        select(func.count()).select_from(WorkItem).where(
            *wi_conds,
            WorkItem.status == "IN_PROGRESS",
            WorkItem.updated_at >= week_ago,
        )
    )
    started_count = started_q.scalar() or 0

    # Total status snapshot
    total_q = await db.execute(select(func.count()).select_from(WorkItem).where(*wi_conds))
    done_q = await db.execute(
        select(func.count()).select_from(WorkItem).where(*wi_conds, WorkItem.status.in_(["DONE", "CLOSED"]))
    )
    total = total_q.scalar() or 0
    done = done_q.scalar() or 0
    completion_pct = round((done / total * 100) if total > 0 else 0, 1)

    # Active sprint info
    iter_conds = [Iteration.organization_id == org_id]
    if project_id:
        iter_conds.append(Iteration.imported_project_id == project_id)
    active_iter = await db.execute(
        select(Iteration).where(*iter_conds, Iteration.state == "active")
        .order_by(Iteration.start_date.desc()).limit(1)
    )
    active = active_iter.scalar_one_or_none()
    sprint_info = None
    if active and active.end_date:
        end = active.end_date.replace(tzinfo=timezone.utc) if active.end_date.tzinfo is None else active.end_date
        days_left = max(0, (end - now).days)
        sprint_info = {"name": active.name, "days_remaining": days_left}

    # Risk items
    risk_q = await db.execute(
        select(func.count()).select_from(WorkItem).where(
            *wi_conds,
            WorkItem.spillover_risk.in_(["high", "critical"]),
        )
    )
    risk_count = risk_q.scalar() or 0

    # AI insight
    ai_insight = None
    if project_id:
        plan_q = await db.execute(
            select(SprintPlan.overall_rationale, SprintPlan.success_probability).where(
                SprintPlan.organization_id == org_id,
                SprintPlan.project_id == project_id,
                SprintPlan.status != "REJECTED",
            ).order_by(SprintPlan.created_at.desc()).limit(1)
        )
        plan_row = plan_q.first()
        if plan_row and plan_row[0]:
            ai_insight = plan_row[0][:200]

    return {
        "period": f"{week_ago.strftime('%b %d')} — {now.strftime('%b %d, %Y')}",
        "generated_at": now.isoformat(),
        "completion_pct": completion_pct,
        "items_completed": len(completed_items),
        "completed_sp": completed_sp,
        "completed_titles": [i["title"] for i in completed_items[:10]],
        "items_started": started_count,
        "sprint": sprint_info,
        "risk_items": risk_count,
        "ai_insight": ai_insight,
        "total_items": total,
        "done_items": done,
    }


@router.get("/export/weekly")
async def get_weekly_report(
    projectId: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest weekly digest."""
    org_id = current_user.get("organization_id", "demo-org")
    return await _generate_weekly_digest(db, org_id, projectId)


@router.post("/export/weekly/generate")
async def generate_weekly_report(
    body: dict | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Force-generate a weekly report now."""
    org_id = current_user.get("organization_id", "demo-org")
    project_id = (body or {}).get("projectId")
    return await _generate_weekly_digest(db, org_id, project_id)

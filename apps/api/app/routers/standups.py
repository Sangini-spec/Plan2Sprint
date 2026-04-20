"""
GET|POST|PATCH /api/standups
Standup digest retrieval, note submission, and notes-by-date lookup.
Queries real data from StandupReport, TeamStandupDigest, BlockerFlag tables.

POST /api/standups/generate  — auto-generate standups from synced work items/PRs

Response format matches the Next.js frontend expectations:
- GET returns: id, organizationId, iterationId, digestDate, sprintPacing,
  acknowledgedPct, sprintHealth, blockerCount, summaryText, atRiskItems,
  individualReports, submittedNotes
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import date, datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from ..auth.supabase import get_current_user
from ..database import get_db
from ..models import StandupReport, TeamStandupDigest, BlockerFlag, TeamMember
from ..models.work_item import WorkItem
from ..services.ws_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_individual_reports(reports: list) -> list[dict]:
    """Build individualReports array from StandupReport rows."""
    individual_reports = []
    for r in reports:
        blockers = []
        for bf in (r.blocker_flags if hasattr(r, "blocker_flags") and r.blocker_flags else []):
            blockers.append({
                "description": bf.description,
                "status": bf.status,
            })

        # Also include inline blockers from the JSON field
        if isinstance(r.blockers, list):
            for b in r.blockers:
                if isinstance(b, dict):
                    blockers.append({
                        "description": b.get("description", str(b)),
                        "status": b.get("status", "OPEN"),
                    })
                elif isinstance(b, str):
                    blockers.append({"description": b, "status": "OPEN"})

        completed = r.completed_items if isinstance(r.completed_items, list) else []
        in_progress = r.in_progress_items if isinstance(r.in_progress_items, list) else []

        individual_reports.append({
            "teamMemberId": r.team_member_id,
            "displayName": r.team_member.display_name if r.team_member else "Unknown",
            "avatarUrl": r.team_member.avatar_url if r.team_member else None,
            "acknowledged": r.acknowledged,
            "isInactive": r.is_inactive,
            "completedCount": len(completed),
            "inProgressCount": len(in_progress),
            "blockerCount": len(blockers),
            "completed": completed,
            "inProgress": in_progress,
            "blockers": blockers,
            "narrativeText": r.narrative_text or "",
            "reportDate": r.report_date.isoformat() if r.report_date else None,
            "teamMember": r.team_member.display_name if r.team_member else "Unknown",
        })

    return individual_reports


def _build_submitted_notes(
    reports: list,
    query_date: str,
    current_user_email: str = "",
    current_user_name: str = "",
) -> list[dict]:
    """Build submittedNotes array from reports with developer_note.

    If current_user_email matches the team member's email, use the logged-in
    user's name (from JWT) instead of the team_member.display_name, which may
    be stale or incorrectly linked.
    """
    submitted_notes = []
    for r in reports:
        if r.developer_note:
            # Determine author name: prefer the logged-in user's name if this
            # is their own report (match by email).
            author = r.team_member.display_name if r.team_member else "Unknown"
            if (
                current_user_email
                and r.team_member
                and r.team_member.email
                and r.team_member.email.lower() == current_user_email.lower()
                and current_user_name
            ):
                author = current_user_name

            submitted_notes.append({
                "id": r.id,
                "date": r.report_date.date().isoformat() if r.report_date else query_date,
                "author": author,
                "authorRole": "developer",
                "note": r.developer_note,
                "submittedAt": r.created_at.isoformat() if r.created_at else None,
            })
    return submitted_notes


# ---------------------------------------------------------------------------
# GET /api/standups — Retrieve standup digest + reports
# ---------------------------------------------------------------------------

@router.get("/standups")
async def get_standup_digest(
    date_param: str | None = Query(None, alias="date"),
    auto_generate: bool = Query(True, alias="autoGenerate"),
    project_id: str | None = Query(None, alias="projectId"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")
    today = date.today()
    query_date = date_param or today.isoformat()

    # If requesting today's data and auto_generate is on, generate if needed
    is_today_request = query_date == today.isoformat()
    if is_today_request and auto_generate and today.weekday() not in (5, 6):
        # Check if we have any generated reports for today
        count_q = await db.execute(
            select(func.count()).select_from(StandupReport).where(
                StandupReport.organization_id == org_id,
                func.date(StandupReport.report_date) == today,
            )
        )
        report_count = count_q.scalar() or 0
        if report_count == 0:
            # Auto-generate
            try:
                from ..services.standup_generator import generate_all_standups
                result = await generate_all_standups(db, org_id)
                logger.info(f"Auto-generated standups for {org_id}: {result}")
            except Exception as e:
                logger.warning(f"Auto-generation failed: {e}")

    # Get digest for the date
    digest_query = (
        select(TeamStandupDigest)
        .where(TeamStandupDigest.organization_id == org_id)
        .order_by(TeamStandupDigest.digest_date.desc())
        .limit(1)
    )
    if is_today_request:
        digest_query = digest_query.where(
            func.date(TeamStandupDigest.digest_date) == today
        )
    digest_result = await db.execute(digest_query)
    digest = digest_result.scalar_one_or_none()

    # Get standup reports with team member info and blocker flags
    reports_query = (
        select(StandupReport)
        .where(StandupReport.organization_id == org_id)
        .options(
            selectinload(StandupReport.team_member),
            selectinload(StandupReport.blocker_flags),
        )
        .order_by(StandupReport.report_date.desc())
    )

    # Filter by date if provided
    if date_param:
        try:
            filter_date = date.fromisoformat(date_param)
            reports_query = reports_query.where(
                func.date(StandupReport.report_date) == filter_date
            )
        except ValueError:
            pass

    reports_query = reports_query.limit(50)
    reports_result = await db.execute(reports_query)
    reports = reports_result.scalars().all()

    # ── Project-scoped filtering ──
    # If projectId is provided, load that project's work-item ticket IDs and
    # filter each report's completed / in_progress / blockers to only include
    # items belonging to the selected project.
    project_ticket_ids: set[str] | None = None
    if project_id:
        wi_q = await db.execute(
            select(WorkItem.external_id).where(
                WorkItem.imported_project_id == project_id,
            )
        )
        project_ticket_ids = {r[0] for r in wi_q.all() if r[0]}

    if project_ticket_ids is not None:
        for r in reports:
            if isinstance(r.completed_items, list):
                r.completed_items = [
                    item for item in r.completed_items
                    if isinstance(item, dict) and item.get("ticketId") in project_ticket_ids
                ]
            if isinstance(r.in_progress_items, list):
                r.in_progress_items = [
                    item for item in r.in_progress_items
                    if isinstance(item, dict) and item.get("ticketId") in project_ticket_ids
                ]
            # Blockers may or may not have ticketIds — keep those that match or have no ticketId
            if isinstance(r.blockers, list):
                r.blockers = [
                    b for b in r.blockers
                    if (isinstance(b, dict) and (not b.get("ticketId") or b.get("ticketId") in project_ticket_ids))
                    or isinstance(b, str)
                ]

    individual_reports = _build_individual_reports(reports)
    submitted_notes = _build_submitted_notes(
        reports,
        query_date,
        current_user_email=(current_user.get("email") or "").lower(),
        current_user_name=current_user.get("full_name") or "",
    )

    # Build the full response matching the Next.js format
    response = {
        "id": digest.id if digest else "digest-0",
        "organizationId": org_id,
        "iterationId": digest.iteration_id if digest else None,
        "digestDate": query_date,
        "sprintPacing": digest.sprint_pacing if digest else 0,
        "acknowledgedPct": digest.acknowledged_pct if digest else 0,
        "sprintHealth": digest.sprint_health if digest else "GREEN",
        "blockerCount": digest.blocker_count if digest else 0,
        "summaryText": digest.summary_text if digest else "No standup data yet. Sync project data to auto-generate standups.",
        "atRiskItems": digest.at_risk_items if digest else {"items": []},
        "individualReports": individual_reports,
        "submittedNotes": submitted_notes,
        # Backward compat
        "date": query_date,
        "digest": {
            "sprintPacing": digest.sprint_pacing if digest else 0,
            "acknowledgedPct": digest.acknowledged_pct if digest else 0,
            "sprintHealth": digest.sprint_health if digest else "GREEN",
            "blockerCount": digest.blocker_count if digest else 0,
            "summaryText": digest.summary_text if digest else "No standup data yet.",
        },
        "reports": individual_reports,
    }

    return response


# ---------------------------------------------------------------------------
# POST /api/standups/generate — Trigger standup generation
# ---------------------------------------------------------------------------

@router.post("/standups/generate")
async def trigger_standup_generation(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger standup report generation from synced data."""
    org_id = current_user.get("organization_id", "demo-org")

    from ..services.standup_generator import generate_all_standups
    result = await generate_all_standups(db, org_id)

    # Broadcast standup generation event
    await ws_manager.broadcast(org_id, {
        "type": "standup_generated",
        "data": {
            "reportsGenerated": result.get("reports_generated", 0),
            "date": date.today().isoformat(),
        },
    })

    return {
        "ok": True,
        **result,
    }


# ---------------------------------------------------------------------------
# POST /api/standups — Submit a standup note
# ---------------------------------------------------------------------------

@router.post("/standups")
async def submit_standup_note(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    if today.weekday() in (5, 6):
        raise HTTPException(
            status_code=400,
            detail="Standup notes cannot be submitted on weekends",
        )

    note = body.get("note", "").strip()
    # Author name: prefer what the frontend sends, then JWT full_name
    author = body.get("author") or current_user.get("full_name") or "Unknown"
    author_role = body.get("authorRole") or current_user.get("role") or "developer"

    if not note:
        raise HTTPException(status_code=400, detail="Note cannot be empty")

    # Find team member for the current user (match by email, not just org)
    org_id = current_user.get("organization_id", "demo-org")
    user_email = (current_user.get("email") or "").lower()
    member_query = (
        select(TeamMember)
        .where(
            TeamMember.organization_id == org_id,
            TeamMember.email.ilike(user_email),
        )
        .limit(1)
    )
    member_result = await db.execute(member_query)
    member = member_result.scalar_one_or_none()

    # Fallback: if no email match, try by org only (for users not yet email-mapped)
    if not member and user_email:
        fallback_q = (
            select(TeamMember)
            .where(TeamMember.organization_id == org_id)
            .limit(1)
        )
        fallback_result = await db.execute(fallback_q)
        member = fallback_result.scalar_one_or_none()

    if member:
        # Check for existing report today — append note to it
        existing_q = await db.execute(
            select(StandupReport).where(
                StandupReport.organization_id == org_id,
                StandupReport.team_member_id == member.id,
                func.date(StandupReport.report_date) == today,
            )
        )
        report = existing_q.scalar_one_or_none()

        if report:
            # Append note to existing report
            if report.developer_note:
                report.developer_note = f"{report.developer_note}\n---\n{note}"
            else:
                report.developer_note = note
            await db.commit()
            await db.refresh(report)
        else:
            report = StandupReport(
                organization_id=org_id,
                team_member_id=member.id,
                report_date=datetime.now(timezone.utc),
                completed_items=[],
                in_progress_items=[note],
                blockers=[],
                narrative_text=note,
                acknowledged=False,
                developer_note=note,
            )
            db.add(report)
            await db.commit()
            await db.refresh(report)

        # Notify PO and broadcast WebSocket event
        try:
            await ws_manager.broadcast(org_id, {
                "type": "standup_note_submitted",
                "data": {"author": author, "date": today.isoformat()},
            })
        except Exception:
            pass

        try:
            from ..services.delivery_queue import enqueue_notification
            from ..services import card_builders
            from .notifications import get_po_email

            po_email = await get_po_email(db, org_id)
            if po_email:
                await enqueue_notification(
                    org_id=org_id,
                    recipient_email=po_email,
                    notification_type="standup_report",
                    in_app_payload={
                        "title": "Standup Note Submitted",
                        "body": f"{author} submitted a standup note",
                        "type": "standup_report",
                    },
                )
        except Exception as e:
            logger.warning(f"Standup notification failed: {e}")

        return {
            "success": True,
            "entry": {
                "id": report.id,
                "note": note,
                "author": author,
                "authorRole": author_role,
                "date": today.isoformat(),
                "submittedAt": report.created_at.isoformat() if report.created_at else datetime.now(timezone.utc).isoformat(),
            },
        }

    return {
        "success": True,
        "entry": {
            "id": f"note-{int(datetime.now(timezone.utc).timestamp())}",
            "note": note,
            "author": author,
            "authorRole": author_role,
            "date": today.isoformat(),
            "submittedAt": datetime.now(timezone.utc).isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# POST /api/standups/blocker — Flag a blocker
# ---------------------------------------------------------------------------

@router.post("/standups/blocker")
async def flag_blocker(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /api/standups/blocker
    Flag a new blocker. Creates a BlockerFlag and notifies the PO via Slack/Teams.
    """
    org_id = current_user.get("organization_id", "demo-org")
    description = body.get("description", "").strip()
    ticket_ref = body.get("ticketReference", "")
    ticket_title = body.get("ticketTitle", "")
    report_id = body.get("reportId")

    if not description:
        raise HTTPException(status_code=400, detail="Blocker description is required")

    # Find the developer's team member record
    member_query = (
        select(TeamMember)
        .where(TeamMember.organization_id == org_id)
        .limit(1)
    )
    member_result = await db.execute(member_query)
    member = member_result.scalar_one_or_none()
    dev_name = member.display_name if member else current_user.get("full_name", "A developer")

    # If no report_id provided, find or create a standup report for today
    if not report_id and member:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
        existing_report = await db.execute(
            select(StandupReport).where(
                StandupReport.organization_id == org_id,
                StandupReport.team_member_id == member.id,
                StandupReport.report_date >= today_start,
            ).limit(1)
        )
        report = existing_report.scalar_one_or_none()
        if report:
            report_id = report.id
        else:
            new_report = StandupReport(
                organization_id=org_id,
                team_member_id=member.id,
                report_date=datetime.now(timezone.utc),
                completed_items=[],
                in_progress_items=[],
                blockers=[description],
                narrative_text=f"Blocker flagged: {description}",
                acknowledged=False,
            )
            db.add(new_report)
            await db.flush()
            report_id = new_report.id

    if not report_id:
        raise HTTPException(status_code=400, detail="Cannot create blocker without a standup report context")

    # Create the blocker flag
    blocker = BlockerFlag(
        standup_report_id=report_id,
        description=description,
        ticket_reference=ticket_ref or None,
        status="OPEN",
    )
    db.add(blocker)
    await db.commit()
    await db.refresh(blocker)

    # ── Notification trigger: notify PO ──
    try:
        from ..services.delivery_queue import enqueue_notification
        from ..services import card_builders
        from .notifications import get_po_email

        po_email = await get_po_email(db, org_id)
        if po_email:
            await enqueue_notification(
                org_id=org_id,
                recipient_email=po_email,
                notification_type="blocker_alert",
                slack_payload=card_builders.slack_blocker_alert(
                    dev_name=dev_name,
                    ticket_key=ticket_ref or "N/A",
                    ticket_title=ticket_title or description[:50],
                    blocker_description=description,
                    days_blocked=0,
                    blocker_id=blocker.id,
                    org_id=org_id,
                ),
                teams_payload=card_builders.teams_blocker_alert(
                    dev_name=dev_name,
                    ticket_key=ticket_ref or "N/A",
                    ticket_title=ticket_title or description[:50],
                    blocker_description=description,
                    days_blocked=0,
                ),
            )
            logger.info(f"Queued blocker_alert notification -> {po_email}")
    except Exception as e:
        logger.warning(f"Notification trigger error: {e}")

    return {
        "success": True,
        "blocker": {
            "id": blocker.id,
            "description": description,
            "ticketReference": ticket_ref,
            "status": "OPEN",
            "flaggedAt": blocker.flagged_at.isoformat() if blocker.flagged_at else None,
        },
    }


# ---------------------------------------------------------------------------
# PATCH /api/standups — Get notes by date
# ---------------------------------------------------------------------------

@router.patch("/standups")
async def get_notes_by_date(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("organization_id", "demo-org")
    query_date = body.get("date", date.today().isoformat())

    reports_query = (
        select(StandupReport)
        .where(StandupReport.organization_id == org_id)
        .options(selectinload(StandupReport.team_member))
        .order_by(StandupReport.report_date.desc())
    )

    # Filter by date
    try:
        filter_date = date.fromisoformat(query_date)
        reports_query = reports_query.where(
            func.date(StandupReport.report_date) == filter_date
        )
    except ValueError:
        pass

    reports_result = await db.execute(reports_query)
    reports = reports_result.scalars().all()

    notes = []
    for r in reports:
        if r.developer_note:
            notes.append({
                "id": r.id,
                "note": r.developer_note,
                "author": r.team_member.display_name if r.team_member else "Unknown",
                "authorRole": "developer",
                "date": r.report_date.date().isoformat() if r.report_date else query_date,
                "submittedAt": r.created_at.isoformat() if r.created_at else None,
            })

    return {"date": query_date, "notes": notes}


# ---------------------------------------------------------------------------
# GET /api/blockers/my — Recent blockers raised by the logged-in developer
# ---------------------------------------------------------------------------

@router.get("/blockers/my")
async def list_my_blockers(
    project_id: str | None = Query(None, alias="projectId"),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current developer's recent blockers with their live status.

    Powers the "Blocker History" list under the dev's Update About Your Blockers
    form. Status is one of OPEN / ACKNOWLEDGED / ESCALATED / RESOLVED.
    """
    org_id = current_user.get("organization_id", "demo-org")
    user_email = (current_user.get("email") or "").lower()

    # Find all TeamMember rows for this user in this org (they may have multiple — one per project)
    tm_q = await db.execute(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
            TeamMember.email.ilike(user_email),
        )
    )
    team_members = list(tm_q.scalars().all())
    if not team_members:
        return {"blockers": []}

    tm_ids = [tm.id for tm in team_members]

    # Join BlockerFlag → StandupReport to filter by team_member_id
    blockers_q = (
        select(BlockerFlag, StandupReport)
        .join(StandupReport, BlockerFlag.standup_report_id == StandupReport.id)
        .where(StandupReport.team_member_id.in_(tm_ids))
        .order_by(BlockerFlag.flagged_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(blockers_q)).all()

    # Optional project filter — include blockers from team_members that either
    # belong to the given project OR have no project assignment (self-created
    # team_members from blocker-flag path).
    project_tm_ids: set[str] | None = None
    if project_id:
        project_tm_ids = {
            tm.id for tm in team_members
            if tm.imported_project_id == project_id or tm.imported_project_id is None
        }

    blockers = []
    for b, r in rows:
        if project_tm_ids is not None and r.team_member_id not in project_tm_ids:
            continue
        blockers.append({
            "id": b.id,
            "ticket": b.ticket_reference or "",
            "description": b.description or "",
            "status": (b.status or "OPEN").upper(),
            "flaggedAt": b.flagged_at.isoformat() if b.flagged_at else None,
            "resolvedAt": b.resolved_at.isoformat() if b.resolved_at else None,
        })

    return {"blockers": blockers}

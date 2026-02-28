"""
Standup Generator — builds standup reports from real synced data.

For each team member it queries:
  - Work items recently moved to DONE  → "completed"
  - Work items currently IN_PROGRESS   → "in progress"
  - PRs opened / merged / in review    → added to completed or in-progress
  - Commits since last standup          → context for narrative
  - Open BlockerFlags                   → "blockers"

Then generates a narrative summary and upserts StandupReport + TeamStandupDigest.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta, date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, case

from ..models.standup import StandupReport, TeamStandupDigest, BlockerFlag
from ..models.work_item import WorkItem
from ..models.team_member import TeamMember
from ..models.iteration import Iteration
from ..models.repository import PullRequest, Commit

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _since_cutoff(last_report_date: datetime | None) -> datetime:
    """Determine the cutoff time for 'recent' activity.
    If there's a previous report, use that date; otherwise look back 24h."""
    if last_report_date:
        return last_report_date
    return datetime.now(timezone.utc) - timedelta(hours=24)


def _build_narrative(
    member_name: str,
    completed: list[dict],
    in_progress: list[dict],
    blockers: list[dict],
    pr_activity: list[dict],
    commit_count: int,
) -> str:
    """Build a readable narrative text from structured standup data."""
    parts: list[str] = []

    # Opening
    if completed:
        titles = ", ".join(c["title"][:40] for c in completed[:3])
        suffix = f" and {len(completed) - 3} more" if len(completed) > 3 else ""
        parts.append(f"{member_name} completed {titles}{suffix}.")
    else:
        parts.append(f"{member_name} has no newly completed items.")

    # In progress
    if in_progress:
        titles = ", ".join(ip["title"][:40] for ip in in_progress[:3])
        suffix = f" and {len(in_progress) - 3} more" if len(in_progress) > 3 else ""
        parts.append(f"Currently working on {titles}{suffix}.")

    # PR activity
    if pr_activity:
        open_prs = [p for p in pr_activity if p.get("status") == "OPEN"]
        merged_prs = [p for p in pr_activity if p.get("status") == "MERGED"]
        if merged_prs:
            parts.append(f"{len(merged_prs)} PR{'s' if len(merged_prs) > 1 else ''} merged.")
        if open_prs:
            parts.append(f"{len(open_prs)} open PR{'s' if len(open_prs) > 1 else ''} awaiting review.")

    # Commits
    if commit_count > 0:
        parts.append(f"{commit_count} commit{'s' if commit_count > 1 else ''} pushed.")

    # Blockers
    if blockers:
        parts.append(f"⚠ {len(blockers)} blocker{'s' if len(blockers) > 1 else ''} reported.")

    return " ".join(parts)


def _to_standup_item(
    title: str,
    ticket_id: str | None = None,
    pr_id: str | None = None,
    pr_status: str | None = None,
) -> dict:
    """Build a StandupReportItem-shaped dict."""
    item: dict[str, Any] = {"title": title}
    if ticket_id:
        item["ticketId"] = ticket_id
    if pr_id:
        item["prId"] = pr_id
    if pr_status:
        item["prStatus"] = pr_status
    return item


# ---------------------------------------------------------------------------
# Per-member generation
# ---------------------------------------------------------------------------

async def generate_member_standup(
    db: AsyncSession,
    member: TeamMember,
    org_id: str,
    since: datetime,
    active_iteration_id: str | None = None,
) -> StandupReport | None:
    """Generate or update a standup report for a single team member."""
    today = date.today()

    # ── 1. Completed items: work items moved to DONE since last standup ──
    done_query = (
        select(WorkItem)
        .where(
            WorkItem.assignee_id == member.id,
            WorkItem.status == "DONE",
            WorkItem.updated_at >= since,
        )
        .order_by(WorkItem.updated_at.desc())
        .limit(20)
    )
    done_result = await db.execute(done_query)
    done_items = done_result.scalars().all()

    completed = [
        _to_standup_item(
            title=wi.title,
            ticket_id=wi.external_id,
        )
        for wi in done_items
    ]

    # ── 2. In-progress items ──
    ip_query = (
        select(WorkItem)
        .where(
            WorkItem.assignee_id == member.id,
            WorkItem.status.in_(["IN_PROGRESS", "IN_REVIEW"]),
        )
        .order_by(WorkItem.priority.asc(), WorkItem.updated_at.desc())
        .limit(20)
    )
    ip_result = await db.execute(ip_query)
    ip_items = ip_result.scalars().all()

    in_progress = [
        _to_standup_item(
            title=wi.title,
            ticket_id=wi.external_id,
        )
        for wi in ip_items
    ]

    # ── 3. PR activity ──
    pr_query = (
        select(PullRequest)
        .where(
            PullRequest.author_id == member.id,
            PullRequest.created_external_at >= since,
        )
        .order_by(PullRequest.created_external_at.desc())
        .limit(10)
    )
    pr_result = await db.execute(pr_query)
    prs = pr_result.scalars().all()

    pr_activity: list[dict] = []
    for pr in prs:
        pr_item = {
            "title": pr.title,
            "number": pr.number,
            "status": pr.status,
            "url": pr.url,
        }
        pr_activity.append(pr_item)

        # Merged PRs → add to completed
        if pr.status == "MERGED" or pr.merged_at:
            completed.append(_to_standup_item(
                title=f"PR #{pr.number}: {pr.title}",
                pr_id=str(pr.number),
                pr_status="MERGED",
            ))
        # Open PRs → add to in-progress
        elif pr.status in ("OPEN", "AWAITING_REVIEW", "CHANGES_REQUESTED"):
            in_progress.append(_to_standup_item(
                title=f"PR #{pr.number}: {pr.title}",
                pr_id=str(pr.number),
                pr_status=pr.status,
            ))

    # ── 4. Commits ──
    commit_count_result = await db.execute(
        select(func.count())
        .select_from(Commit)
        .where(
            Commit.author_id == member.id,
            Commit.committed_at >= since,
        )
    )
    commit_count = commit_count_result.scalar() or 0

    # ── 5. Blockers ──
    # Check for any open blocker flags from recent standup reports
    blocker_query = (
        select(BlockerFlag)
        .join(StandupReport, BlockerFlag.standup_report_id == StandupReport.id)
        .where(
            StandupReport.team_member_id == member.id,
            StandupReport.organization_id == org_id,
            BlockerFlag.status.in_(["OPEN", "ACKNOWLEDGED", "ESCALATED"]),
        )
        .limit(10)
    )
    blocker_result = await db.execute(blocker_query)
    blocker_flags = blocker_result.scalars().all()

    blockers = [
        {
            "description": bf.description,
            "ticketId": bf.ticket_reference,
            "status": bf.status,
        }
        for bf in blocker_flags
    ]

    # ── Skip if no activity at all ──
    if not completed and not in_progress and not blockers and commit_count == 0:
        # Mark member as inactive for the day
        return None

    # ── 6. Build narrative ──
    narrative = _build_narrative(
        member_name=member.display_name,
        completed=completed,
        in_progress=in_progress,
        blockers=blockers,
        pr_activity=pr_activity,
        commit_count=commit_count,
    )

    # ── 7. Upsert StandupReport ──
    # Check if report exists for today
    existing_query = (
        select(StandupReport)
        .where(
            StandupReport.organization_id == org_id,
            StandupReport.team_member_id == member.id,
            func.date(StandupReport.report_date) == today,
        )
    )
    existing_result = await db.execute(existing_query)
    report = existing_result.scalar_one_or_none()

    if report:
        # Update existing report with generated data
        report.completed_items = completed
        report.in_progress_items = in_progress
        report.blockers = blockers
        report.narrative_text = narrative
        report.iteration_id = active_iteration_id
    else:
        report = StandupReport(
            organization_id=org_id,
            team_member_id=member.id,
            iteration_id=active_iteration_id,
            report_date=datetime.now(timezone.utc),
            completed_items=completed,
            in_progress_items=in_progress,
            blockers=blockers,
            narrative_text=narrative,
            acknowledged=False,
            is_inactive=False,
        )
        db.add(report)

    return report


# ---------------------------------------------------------------------------
# Team digest generation
# ---------------------------------------------------------------------------

async def generate_team_digest(
    db: AsyncSession,
    org_id: str,
    reports: list[StandupReport],
    active_iteration_id: str | None = None,
) -> TeamStandupDigest:
    """Generate or update the team standup digest for today."""
    today = date.today()
    now = datetime.now(timezone.utc)

    # Compute metrics
    total_reports = len(reports)
    acknowledged = sum(1 for r in reports if r.acknowledged)
    ack_pct = int((acknowledged / total_reports) * 100) if total_reports > 0 else 0

    total_blockers = 0
    for r in reports:
        if isinstance(r.blockers, list):
            total_blockers += len(r.blockers)

    # Sprint pacing: compute from active iteration
    sprint_pacing = 0.0
    if active_iteration_id:
        # Count done vs total in the iteration
        total_q = await db.execute(
            select(func.count()).select_from(WorkItem)
            .where(WorkItem.iteration_id == active_iteration_id)
        )
        total_items = total_q.scalar() or 1

        done_q = await db.execute(
            select(func.count()).select_from(WorkItem)
            .where(
                WorkItem.iteration_id == active_iteration_id,
                WorkItem.status == "DONE",
            )
        )
        done_items = done_q.scalar() or 0

        # Also factor in time elapsed
        iter_result = await db.execute(
            select(Iteration).where(Iteration.id == active_iteration_id)
        )
        iteration = iter_result.scalar_one_or_none()
        if iteration and iteration.start_date and iteration.end_date:
            total_days = (iteration.end_date - iteration.start_date).days or 1
            elapsed = (now - iteration.start_date).days
            time_pct = min(elapsed / total_days, 1.0)
            work_pct = done_items / total_items
            sprint_pacing = int((work_pct / max(time_pct, 0.01)) * 100)
            sprint_pacing = min(sprint_pacing, 120)
        else:
            sprint_pacing = int((done_items / total_items) * 100)

    # Sprint health
    if sprint_pacing >= 80 and total_blockers == 0:
        sprint_health = "GREEN"
    elif sprint_pacing >= 50 or total_blockers <= 1:
        sprint_health = "AMBER"
    else:
        sprint_health = "RED"

    # At-risk items: items overdue or blocked
    at_risk_items: list[dict] = []
    at_risk_q = await db.execute(
        select(WorkItem)
        .where(
            WorkItem.organization_id == org_id,
            WorkItem.status.in_(["IN_PROGRESS", "TODO"]),
        )
        .order_by(WorkItem.priority.asc())
        .limit(5)
    )
    for wi in at_risk_q.scalars().all():
        # Flag items that are high priority and not done
        if wi.priority <= 2:
            at_risk_items.append({
                "workItemId": wi.external_id,
                "reason": f"High priority ({wi.type}) still {wi.status.lower().replace('_', ' ')}",
            })

    # Summary text
    summary_parts: list[str] = []
    total_completed = sum(
        len(r.completed_items) if isinstance(r.completed_items, list) else 0
        for r in reports
    )
    total_in_progress = sum(
        len(r.in_progress_items) if isinstance(r.in_progress_items, list) else 0
        for r in reports
    )
    summary_parts.append(f"Team completed {total_completed} items and has {total_in_progress} in progress.")
    if total_blockers > 0:
        summary_parts.append(f"{total_blockers} blocker{'s' if total_blockers > 1 else ''} require attention.")
    if sprint_pacing > 0:
        summary_parts.append(f"Sprint pacing is at {sprint_pacing}%.")

    summary_text = " ".join(summary_parts)

    # Upsert digest
    existing_q = await db.execute(
        select(TeamStandupDigest).where(
            TeamStandupDigest.organization_id == org_id,
            func.date(TeamStandupDigest.digest_date) == today,
        )
    )
    digest = existing_q.scalar_one_or_none()

    if digest:
        digest.sprint_pacing = sprint_pacing
        digest.acknowledged_pct = ack_pct
        digest.sprint_health = sprint_health
        digest.at_risk_items = {"items": at_risk_items}
        digest.blocker_count = total_blockers
        digest.summary_text = summary_text
        digest.iteration_id = active_iteration_id
    else:
        digest = TeamStandupDigest(
            organization_id=org_id,
            iteration_id=active_iteration_id,
            digest_date=now,
            sprint_pacing=sprint_pacing,
            acknowledged_pct=ack_pct,
            sprint_health=sprint_health,
            at_risk_items={"items": at_risk_items},
            blocker_count=total_blockers,
            summary_text=summary_text,
        )
        db.add(digest)

    return digest


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def generate_all_standups(
    db: AsyncSession,
    org_id: str,
) -> dict:
    """Generate standup reports for all team members in the org + team digest.

    Returns a summary dict with counts.
    """
    today = date.today()

    # Skip weekends
    if today.weekday() in (5, 6):
        return {"generated": 0, "skipped": "weekend"}

    # Find all team members
    member_result = await db.execute(
        select(TeamMember)
        .where(TeamMember.organization_id == org_id)
        .order_by(TeamMember.display_name)
    )
    members = member_result.scalars().all()

    if not members:
        return {"generated": 0, "skipped": "no_team_members"}

    # Find active iteration
    iter_result = await db.execute(
        select(Iteration)
        .where(
            Iteration.organization_id == org_id,
            Iteration.state == "active",
        )
        .order_by(Iteration.start_date.desc())
        .limit(1)
    )
    active_iter = iter_result.scalar_one_or_none()
    active_iteration_id = active_iter.id if active_iter else None

    # Determine "since" cutoff — last generated report for the org
    last_report_q = await db.execute(
        select(StandupReport.report_date)
        .where(StandupReport.organization_id == org_id)
        .order_by(StandupReport.report_date.desc())
        .limit(1)
    )
    last_report_row = last_report_q.scalar_one_or_none()
    since = _since_cutoff(last_report_row)

    # Generate per-member reports
    reports: list[StandupReport] = []
    generated = 0
    inactive = 0

    for member in members:
        try:
            report = await generate_member_standup(
                db=db,
                member=member,
                org_id=org_id,
                since=since,
                active_iteration_id=active_iteration_id,
            )
            if report:
                reports.append(report)
                generated += 1
            else:
                # Create inactive placeholder
                existing_q = await db.execute(
                    select(StandupReport).where(
                        StandupReport.organization_id == org_id,
                        StandupReport.team_member_id == member.id,
                        func.date(StandupReport.report_date) == today,
                    )
                )
                existing = existing_q.scalar_one_or_none()
                if not existing:
                    placeholder = StandupReport(
                        organization_id=org_id,
                        team_member_id=member.id,
                        iteration_id=active_iteration_id,
                        report_date=datetime.now(timezone.utc),
                        completed_items=[],
                        in_progress_items=[],
                        blockers=[],
                        narrative_text=f"{member.display_name} has no recent activity.",
                        acknowledged=False,
                        is_inactive=True,
                    )
                    db.add(placeholder)
                    reports.append(placeholder)
                inactive += 1
        except Exception as e:
            logger.warning(f"Failed to generate standup for {member.display_name}: {e}")

    # Generate team digest
    try:
        digest = await generate_team_digest(
            db=db,
            org_id=org_id,
            reports=reports,
            active_iteration_id=active_iteration_id,
        )
    except Exception as e:
        logger.warning(f"Failed to generate team digest: {e}")

    await db.commit()

    return {
        "generated": generated,
        "inactive": inactive,
        "totalMembers": len(members),
        "digestGenerated": True,
    }

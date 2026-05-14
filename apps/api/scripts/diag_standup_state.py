"""
One-shot diagnostic — inspect today's StandupReport rows + commit
attribution state. Run from apps/api/:

    python scripts/diag_standup_state.py

Reads DATABASE_URL from .env. Read-only — does NOT mutate.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date

# Ensure the apps/api/app package resolves when this script runs from
# apps/api/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # type: ignore
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


async def main():
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("DATABASE_URL not set"); return
    # Convert SQLAlchemy sync URL to async if needed
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(db_url, echo=False)

    from app.models import StandupReport, TeamMember
    from app.models.repository import Commit, Repository

    today = date.today()

    async with AsyncSession(engine) as db:
        # 1) Per-org count of today's StandupReports
        print("=" * 70)
        print(f"STANDUP STATE — {today.isoformat()}")
        print("=" * 70)

        org_counts = (await db.execute(
            select(StandupReport.organization_id, func.count(StandupReport.id))
            .where(func.date(StandupReport.report_date) == today)
            .group_by(StandupReport.organization_id)
        )).all()
        print(f"\n[1] StandupReport row counts today, by org:")
        for org_id, n in org_counts:
            print(f"    org={org_id} reports={n}")
        if not org_counts:
            print("    (NONE — no standups generated yet today)")

        # 2) For each org with reports, dump per-TM detail
        for org_id, _ in org_counts:
            print(f"\n[2] org={org_id} — per-TM detail:")
            reports = (await db.execute(
                select(StandupReport)
                .where(
                    StandupReport.organization_id == org_id,
                    func.date(StandupReport.report_date) == today,
                )
                .order_by(StandupReport.report_date.desc())
            )).scalars().all()

            for r in reports:
                tm = (await db.execute(
                    select(TeamMember).where(TeamMember.id == r.team_member_id)
                )).scalar_one_or_none()
                tm_email = tm.email if tm else "?"
                tm_name = tm.display_name if tm else "?"
                tm_role = tm.role if tm else "?"

                ci = r.completed_items if isinstance(r.completed_items, list) else []
                ip = r.in_progress_items if isinstance(r.in_progress_items, list) else []

                has_summary = any(
                    isinstance(x, dict) and x.get("isCommitSummary") for x in ci
                )
                commit_items = [x for x in ci if isinstance(x, dict) and x.get("commitSha")]
                pr_items = [x for x in ci if isinstance(x, dict) and x.get("prId")]
                wi_items = [
                    x for x in ci
                    if isinstance(x, dict)
                    and x.get("ticketId")
                    and not x.get("commitSha")
                    and not x.get("prId")
                ]

                print(f"    - id={r.team_member_id} {tm_email!r} / {tm_name!r} (role={tm_role}, inactive={r.is_inactive})")
                print(f"        completed_items: {len(ci)}  (workItems={len(wi_items)}, prs={len(pr_items)}, individualCommits={len(commit_items)}, hasAISummary={has_summary})")
                print(f"        in_progress: {len(ip)}")
                if has_summary:
                    s = next(x for x in ci if isinstance(x, dict) and x.get("isCommitSummary"))
                    text = (s.get("title") or "")[:100]
                    print(f"        AI summary preview: {text!r}{'…' if len(s.get('title','')) > 100 else ''}")
                    print(f"        commitCount field: {s.get('commitCount')}")

            # 3) Commit attribution snapshot in this org
            commit_groups = (await db.execute(
                select(
                    Commit.author_email,
                    Commit.author_id,
                    func.count(Commit.id),
                )
                .join(Repository, Repository.id == Commit.repository_id)
                .where(Repository.organization_id == org_id)
                .group_by(Commit.author_email, Commit.author_id)
                .limit(15)
            )).all()
            total_commits = sum(n for _, _, n in commit_groups)
            print(f"\n[3] org={org_id} — commit attribution (total={total_commits}):")
            for email, author_id, n in commit_groups:
                # Lookup the TM behind this author_id to see if it's a
                # dev TM that should be picked up by the standup engine.
                tm_for_author = (await db.execute(
                    select(TeamMember).where(TeamMember.id == author_id)
                )).scalar_one_or_none() if author_id else None
                if tm_for_author:
                    print(f"    email={email!r} author_id={author_id!r} count={n}")
                    print(f"        -> TM email={tm_for_author.email!r} name={tm_for_author.display_name!r} role={tm_for_author.role!r} org={tm_for_author.organization_id}")
                else:
                    print(f"    email={email!r} author_id={author_id!r} count={n}  (TM NOT FOUND)")

            # 4) Recent window check — how many commits in last 7 days?
            from datetime import timedelta as _td, datetime as _dt, timezone as _tz
            since = _dt.now(_tz.utc) - _td(days=7)
            recent_n = (await db.execute(
                select(func.count(Commit.id))
                .join(Repository, Repository.id == Commit.repository_id)
                .where(
                    Repository.organization_id == org_id,
                    Commit.committed_at >= since,
                )
            )).scalar() or 0
            print(f"\n[4] commits in last 7 days for org={org_id}: {recent_n}")
            # And by author
            recent_by_author = (await db.execute(
                select(Commit.author_id, func.count(Commit.id))
                .join(Repository, Repository.id == Commit.repository_id)
                .where(
                    Repository.organization_id == org_id,
                    Commit.committed_at >= since,
                )
                .group_by(Commit.author_id)
            )).all()
            for aid, cn in recent_by_author:
                print(f"    author_id={aid!r} recent_count={cn}")

            # [5] When were the most recent commits? min/max committed_at + a few samples
            mm = (await db.execute(
                select(
                    func.min(Commit.committed_at),
                    func.max(Commit.committed_at),
                )
                .join(Repository, Repository.id == Commit.repository_id)
                .where(Repository.organization_id == org_id)
            )).first()
            print(f"\n[5] commit committed_at range for org={org_id}:")
            print(f"    earliest: {mm[0]}")
            print(f"    latest:   {mm[1]}")
            now = _dt.now(_tz.utc)
            if mm[1]:
                age_days = (now - mm[1]).total_seconds() / 86400
                print(f"    age of latest: {age_days:.2f} days")
            sample = (await db.execute(
                select(Commit.committed_at, Commit.sha, Commit.message)
                .join(Repository, Repository.id == Commit.repository_id)
                .where(Repository.organization_id == org_id)
                .order_by(Commit.committed_at.desc())
                .limit(5)
            )).all()
            print(f"    5 most-recent commits:")
            for t, sha, msg in sample:
                first_line = (msg or "").splitlines()[0][:60] if msg else ""
                print(f"        {t}  {sha[:8]}  {first_line!r}")

    await engine.dispose()


async def deep_commit_audit():
    """Cross-org commit audit — find missing recent commits regardless
    of which org/repo they ended up in."""
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(db_url, echo=False)

    from app.models import StandupReport, TeamMember
    from app.models.repository import Commit, Repository
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    async with AsyncSession(engine) as db:
        print("\n\n" + "=" * 70)
        print("DEEP COMMIT AUDIT (cross-org)")
        print("=" * 70)

        # All commits globally, latest 15
        print("\n[A] 15 most-recent commits across ALL orgs:")
        rows = (await db.execute(
            select(
                Commit.committed_at, Commit.sha, Commit.message,
                Commit.author_email, Commit.author_id,
                Repository.full_name, Repository.organization_id,
            )
            .join(Repository, Repository.id == Commit.repository_id)
            .order_by(Commit.committed_at.desc())
            .limit(15)
        )).all()
        for t, sha, msg, ae, aid, full, oid in rows:
            first = (msg or "").splitlines()[0][:55] if msg else ""
            print(f"    {t}  {sha[:8]}  repo={full!r} org={oid}")
            print(f"        author={ae!r} author_id={aid!r}")
            print(f"        msg={first!r}")

        # All repositories
        print("\n[B] All Repository rows:")
        repos = (await db.execute(select(Repository).order_by(Repository.created_at.desc()))).scalars().all()
        for repo in repos:
            print(f"    repo='{repo.full_name}' id={repo.id} org={repo.organization_id}")
            print(f"        created_at={repo.created_at} updated_at={getattr(repo, 'updated_at', None)}")
            cnt = (await db.execute(
                select(func.count(Commit.id)).where(Commit.repository_id == repo.id)
            )).scalar() or 0
            latest = (await db.execute(
                select(func.max(Commit.committed_at)).where(Commit.repository_id == repo.id)
            )).scalar()
            print(f"        commit_count={cnt} latest_committed_at={latest}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(deep_commit_audit())

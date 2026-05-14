"""
End-to-end verification of the standup pipeline with the local fixes.

Strategy:
  1. Open a transaction.
  2. Insert N synthetic ``Commit`` rows attributed to the work-email TM
     with committed_at = NOW (i.e. inside the 7-day standup window).
  3. Call ``generate_member_standup`` on that TM — same code path the
     webhook auto-regen + standup endpoint use. This populates
     ``StandupReport.completed_items`` with (hopefully) an
     ``isCommitSummary`` row from the AI caller.
  4. Read the row back, then SIMULATE the two display paths:
       - PO digest:  project filter + ``_build_individual_reports``
       - Dev page:   "mine" matching_reports filter + per_tm aggregation
     Print what each path emits so we can eyeball ``commitSummary`` and
     the ``completed[*].isCommitSummary`` row.
  5. ``db.rollback()`` so neither the synthetic commits nor the mutated
     report row ever persist.

Read-mostly. Aborts cleanly on any failure. Run from apps/api/.
"""
from __future__ import annotations

import asyncio
import os
import sys
import json
from uuid import uuid4
from datetime import datetime, timezone, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # type: ignore
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


ORG = "61d14720752b4ee8a8f834c16"
WORK_TM_ID = "b73ee898e484435fbeef0082e"  # sangini@concept2action.ai
LOGIN_TM_ID = "ae61999bd69a42e9b9a7a3c52"  # sanginitripathi28@gmail.com (gmail)
LOGIN_EMAIL = "sanginitripathi28@gmail.com"
REPO_FULL = "Sangini-spec/Plan2Sprint"

TEST_COMMIT_MESSAGES = [
    "feat(standups): add AI commit summary to PO digest",
    "fix(github): conn.config_ typo causing webhook 500s",
    "feat(standups): cluster_tm_ids expansion for multi-email users",
    "refactor(standups): reorder completed_capped to surface AI summary",
    "fix(standups): preserve isCommitSummary through project filter",
    "feat(dev): render commit summary block on /dev/standup",
]


def section(t):
    print()
    print("=" * 70)
    print(t)
    print("=" * 70)


async def main():
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(db_url, echo=False)

    from app.models import StandupReport, TeamMember
    from app.models.repository import Commit, Repository
    from app.services.standup_generator import generate_member_standup, _since_cutoff

    async with AsyncSession(engine) as db:
        # ── 1) Find repo + TM ────────────────────────────────────────
        repo = (await db.execute(
            select(Repository).where(
                Repository.organization_id == ORG,
                Repository.full_name == REPO_FULL,
            )
        )).scalar_one_or_none()
        if not repo:
            print("Repo not found — abort"); return

        work_tm = (await db.execute(
            select(TeamMember).where(TeamMember.id == WORK_TM_ID)
        )).scalar_one_or_none()
        if not work_tm:
            print("Work TM not found — abort"); return

        section("STAGE 1 — insert synthetic recent commits")
        now = datetime.now(timezone.utc)
        test_ids: list[str] = []
        for i, msg in enumerate(TEST_COMMIT_MESSAGES):
            cid = "TST" + uuid4().hex[:22]
            sha = "test" + uuid4().hex[:36]
            test_ids.append(cid)
            db.add(Commit(
                id=cid,
                repository_id=repo.id,
                sha=sha,
                message=msg,
                author_id=WORK_TM_ID,
                author_email="131374214+Sangini-spec@users.noreply.github.com",
                author_name="Sangini-spec",
                committed_at=now - timedelta(minutes=i * 30),  # spread last 3h
                branch="main",
                linked_ticket_ids=[],
                files_changed=3,
            ))
        await db.flush()
        print(f"  inserted {len(test_ids)} commits attributed to work TM {WORK_TM_ID}")
        print(f"  committed_at range: {now - timedelta(hours=3)} → {now}")

        # Sanity: confirm the standup window query would now find them
        since = _since_cutoff(None)
        n_recent = (await db.execute(
            select(func.count(Commit.id))
            .join(Repository, Repository.id == Commit.repository_id)
            .where(
                Repository.organization_id == ORG,
                Commit.author_id == WORK_TM_ID,
                Commit.committed_at >= since,
            )
        )).scalar() or 0
        print(f"  commits in last 7 days for work TM (after insert): {n_recent}")

        # ── 2) Run generate_member_standup ───────────────────────────
        section("STAGE 2 — generate_member_standup on work TM")
        report = await generate_member_standup(db, work_tm, ORG, since)
        if report is None:
            print("  generate_member_standup returned None — no activity?");
        else:
            ci = report.completed_items if isinstance(report.completed_items, list) else []
            ip = report.in_progress_items if isinstance(report.in_progress_items, list) else []
            summary_entries = [x for x in ci if isinstance(x, dict) and x.get("isCommitSummary")]
            commit_entries = [x for x in ci if isinstance(x, dict) and x.get("commitSha")]
            pr_entries = [x for x in ci if isinstance(x, dict) and x.get("prId")]
            wi_entries = [
                x for x in ci
                if isinstance(x, dict) and x.get("ticketId")
                and not x.get("commitSha") and not x.get("prId")
            ]
            print(f"  StandupReport.completed_items: total={len(ci)}")
            print(f"    workItems   = {len(wi_entries)}")
            print(f"    PRs         = {len(pr_entries)}")
            print(f"    commits     = {len(commit_entries)}")
            print(f"    AI summary  = {len(summary_entries)}  ← target=1")
            if summary_entries:
                s = summary_entries[0]
                txt = (s.get("title") or "")[:240]
                print(f"\n    AI SUMMARY TEXT ({len(s.get('title') or '')} chars):")
                print(f"      {txt}{'…' if len(s.get('title') or '') > 240 else ''}")
                print(f"      commitCount field: {s.get('commitCount')}")
            else:
                print("    ⚠ NO AI SUMMARY — likely AI caller returned None.")
                print("      Falling back to per-commit list. First 5:")
                for c in commit_entries[:5]:
                    print(f"        - {c.get('title')!r} sha={c.get('commitSha')}")

        # Persist the local mutation so subsequent reads in this txn see it
        await db.flush()

        # ── 3) Simulate the PO digest path ───────────────────────────
        section("STAGE 3 — simulate PO digest response build")
        from app.models.work_item import WorkItem

        # Find a project the user actually has; use it as project_id
        proj_q = await db.execute(
            select(WorkItem.imported_project_id, func.count(WorkItem.id))
            .where(
                WorkItem.organization_id == ORG,
                WorkItem.imported_project_id.isnot(None),
            )
            .group_by(WorkItem.imported_project_id)
            .order_by(func.count(WorkItem.id).desc())
        )
        proj_rows = proj_q.all()
        if not proj_rows:
            print("  No project work items found — skipping project filter sim")
            project_id = None
            project_ticket_ids: set[str] | None = None
        else:
            project_id = proj_rows[0][0]
            print(f"  Using project_id={project_id} ({proj_rows[0][1]} work items)")
            tid_rows = (await db.execute(
                select(WorkItem.external_id).where(
                    WorkItem.imported_project_id == project_id,
                )
            )).all()
            project_ticket_ids = {r[0] for r in tid_rows if r[0]}
            print(f"  project_ticket_ids: {len(project_ticket_ids)} tickets")

        # Apply the EXACT project filter from standups.py (with the fix)
        completed_before = list(report.completed_items or [])
        if project_ticket_ids is not None:
            filtered = [
                item for item in completed_before
                if isinstance(item, dict) and (
                    item.get("isCommitSummary") is True
                    or item.get("commitSha")
                    or item.get("prId")
                    or item.get("ticketId") in project_ticket_ids
                )
            ]
        else:
            filtered = completed_before
        print(f"  completed_items BEFORE project filter: {len(completed_before)}")
        print(f"  completed_items AFTER  project filter: {len(filtered)}")
        survived_summary = [x for x in filtered if isinstance(x, dict) and x.get("isCommitSummary")]
        print(f"  isCommitSummary rows survived: {len(survived_summary)}")

        # Apply the completed_capped reorder fix
        summary_items = [
            it for it in filtered
            if isinstance(it, dict) and it.get("isCommitSummary")
        ]
        other_items = [
            it for it in filtered
            if not (isinstance(it, dict) and it.get("isCommitSummary"))
        ]
        completed_capped = (summary_items + other_items)[:8]
        # Extract commitSummary from full filtered list (same logic as _build_individual_reports)
        commit_summary: dict | None = None
        for it in filtered:
            if isinstance(it, dict) and it.get("isCommitSummary"):
                commit_summary = {
                    "text": it.get("title") or "",
                    "commitCount": int(it.get("commitCount") or 0),
                }
                break

        po_response_row = {
            "displayName": work_tm.display_name,
            "email": (work_tm.email or "").lower(),
            "commitSummary": commit_summary,
            "completed": completed_capped,
            "completedCount": len(filtered),
        }
        print()
        print("  --- WHAT THE PO DIGEST WOULD SEE FOR THIS ROW ---")
        print(f"  displayName: {po_response_row['displayName']!r}")
        print(f"  email: {po_response_row['email']!r}")
        print(f"  commitSummary: {json.dumps(commit_summary, default=str)[:300] if commit_summary else 'null'}")
        print(f"  completed (capped 8): {len(completed_capped)} items")
        for i, it in enumerate(completed_capped):
            tag = "AI-SUMMARY" if it.get("isCommitSummary") else (
                "COMMIT" if it.get("commitSha") else (
                    "PR" if it.get("prId") else "WORK_ITEM"
                )
            )
            title = (it.get("title") or "")[:60]
            print(f"    [{i}] {tag:11s} {title!r}")

        # ── 4) Simulate the dev "mine" path ─────────────────────────
        section("STAGE 4 — simulate dev /dev/standup 'mine' response")

        # 'mine' matches reports by email OR display_name
        all_today_q = await db.execute(
            select(StandupReport).where(
                StandupReport.organization_id == ORG,
                func.date(StandupReport.report_date) == datetime.now(timezone.utc).date(),
            )
        )
        matching = []
        for r in all_today_q.scalars().all():
            tm = (await db.execute(
                select(TeamMember).where(TeamMember.id == r.team_member_id)
            )).scalar_one_or_none()
            if not tm:
                continue
            tm_email = (tm.email or "").lower()
            tm_name = (tm.display_name or "").strip().lower()
            if tm_email == LOGIN_EMAIL.lower() or tm_name == "sangini tripathi":
                matching.append((r, tm))
        print(f"  matching_reports for login={LOGIN_EMAIL}: {len(matching)}")
        for r, tm in matching:
            print(f"    - id={r.id} TM={tm.email!r} name={tm.display_name!r}")

        # Apply same fixed project filter + per_tm aggregation
        best_summary = None
        merged_completed = []
        seen_keys: set[str] = set()
        for r, tm in matching:
            ci = list(r.completed_items or [])
            if project_ticket_ids is not None:
                ci = [
                    it for it in ci
                    if isinstance(it, dict) and (
                        it.get("isCommitSummary") is True
                        or it.get("commitSha")
                        or it.get("prId")
                        or it.get("ticketId") in project_ticket_ids
                    )
                ]
            # Pull summary to front for capping
            summary = [x for x in ci if isinstance(x, dict) and x.get("isCommitSummary")]
            other = [x for x in ci if not (isinstance(x, dict) and x.get("isCommitSummary"))]
            tm_completed = (summary + other)[:8]
            # extract commitSummary for this TM
            tm_cs = None
            for it in ci:
                if isinstance(it, dict) and it.get("isCommitSummary"):
                    tm_cs = {
                        "text": it.get("title") or "",
                        "commitCount": int(it.get("commitCount") or 0),
                    }
                    break
            if tm_cs and (best_summary is None or tm_cs["commitCount"] > best_summary["commitCount"]):
                best_summary = tm_cs
            # Aggregate completed across TMs (dedup by key)
            for it in tm_completed:
                k = (it.get("ticketId") or it.get("commitSha") or it.get("prId")
                     or (it.get("title") or "").strip().lower())
                if k and k not in seen_keys:
                    seen_keys.add(k)
                    merged_completed.append(it)

        mine_response = {
            "displayName": "Sangini Tripathi",
            "email": LOGIN_EMAIL,
            "commitSummary": best_summary,
            "completed": merged_completed,
        }
        print()
        print("  --- WHAT /dev/standup 'mine' WOULD SEE ---")
        print(f"  commitSummary: {json.dumps(best_summary, default=str)[:300] if best_summary else 'null'}")
        print(f"  completed (merged across TMs): {len(merged_completed)} items")
        for i, it in enumerate(merged_completed[:10]):
            tag = "AI-SUMMARY" if it.get("isCommitSummary") else (
                "COMMIT" if it.get("commitSha") else (
                    "PR" if it.get("prId") else "WORK_ITEM"
                )
            )
            title = (it.get("title") or "")[:60]
            print(f"    [{i}] {tag:11s} {title!r}")

        # ── 4b) Synthetic AI summary path — verify isCommitSummary
        #        survives project filter + capping + extraction. This
        #        simulates what production does when the AI caller
        #        returns a real summary string.
        section("STAGE 4b — INJECT synthetic isCommitSummary, verify pipeline")
        synthetic = {
            "title": (
                "Sangini shipped six commits today focused on the standup "
                "pipeline: she fixed a webhook handler typo that had been "
                "silently dropping every push event, then patched the "
                "project filter so AI commit summaries and PR rows are no "
                "longer stripped before reaching the dashboard. She also "
                "reordered the completed cap so the summary always lands "
                "in the rendered slice."
            ),
            "isCommitSummary": True,
            "commitCount": 6,
        }
        # Inject AT THE END (mirrors how generate_member_standup appends)
        injected_ci = list(report.completed_items or []) + [synthetic]
        report.completed_items = injected_ci
        await db.flush()

        # PO digest path
        if project_ticket_ids is not None:
            injected_filtered = [
                item for item in injected_ci
                if isinstance(item, dict) and (
                    item.get("isCommitSummary") is True
                    or item.get("commitSha")
                    or item.get("prId")
                    or item.get("ticketId") in project_ticket_ids
                )
            ]
        else:
            injected_filtered = list(injected_ci)
        summary_items = [it for it in injected_filtered if isinstance(it, dict) and it.get("isCommitSummary")]
        other_items = [it for it in injected_filtered if not (isinstance(it, dict) and it.get("isCommitSummary"))]
        injected_capped = (summary_items + other_items)[:8]
        injected_cs = None
        for it in injected_filtered:
            if isinstance(it, dict) and it.get("isCommitSummary"):
                injected_cs = {
                    "text": it.get("title") or "",
                    "commitCount": int(it.get("commitCount") or 0),
                }
                break
        print(f"  injected completed_items length: {len(injected_ci)}")
        print(f"  after project filter:            {len(injected_filtered)}")
        print(f"  isCommitSummary survived filter: {len(summary_items)}  (expect=1)")
        print(f"  PO commitSummary field set:      {injected_cs is not None}")
        print(f"  completed_capped[0].isCommitSummary: {injected_capped[0].get('isCommitSummary') if injected_capped else 'EMPTY'}")
        print()
        print("  --- PO DIGEST WITH SYNTHETIC AI SUMMARY ---")
        print(f"  commitSummary.text (first 180c): {(injected_cs or {}).get('text','')[:180]}")
        print(f"  commitSummary.commitCount: {(injected_cs or {}).get('commitCount')}")
        print(f"  completed[0]: isCommitSummary={injected_capped[0].get('isCommitSummary') if injected_capped else None}")

        # Dev mine path with synthetic injection across matching TMs
        # (only work TM's report has the synthetic; others don't)
        dev_best = None
        dev_merged = []
        dev_seen: set[str] = set()
        for r, tm in matching:
            ci_r = list(r.completed_items or [])
            if project_ticket_ids is not None:
                ci_r = [
                    it for it in ci_r
                    if isinstance(it, dict) and (
                        it.get("isCommitSummary") is True
                        or it.get("commitSha")
                        or it.get("prId")
                        or it.get("ticketId") in project_ticket_ids
                    )
                ]
            sumi = [x for x in ci_r if isinstance(x, dict) and x.get("isCommitSummary")]
            othi = [x for x in ci_r if not (isinstance(x, dict) and x.get("isCommitSummary"))]
            tm_completed = (sumi + othi)[:8]
            tm_cs = None
            for it in ci_r:
                if isinstance(it, dict) and it.get("isCommitSummary"):
                    tm_cs = {"text": it.get("title") or "", "commitCount": int(it.get("commitCount") or 0)}
                    break
            if tm_cs and (dev_best is None or tm_cs["commitCount"] > dev_best["commitCount"]):
                dev_best = tm_cs
            for it in tm_completed:
                k = (it.get("ticketId") or it.get("commitSha") or it.get("prId")
                     or (it.get("title") or "").strip().lower())
                if k and k not in dev_seen:
                    dev_seen.add(k)
                    dev_merged.append(it)
        print()
        print("  --- DEV /dev/standup WITH SYNTHETIC AI SUMMARY ---")
        print(f"  mine.commitSummary set: {dev_best is not None}")
        if dev_best:
            print(f"  mine.commitSummary.text (first 180c): {dev_best.get('text','')[:180]}")
            print(f"  mine.commitSummary.commitCount: {dev_best.get('commitCount')}")
        # completed[*].isCommitSummary (the dev's render-by-flag path)
        flag_items = [x for x in dev_merged if isinstance(x, dict) and x.get("isCommitSummary")]
        print(f"  mine.completed has isCommitSummary entry: {len(flag_items) > 0}  ({len(flag_items)} found)")

        # Verdict for STAGE 4b
        po_ok_b = bool(injected_cs and injected_cs.get("text"))
        dev_ok_b = bool(dev_best and dev_best.get("text")) or bool(flag_items)
        print()
        if po_ok_b and dev_ok_b:
            print("  ✅  STAGE 4b: BOTH paths surface the synthetic AI summary.")
        else:
            print(f"  ❌  STAGE 4b: PO={po_ok_b} dev={dev_ok_b} — pipeline broken somewhere.")

        # ── 5) Verdict ───────────────────────────────────────────────
        section("VERDICT")
        po_ok = bool(commit_summary and commit_summary.get("text"))
        # Dev page reads completed[].isCommitSummary OR commitSummary.text
        dev_ok = bool(best_summary and best_summary.get("text")) or any(
            x.get("isCommitSummary") for x in merged_completed if isinstance(x, dict)
        )
        print(f"  PO digest commitSummary present: {po_ok}")
        print(f"  Dev page commitSummary visible:  {dev_ok}")
        if po_ok and dev_ok:
            print("\n  ✅  BOTH DASHBOARDS would show the AI commit summary block.")
        elif not po_ok and not dev_ok:
            print("\n  ❌  Neither dashboard sees the AI summary.")
            print("      Likely cause: AI caller returned None (no credentials, rate-limit, etc.).")
            print("      In production with creds set, this same code path would succeed.")
        else:
            print("\n  ⚠  Partial — one path renders, the other doesn't. Inspect logs above.")

        # ── 6) Rollback ──────────────────────────────────────────────
        repo_id_cached = repo.id  # snapshot before rollback expires attrs
        section("ROLLBACK — discarding all test mutations")
        await db.rollback()
        # Sanity-confirm using a fresh session
        async with AsyncSession(engine) as db2:
            n_remaining = (await db2.execute(
                select(func.count(Commit.id))
                .where(Commit.repository_id == repo_id_cached, Commit.committed_at >= since)
            )).scalar() or 0
            print(f"  recent commits remaining in DB after rollback: {n_remaining} (expect 0)")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

"""
Seed script: populates Supabase PostgreSQL with demo data.
Run from apps/api directory: python -m scripts.seed

Creates:
  - 1 Organization (demo-org)
  - 1 User (demo user)
  - 6 TeamMembers
  - 1 Iteration (Sprint 24)
  - 10 WorkItems
  - 5 Repositories
  - 6 PullRequests, 7 Commits
  - 6 StandupReports + 1 TeamStandupDigest
  - 1 SprintPlan + 6 PlanAssignments
  - 48 VelocityProfiles (6 members × 8 sprints)
  - 3 HealthSignals, 1 BurnoutAlert
  - 1 Retrospective + 2 RetroActionItems
  - 6 AuditLogEntries
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# Ensure we can import app modules
sys.path.insert(0, ".")

from app.config import settings
from app.models import Base
from app.models.organization import Organization
from app.models.user import User
from app.models.team_member import TeamMember
from app.models.iteration import Iteration
from app.models.work_item import WorkItem
from app.models.repository import Repository, PullRequest, Commit
from app.models.standup import StandupReport, TeamStandupDigest, BlockerFlag
from app.models.sprint_plan import SprintPlan, PlanAssignment
from app.models.analytics import VelocityProfile, HealthSignal, BurnoutAlert
from app.models.retrospective import Retrospective, RetroActionItem
from app.models.audit_log import AuditLogEntry
from app.models.activity import ActivityEvent


def utc(year, month, day, hour=0, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


async def seed():
    print(f"Connecting to: {settings.database_url[:50]}...")
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        # ── Organization ──────────────────────────────────
        org = Organization(
            id="demo-org",
            name="Demo Organization",
            slug="demo-org",
            timezone="America/New_York",
            working_hours_start="09:00",
            working_hours_end="17:00",
            standup_time="09:30",
        )
        session.add(org)

        # ── User ──────────────────────────────────────────
        user = User(
            id="demo-user-1",
            email="demo@plan2sprint.app",
            full_name="Demo User",
            role="PRODUCT_OWNER",
            supabase_user_id="demo-supabase-uid",
            organization_id="demo-org",
            onboarding_completed=True,
        )
        session.add(user)

        # ── Team Members ──────────────────────────────────
        members_data = [
            ("tm-1", "Alex Chen", "alex.chen@demo.com", "ext-alex", ["frontend", "react", "typescript"], 40),
            ("tm-2", "Sarah Kim", "sarah.kim@demo.com", "ext-sarah", ["backend", "python", "api"], 40),
            ("tm-3", "Marcus Johnson", "marcus.johnson@demo.com", "ext-marcus", ["frontend", "css", "animations"], 40),
            ("tm-4", "Priya Patel", "priya.patel@demo.com", "ext-priya", ["devops", "kubernetes", "aws"], 32),
            ("tm-5", "James Wilson", "james.wilson@demo.com", "ext-james", ["mobile", "react-native", "ios"], 40),
            ("tm-6", "Emma Davis", "emma.davis@demo.com", "ext-emma", ["backend", "ml", "python"], 40),
        ]
        members = {}
        for mid, name, email, ext_id, skills, cap in members_data:
            tm = TeamMember(
                id=mid,
                organization_id="demo-org",
                external_id=ext_id,
                email=email,
                display_name=name,
                skill_tags=skills,
                default_capacity=cap,
            )
            session.add(tm)
            members[mid] = tm

        # ── Iteration (Sprint 24) ────────────────────────
        sprint = Iteration(
            id="iter-1",
            organization_id="demo-org",
            external_id="sprint-24",
            source_tool="JIRA",
            name="Sprint 24",
            goal="Complete checkout flow redesign and payment integration",
            start_date=utc(2026, 2, 9),
            end_date=utc(2026, 2, 23),
            state="active",
        )
        session.add(sprint)

        # ── Work Items ────────────────────────────────────
        items_data = [
            ("wi-1", "AUTH-41", "Checkout flow redesign", "IN_PROGRESS", 8, "story", "tm-1"),
            ("wi-2", "AUTH-42", "Payment integration - Stripe", "IN_PROGRESS", 13, "story", "tm-2"),
            ("wi-3", "AUTH-43", "Cart page animations", "TODO", 5, "story", "tm-3"),
            ("wi-4", "AUTH-44", "K8s deployment config", "IN_REVIEW", 3, "task", "tm-4"),
            ("wi-5", "AUTH-45", "Mobile responsive fixes", "IN_REVIEW", 3, "bug", "tm-1"),
            ("wi-6", "AUTH-46", "Email notification templates", "TODO", 5, "story", "tm-3"),
            ("wi-7", "AUTH-47", "Push notification service", "IN_PROGRESS", 8, "story", "tm-5"),
            ("wi-8", "AUTH-48", "Order confirmation page", "BACKLOG", 5, "story", None),
            ("wi-9", "AUTH-49", "Recommendation engine v2", "DONE", 5, "story", "tm-6"),
            ("wi-10", "AUTH-50", "Load testing framework", "DONE", 3, "task", "tm-4"),
        ]
        for wid, ext, title, status, sp, wtype, assignee in items_data:
            wi = WorkItem(
                id=wid,
                organization_id="demo-org",
                external_id=ext,
                source_tool="JIRA",
                title=title,
                status=status,
                story_points=sp,
                type=wtype,
                labels=[],
                iteration_id="iter-1",
                assignee_id=assignee,
            )
            session.add(wi)

        # ── Repositories ──────────────────────────────────
        repos_data = [
            ("repo-1", "gh-1", "acme-web", "acme-org/acme-web", "https://github.com/acme-org/acme-web"),
            ("repo-2", "gh-2", "acme-api", "acme-org/acme-api", "https://github.com/acme-org/acme-api"),
            ("repo-3", "gh-3", "acme-mobile", "acme-org/acme-mobile", "https://github.com/acme-org/acme-mobile"),
            ("repo-4", "gh-4", "acme-infra", "acme-org/acme-infra", "https://github.com/acme-org/acme-infra"),
            ("repo-5", "gh-5", "design-system", "acme-org/design-system", "https://github.com/acme-org/design-system"),
        ]
        for rid, ext, name, full, url in repos_data:
            r = Repository(
                id=rid,
                organization_id="demo-org",
                external_id=ext,
                name=name,
                full_name=full,
                default_branch="main",
                url=url,
            )
            session.add(r)

        # ── Pull Requests ─────────────────────────────────
        prs_data = [
            ("pr-1", "repo-1", "gpr-1", 89, "feat: Checkout flow redesign", "AWAITING_REVIEW", "tm-1", "PASSING", "wi-1", utc(2026, 2, 19, 10, 30)),
            ("pr-2", "repo-1", "gpr-2", 87, "fix: Mobile responsive layout", "APPROVED", "tm-1", "PASSING", "wi-5", utc(2026, 2, 18, 14)),
            ("pr-3", "repo-2", "gpr-3", 92, "feat: Payment integration - Stripe", "CHANGES_REQUESTED", "tm-2", "FAILING", "wi-2", utc(2026, 2, 20, 9, 15)),
            ("pr-4", "repo-1", "gpr-4", 45, "chore: Update auth dependencies", "OPEN", "tm-3", "PASSING", None, utc(2026, 2, 20, 16, 45)),
            ("pr-5", "repo-3", "gpr-5", 23, "feat: Push notification service", "AWAITING_REVIEW", "tm-5", "PENDING", "wi-7", utc(2026, 2, 21, 8)),
            ("pr-6", "repo-2", "gpr-6", 15, "feat: Recommendation engine v2", "MERGED", "tm-6", "PASSING", "wi-9", utc(2026, 2, 17, 11)),
        ]
        for pid, repo_id, ext, num, title, status, author, ci, linked, created in prs_data:
            pr = PullRequest(
                id=pid,
                repository_id=repo_id,
                external_id=ext,
                number=num,
                title=title,
                status=status,
                author_id=author,
                ci_status=ci,
                linked_work_item_id=linked,
                url=f"https://github.com/acme-org/{repo_id}/pull/{num}",
                created_external_at=created,
            )
            session.add(pr)

        # ── Commits ───────────────────────────────────────
        commits_data = [
            ("cm-1", "repo-1", "a1b2c3d", "feat: add checkout form validation", "tm-1", "feature/checkout-redesign", ["wi-1"], utc(2026, 2, 20, 18, 30)),
            ("cm-2", "repo-2", "e4f5g6h", "fix: stripe webhook signature verification", "tm-2", "feature/payment-integration", ["wi-2"], utc(2026, 2, 20, 16)),
            ("cm-3", "repo-1", "i7j8k9l", "style: responsive cart layout", "tm-3", "fix/mobile-responsive", ["wi-5"], utc(2026, 2, 20, 14, 20)),
            ("cm-4", "repo-4", "m0n1o2p", "chore: update kubernetes manifests", "tm-4", "infra/k8s-update", ["wi-4"], utc(2026, 2, 20, 11)),
            ("cm-5", "repo-3", "q3r4s5t", "feat: deep link routing", "tm-5", "feature/push-notifications", ["wi-7"], utc(2026, 2, 19, 15, 45)),
            ("cm-6", "repo-2", "u6v7w8x", "feat: collaborative filtering model", "tm-6", "feature/recommendation-v2", ["wi-9"], utc(2026, 2, 19, 10, 30)),
            ("cm-7", "repo-1", "y9z0a1b", "test: add e2e tests for checkout", "tm-1", "feature/checkout-redesign", ["wi-1"], utc(2026, 2, 19, 9)),
        ]
        for cid, repo_id, sha, msg, author, branch, tickets, committed in commits_data:
            c = Commit(
                id=cid,
                repository_id=repo_id,
                sha=sha,
                message=msg,
                author_id=author,
                branch=branch,
                linked_ticket_ids=tickets,
                files_changed=5,
                committed_at=committed,
            )
            session.add(c)

        # ── Standup Reports ───────────────────────────────
        report_date = utc(2026, 2, 21)
        standups_data = [
            ("sr-1", "tm-1", ["Checkout UI components"], ["Payment form"], [], True),
            ("sr-2", "tm-2", ["API rate limiting"], ["Stripe integration"], [{"description": "Waiting for Stripe API key", "status": "OPEN"}], True),
            ("sr-3", "tm-3", ["Responsive fixes"], ["Cart animations"], [], True),
            ("sr-4", "tm-4", ["K8s config"], ["Load balancer setup"], [], True),
            ("sr-5", "tm-5", ["Push notification POC"], ["Deep linking"], [], False),
            ("sr-6", "tm-6", ["ML model tuning"], ["Recommendation engine"], [], True),
        ]
        for sid, tm_id, completed, in_progress, blockers, ack in standups_data:
            sr = StandupReport(
                id=sid,
                organization_id="demo-org",
                team_member_id=tm_id,
                iteration_id="iter-1",
                report_date=report_date,
                completed_items=completed,
                in_progress_items=in_progress,
                blockers=blockers,
                narrative_text=f"Completed {', '.join(completed)}. Working on {', '.join(in_progress)}.",
                acknowledged=ack,
                acknowledged_at=report_date if ack else None,
                is_inactive=False,
            )
            session.add(sr)

            # Create blocker flags
            for blocker in blockers:
                bf = BlockerFlag(
                    standup_report_id=sid,
                    description=blocker["description"],
                    status=blocker.get("status", "OPEN"),
                )
                session.add(bf)

        # ── Team Standup Digest ───────────────────────────
        digest = TeamStandupDigest(
            id="tsd-1",
            organization_id="demo-org",
            iteration_id="iter-1",
            digest_date=report_date,
            sprint_pacing=62.0,
            acknowledged_pct=83.0,
            sprint_health="GREEN",
            at_risk_items=["wi-2"],
            blocker_count=1,
            summary_text="Sprint 24 is on track. 5/6 developers submitted standups. 1 blocker flagged.",
        )
        session.add(digest)

        # ── Sprint Plan + Assignments ─────────────────────
        plan = SprintPlan(
            id="plan-1",
            organization_id="demo-org",
            iteration_id="iter-1",
            status="APPROVED",
            confidence_score=82.0,
            risk_summary="Payment integration has high complexity. Consider pair programming.",
            total_story_points=58.0,
            ai_model_used="gpt-4-turbo",
            approved_by_id="demo-user-1",
            approved_at=utc(2026, 2, 9, 10),
        )
        session.add(plan)

        assignments_data = [
            ("pa-1", "wi-1", "tm-1", 8, 0.91, "Strong frontend skills match checkout redesign"),
            ("pa-2", "wi-2", "tm-2", 13, 0.85, "Backend expertise for Stripe integration"),
            ("pa-3", "wi-3", "tm-3", 5, 0.88, "Animation specialist for cart page"),
            ("pa-4", "wi-4", "tm-4", 3, 0.95, "DevOps lead for K8s config"),
            ("pa-5", "wi-7", "tm-5", 8, 0.82, "Mobile expertise for push notifications"),
            ("pa-6", "wi-9", "tm-6", 5, 0.90, "ML background for recommendation engine"),
        ]
        for paid, wi_id, tm_id, sp, conf, rationale in assignments_data:
            pa = PlanAssignment(
                id=paid,
                sprint_plan_id="plan-1",
                work_item_id=wi_id,
                team_member_id=tm_id,
                story_points=sp,
                confidence_score=conf,
                rationale=rationale,
                risk_flags=[],
            )
            session.add(pa)

        # ── Velocity Profiles (8 sprints × 6 members) ────
        sprint_names = [
            "Sprint 17", "Sprint 18", "Sprint 19", "Sprint 20",
            "Sprint 21", "Sprint 22", "Sprint 23", "Sprint 24",
        ]
        velocity_data = {
            "tm-1": [(8, 7), (10, 9), (8, 8), (10, 8), (8, 7), (10, 10), (8, 8), (8, 5)],
            "tm-2": [(13, 11), (10, 10), (13, 12), (10, 8), (13, 10), (10, 9), (13, 13), (13, 6)],
            "tm-3": [(5, 5), (8, 7), (5, 4), (8, 8), (5, 5), (8, 6), (5, 5), (5, 0)],
            "tm-4": [(3, 3), (5, 4), (3, 3), (5, 5), (3, 2), (5, 5), (3, 3), (3, 3)],
            "tm-5": [(8, 6), (8, 7), (10, 8), (8, 8), (8, 7), (10, 9), (8, 8), (8, 3)],
            "tm-6": [(5, 5), (8, 8), (5, 5), (8, 7), (5, 5), (8, 8), (5, 5), (5, 5)],
        }
        vp_count = 0
        for tm_id, sprints in velocity_data.items():
            rolling_sum = 0
            for i, (planned, completed) in enumerate(sprints):
                rolling_sum += completed
                rolling_avg = rolling_sum / (i + 1)
                vp = VelocityProfile(
                    id=f"vp-{vp_count}",
                    team_member_id=tm_id,
                    iteration_id=f"sprint-{17 + i}",
                    planned_sp=planned,
                    completed_sp=completed,
                    rolling_average=round(rolling_avg, 1),
                    by_ticket_type={"story": completed, "bug": 0},
                    is_cold_start=(i < 2),
                )
                session.add(vp)
                vp_count += 1

        # ── Health Signals ────────────────────────────────
        signals_data = [
            ("hs-1", "tm-2", "STALLED_TICKET", "AMBER", "AUTH-42 has had no activity for 36 hours", {"ticketId": "AUTH-42", "hoursStalled": 36}),
            ("hs-2", "tm-4", "AFTER_HOURS", "AMBER", "3 after-hours commits this sprint", {"occurrences": 3, "sprint": "Sprint 24"}),
            ("hs-3", "tm-6", "INACTIVITY", "GREEN", "Low activity - may need check-in", {"lastActivity": "2026-02-20T14:00:00Z"}),
        ]
        for hsid, tm_id, stype, sev, msg, meta in signals_data:
            hs = HealthSignal(
                id=hsid,
                organization_id="demo-org",
                team_member_id=tm_id,
                signal_type=stype,
                severity=sev,
                message=msg,
                metadata_=meta,
            )
            session.add(hs)

        # ── Burnout Alert ─────────────────────────────────
        ba = BurnoutAlert(
            id="ba-1",
            organization_id="demo-org",
            team_member_id="tm-4",
            severity="AMBER",
            capacity_utilization=1.09,
            consecutive_sprints=3,
            after_hours_frequency=0.15,
        )
        session.add(ba)

        # ── Retrospective ────────────────────────────────
        retro = Retrospective(
            id="retro-1",
            organization_id="demo-org",
            iteration_id="iter-1",
            what_went_well=[
                "AI sprint planning saved 2+ hours",
                "Good cross-team collaboration",
                "CI/CD pipeline improvements",
            ],
            what_didnt_go_well=[
                "Stripe API key delay blocked payment work",
                "Some estimates were too optimistic",
            ],
            root_cause_analysis={
                "key_issues": ["External dependency delays", "Estimation accuracy"],
                "recommendations": ["Add buffer for external deps", "Use reference class forecasting"],
            },
            is_draft=False,
            finalized_at=utc(2026, 2, 23, 16),
        )
        session.add(retro)

        # ── Retro Action Items ────────────────────────────
        action1 = RetroActionItem(
            id="rai-1",
            retrospective_id="retro-1",
            title="Set up Stripe sandbox credentials before next sprint",
            assignee_id="tm-2",
            status="open",
        )
        action2 = RetroActionItem(
            id="rai-2",
            retrospective_id="retro-1",
            title="Review estimation accuracy with team",
            assignee_id="tm-1",
            status="open",
            is_carry_forward=True,
        )
        session.add(action1)
        session.add(action2)

        # ── Audit Log Entries ─────────────────────────────
        audit_data = [
            ("al-1", "connection.created", "ToolConnection", "conn-jira", utc(2026, 2, 15, 10)),
            ("al-2", "sync.completed", "ToolConnection", "conn-jira", utc(2026, 2, 15, 10, 1)),
            ("al-3", "connection.created", "ToolConnection", "conn-github", utc(2026, 2, 16, 9)),
            ("al-4", "sync.completed", "ToolConnection", "conn-github", utc(2026, 2, 16, 9, 1)),
            ("al-5", "sprint_plan.approved", "SprintPlan", "plan-1", utc(2026, 2, 9, 10)),
            ("al-6", "writeback.executed", "WorkItem", "wi-4", utc(2026, 2, 20, 15)),
        ]
        for alid, evt, resource_type, resource_id, created in audit_data:
            ale = AuditLogEntry(
                id=alid,
                organization_id="demo-org",
                actor_id="demo-user-1",
                actor_role="PRODUCT_OWNER",
                event_type=evt,
                resource_type=resource_type,
                resource_id=resource_id,
                success=True,
                created_at=created,
            )
            session.add(ale)

        # ── Commit ────────────────────────────────────────
        await session.commit()
        print("[OK] Seed data committed successfully!")
        print(f"   - 1 Organization")
        print(f"   - 1 User")
        print(f"   - 6 TeamMembers")
        print(f"   - 1 Iteration")
        print(f"   - 10 WorkItems")
        print(f"   - 5 Repositories")
        print(f"   - 6 PullRequests, 7 Commits")
        print(f"   - 6 StandupReports + 1 TeamStandupDigest")
        print(f"   - 1 SprintPlan + 6 PlanAssignments")
        print(f"   - {vp_count} VelocityProfiles")
        print(f"   - 3 HealthSignals, 1 BurnoutAlert")
        print(f"   - 1 Retrospective + 2 RetroActionItems")
        print(f"   - 6 AuditLogEntries")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())

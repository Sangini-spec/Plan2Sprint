"""
Seed script: populates Supabase PostgreSQL with comprehensive demo data
simulating a full sprint lifecycle.

Run from apps/api directory: python -m scripts.seed

Creates a realistic project lifecycle:
  - 1 Organization + 1 User (PO)
  - 6 TeamMembers with diverse skills
  - 2 ToolConnections (Jira + GitHub)
  - 1 ImportedProject ("Acme Checkout Platform")
  - 3 Iterations (Sprint 22 closed, Sprint 23 closed, Sprint 24 active)
  - 30 WorkItems across sprints (various statuses)
  - 5 Repositories + 15 PullRequests + 25 Commits
  - 80+ ActivityEvents (with after-hours & weekend events for burnout detection)
  - StandupReports for 6 weekdays + TeamStandupDigests
  - 3 SprintPlans + Assignments
  - 48 VelocityProfiles (6 members x 8 sprints)
  - HealthSignals + BurnoutAlerts
  - 2 Retrospectives (for closed sprints)
  - AuditLogEntries for key events
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta, date

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text

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
from app.models.tool_connection import ToolConnection
from app.models.imported_project import ImportedProject, UserProjectPreference


def utc(year, month, day, hour=0, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ============================================================================
# Constants - Timeline
# ============================================================================
# Today: March 5, 2026 (Thursday)
# Sprint 22: Jan 26 - Feb 6, 2026 (CLOSED - successful)
# Sprint 23: Feb 9 - Feb 20, 2026 (CLOSED - partial completion, good for retro)
# Sprint 24: Feb 23 - Mar 6, 2026 (ACTIVE - Day 9 of 10)

S22_START = utc(2026, 1, 26)
S22_END   = utc(2026, 2, 6)
S23_START = utc(2026, 2, 9)
S23_END   = utc(2026, 2, 20)
S24_START = utc(2026, 2, 23)
S24_END   = utc(2026, 3, 6)

TODAY = utc(2026, 3, 5, 9, 30)
YESTERDAY = utc(2026, 3, 4, 9, 30)


async def seed():
    print(f"Connecting to: {settings.database_url[:50]}...")
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        # -- CLEANUP: Clear only seed data, PRESERVE real OAuth connections & imported projects --
        print("Clearing seed data (preserving real connections & projects)...")
        await session.execute(text("SET session_replication_role = replica;"))

        # Tables safe to fully truncate (only contain seed data)
        safe_to_truncate = [
            "retro_action_items", "retrospectives",
            "burnout_alerts", "health_signals", "velocity_profiles",
            "plan_assignments", "sprint_plans",
            "blocker_flags", "standup_reports", "team_standup_digests",
            "activity_events", "audit_log_entries",
            "commits", "pull_requests", "repositories",
            "sprint_constraints",
            "user_project_preferences", "work_items",
            "iterations", "team_members", "users",
            "notification_preferences",
        ]
        for t in safe_to_truncate:
            try:
                await session.execute(text(f"TRUNCATE TABLE {t} CASCADE;"))
            except Exception:
                pass  # Table might not exist yet

        # PRESERVE real OAuth tool_connections (created via /connect flow)
        # Only remove seed connections (known IDs: conn-jira, conn-github)
        try:
            await session.execute(text(
                "DELETE FROM tool_connections WHERE id IN ('conn-jira', 'conn-github')"
            ))
            print("  [OK] Removed seed tool_connections (preserved real OAuth connections)")
        except Exception:
            pass

        # PRESERVE real imported_projects (synced from ADO/Jira)
        # Only remove seed project (known ID: proj-1)
        try:
            await session.execute(text(
                "DELETE FROM imported_projects WHERE id = 'proj-1'"
            ))
            print("  [OK] Removed seed imported_project (preserved real synced projects)")
        except Exception:
            pass

        # Organization: upsert (don't wipe, may have FK refs from real data)
        try:
            result = await session.execute(text(
                "SELECT id FROM organizations WHERE id = 'demo-org'"
            ))
            if not result.scalar_one_or_none():
                await session.execute(text("TRUNCATE TABLE organizations CASCADE;"))
        except Exception:
            pass

        await session.execute(text("SET session_replication_role = DEFAULT;"))
        await session.commit()
        print("[OK] Seed data cleared (real connections & projects preserved).")

        # ================================================================
        # 1. ORGANIZATION
        # ================================================================
        org = Organization(
            id="demo-org",
            name="Acme Technologies",
            slug="acme-tech",
            timezone="America/New_York",
            working_hours_start="09:00",
            working_hours_end="17:00",
            standup_time="09:30",
        )
        session.add(org)

        # ================================================================
        # 2. USER (Product Owner)
        # ================================================================
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

        # ================================================================
        # 3. TEAM MEMBERS (6 developers)
        # ================================================================
        members_data = [
            ("tm-1", "Alex Chen",       "alex.chen@acme.com",       "ext-alex",   ["frontend", "react", "typescript", "nextjs"], 40),
            ("tm-2", "Sarah Kim",       "sarah.kim@acme.com",       "ext-sarah",  ["backend", "python", "api", "fastapi", "postgresql"], 40),
            ("tm-3", "Marcus Johnson",  "marcus.johnson@acme.com",  "ext-marcus", ["frontend", "css", "animations", "figma", "react"], 40),
            ("tm-4", "Priya Patel",     "priya.patel@acme.com",     "ext-priya",  ["devops", "kubernetes", "aws", "terraform", "monitoring"], 32),
            ("tm-5", "James Wilson",    "james.wilson@acme.com",    "ext-james",  ["mobile", "react-native", "ios", "android", "push-notifications"], 40),
            ("tm-6", "Emma Davis",      "emma.davis@acme.com",      "ext-emma",   ["backend", "ml", "python", "data-pipeline", "recommendation"], 40),
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

        # ================================================================
        # 4. TOOL CONNECTIONS (Jira + GitHub)
        # ================================================================
        jira_conn = ToolConnection(
            id="conn-jira",
            organization_id="demo-org",
            source_tool="JIRA",
            access_token="demo-jira-token-encrypted",
            refresh_token="demo-jira-refresh",
            last_sync_at=utc(2026, 3, 5, 8, 0),
            sync_status="synced",
            config={"cloudId": "acme-cloud-123", "siteUrl": "https://acme-tech.atlassian.net"},
        )
        github_conn = ToolConnection(
            id="conn-github",
            organization_id="demo-org",
            source_tool="GITHUB",
            access_token="demo-github-token-encrypted",
            last_sync_at=utc(2026, 3, 5, 8, 0),
            sync_status="synced",
            config={"installationId": "gh-install-456", "org": "acme-org"},
        )
        session.add(jira_conn)
        session.add(github_conn)

        # ================================================================
        # 5. IMPORTED PROJECT
        # ================================================================
        project = ImportedProject(
            id="proj-1",
            organization_id="demo-org",
            external_id="10001",
            source_tool="jira",
            name="Acme Checkout Platform",
            key="ACME",
            description="E-commerce checkout flow, payments, and order management",
            board_id="board-42",
            is_active=True,
            synced_at=utc(2026, 3, 5, 8, 0),
        )
        session.add(project)

        # User project preference
        pref = UserProjectPreference(
            id="pref-1",
            user_id="demo-user-1",
            organization_id="demo-org",
            selected_project_id="proj-1",
        )
        session.add(pref)

        # ================================================================
        # 6. ITERATIONS (3 sprints)
        # ================================================================
        iter22 = Iteration(
            id="iter-22",
            organization_id="demo-org",
            imported_project_id="proj-1",
            external_id="sprint-22",
            source_tool="JIRA",
            name="Sprint 22",
            goal="Complete user auth and search features",
            start_date=S22_START,
            end_date=S22_END,
            state="closed",
        )
        iter23 = Iteration(
            id="iter-23",
            organization_id="demo-org",
            imported_project_id="proj-1",
            external_id="sprint-23",
            source_tool="JIRA",
            name="Sprint 23",
            goal="Complete checkout flow redesign and payment integration",
            start_date=S23_START,
            end_date=S23_END,
            state="closed",
        )
        iter24 = Iteration(
            id="iter-1",  # Keep as iter-1 for backward compat
            organization_id="demo-org",
            imported_project_id="proj-1",
            external_id="sprint-24",
            source_tool="JIRA",
            name="Sprint 24",
            goal="Payments v2, monitoring, mobile push, and recommendations engine",
            start_date=S24_START,
            end_date=S24_END,
            state="active",
        )
        session.add_all([iter22, iter23, iter24])

        # ================================================================
        # 7. WORK ITEMS (30 items across 3 sprints)
        # ================================================================

        # --- Sprint 22 (CLOSED - all DONE) ---
        s22_items = [
            ("wi-101", "ACME-101", "User authentication flow",        "DONE", 8,  "story", "tm-1", 2, "iter-22"),
            ("wi-102", "ACME-102", "API rate limiting middleware",     "DONE", 5,  "story", "tm-2", 1, "iter-22"),
            ("wi-103", "ACME-103", "Responsive navigation bar",       "DONE", 3,  "story", "tm-3", 2, "iter-22"),
            ("wi-104", "ACME-104", "CI/CD pipeline setup",            "DONE", 5,  "task",  "tm-4", 1, "iter-22"),
            ("wi-105", "ACME-105", "Product search feature",          "DONE", 8,  "story", "tm-5", 2, "iter-22"),
            ("wi-106", "ACME-106", "ML recommendation baseline",      "DONE", 5,  "story", "tm-6", 3, "iter-22"),
            ("wi-107", "ACME-107", "Fix login redirect bug",          "DONE", 2,  "bug",   "tm-1", 1, "iter-22"),
        ]

        # --- Sprint 23 (CLOSED - partial completion) ---
        s23_items = [
            ("wi-201", "ACME-201", "Checkout flow redesign",           "DONE",        8,  "story", "tm-1", 1, "iter-23"),
            ("wi-202", "ACME-202", "Payment integration - Stripe",     "DONE",        13, "story", "tm-2", 1, "iter-23"),
            ("wi-203", "ACME-203", "Cart page animations",             "DONE",        5,  "story", "tm-3", 2, "iter-23"),
            ("wi-204", "ACME-204", "K8s deployment config",            "DONE",        3,  "task",  "tm-4", 1, "iter-23"),
            ("wi-205", "ACME-205", "Mobile responsive fixes",          "DONE",        3,  "bug",   "tm-1", 2, "iter-23"),
            ("wi-206", "ACME-206", "Push notification service",        "IN_PROGRESS", 8,  "story", "tm-5", 2, "iter-23"),
            ("wi-207", "ACME-207", "Order confirmation page",          "TODO",        5,  "story", "tm-3", 3, "iter-23"),
            ("wi-208", "ACME-208", "Load testing framework",           "DONE",        3,  "task",  "tm-4", 2, "iter-23"),
            ("wi-209", "ACME-209", "API documentation generation",     "DONE",        2,  "task",  "tm-6", 3, "iter-23"),
        ]

        # --- Sprint 24 (ACTIVE - mixed statuses) ---
        s24_items = [
            ("wi-1",  "ACME-301", "Checkout flow v2 - payment form",    "IN_PROGRESS", 8,  "story", "tm-1", 1, "iter-1"),
            ("wi-2",  "ACME-302", "API gateway optimization",           "IN_REVIEW",   5,  "story", "tm-2", 1, "iter-1"),
            ("wi-3",  "ACME-303", "Product card redesign",              "DONE",        5,  "story", "tm-3", 2, "iter-1"),
            ("wi-4",  "ACME-304", "Monitoring dashboard",               "IN_PROGRESS", 3,  "task",  "tm-4", 1, "iter-1"),
            ("wi-5",  "ACME-305", "Mobile push v2 - deep linking",      "IN_PROGRESS", 8,  "story", "tm-5", 2, "iter-1"),
            ("wi-6",  "ACME-306", "Recommendation engine v2",           "DONE",        5,  "story", "tm-6", 1, "iter-1"),
            ("wi-7",  "ACME-307", "Email notification templates",       "TODO",        5,  "story", "tm-3", 3, "iter-1"),
            ("wi-8",  "ACME-308", "Database indexing optimization",     "DONE",        3,  "task",  "tm-2", 1, "iter-1"),
            ("wi-9",  "ACME-309", "iOS widget feature",                 "IN_PROGRESS", 5,  "story", "tm-5", 2, "iter-1"),
            ("wi-10", "ACME-310", "Infra cost optimization",            "IN_PROGRESS", 3,  "task",  "tm-4", 2, "iter-1"),
            ("wi-11", "ACME-311", "Accessibility audit fixes",          "IN_REVIEW",   3,  "story", "tm-1", 2, "iter-1"),
            ("wi-12", "ACME-312", "Order tracking feature",             "IN_PROGRESS", 8,  "story", "tm-6", 2, "iter-1"),
            # Backlog items (future)
            ("wi-13", "ACME-313", "Customer analytics dashboard",       "BACKLOG",     8,  "story", None,   3, None),
            ("wi-14", "ACME-314", "Inventory management integration",   "BACKLOG",     13, "story", None,   2, None),
        ]

        all_items = s22_items + s23_items + s24_items
        for wid, ext, title, status, sp, wtype, assignee, priority, iter_id in all_items:
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
                priority=priority,
                iteration_id=iter_id,
                assignee_id=assignee,
                imported_project_id="proj-1",
            )
            # Set realistic updated_at timestamps
            if iter_id == "iter-22":
                wi.updated_at = utc(2026, 2, 5, 14, 30)
            elif iter_id == "iter-23":
                wi.updated_at = utc(2026, 2, 19, 16, 0)
            elif iter_id == "iter-1":
                if status == "DONE":
                    wi.updated_at = utc(2026, 3, 4, 15, 0)
                elif status in ("IN_PROGRESS", "IN_REVIEW"):
                    wi.updated_at = utc(2026, 3, 5, 8, 0)
                else:
                    wi.updated_at = utc(2026, 2, 23, 10, 0)
            session.add(wi)

        # ================================================================
        # 8. REPOSITORIES (5 repos)
        # ================================================================
        repos_data = [
            ("repo-1", "gh-1", "acme-web",     "acme-org/acme-web",     "https://github.com/acme-org/acme-web"),
            ("repo-2", "gh-2", "acme-api",     "acme-org/acme-api",     "https://github.com/acme-org/acme-api"),
            ("repo-3", "gh-3", "acme-mobile",  "acme-org/acme-mobile",  "https://github.com/acme-org/acme-mobile"),
            ("repo-4", "gh-4", "acme-infra",   "acme-org/acme-infra",   "https://github.com/acme-org/acme-infra"),
            ("repo-5", "gh-5", "design-system","acme-org/design-system","https://github.com/acme-org/design-system"),
        ]
        repos_map = {}
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
            repos_map[rid] = full

        # ================================================================
        # 9. PULL REQUESTS (15 PRs across sprints)
        # ================================================================
        prs_data = [
            # Sprint 23 PRs (older, MERGED)
            ("pr-101", "repo-1", "gpr-101", 75, "feat: Checkout flow redesign",          "MERGED",            "tm-1", "PASSING", "wi-201", utc(2026, 2, 14, 10, 30), utc(2026, 2, 16, 14)),
            ("pr-102", "repo-2", "gpr-102", 78, "feat: Stripe payment integration",      "MERGED",            "tm-2", "PASSING", "wi-202", utc(2026, 2, 12, 9, 15),  utc(2026, 2, 18, 11)),
            ("pr-103", "repo-1", "gpr-103", 80, "feat: Cart animations & transitions",   "MERGED",            "tm-3", "PASSING", "wi-203", utc(2026, 2, 13, 15, 0),  utc(2026, 2, 17, 9)),

            # Sprint 24 PRs (current - various states)
            ("pr-1",   "repo-1", "gpr-1",  89, "feat: Payment form v2 with validation",  "AWAITING_REVIEW",   "tm-1", "PASSING", "wi-1",   utc(2026, 3, 4, 10, 30),  None),
            ("pr-2",   "repo-1", "gpr-2",  87, "fix: Accessibility audit issues",        "APPROVED",          "tm-1", "PASSING", "wi-11",  utc(2026, 3, 3, 14, 0),   None),
            ("pr-3",   "repo-2", "gpr-3",  92, "feat: API gateway rate limit + cache",   "CHANGES_REQUESTED", "tm-2", "FAILING", "wi-2",   utc(2026, 3, 3, 9, 15),   None),
            ("pr-4",   "repo-2", "gpr-4",  93, "perf: DB index optimization",            "MERGED",            "tm-2", "PASSING", "wi-8",   utc(2026, 3, 1, 16, 0),   utc(2026, 3, 2, 10)),
            ("pr-5",   "repo-1", "gpr-5",  90, "feat: Product card redesign",            "MERGED",            "tm-3", "PASSING", "wi-3",   utc(2026, 2, 27, 11, 0),  utc(2026, 3, 1, 14)),
            ("pr-6",   "repo-4", "gpr-6",  15, "feat: Monitoring dashboard setup",       "OPEN",              "tm-4", "PENDING", "wi-4",   utc(2026, 3, 4, 16, 45),  None),
            ("pr-7",   "repo-3", "gpr-7",  23, "feat: Deep linking for push notifs",     "AWAITING_REVIEW",   "tm-5", "PASSING", "wi-5",   utc(2026, 3, 4, 8, 0),    None),
            ("pr-8",   "repo-3", "gpr-8",  24, "feat: iOS widget basic implementation",  "OPEN",              "tm-5", "PENDING", "wi-9",   utc(2026, 3, 5, 7, 30),   None),
            ("pr-9",   "repo-2", "gpr-9",  94, "feat: Recommendation engine v2",         "MERGED",            "tm-6", "PASSING", "wi-6",   utc(2026, 2, 28, 11, 0),  utc(2026, 3, 3, 9)),
            ("pr-10",  "repo-2", "gpr-10", 95, "feat: Order tracking API endpoints",     "OPEN",              "tm-6", "PASSING", "wi-12",  utc(2026, 3, 4, 14, 0),   None),
            ("pr-11",  "repo-4", "gpr-11", 16, "chore: Infra cost analysis scripts",     "OPEN",              "tm-4", "PASSING", "wi-10",  utc(2026, 3, 3, 11, 0),   None),
        ]
        for pid, repo_id, ext, num, title, status, author, ci, linked, created, merged in prs_data:
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
                url=f"https://github.com/{repos_map.get(repo_id, 'acme-org/repo')}/pull/{num}",
                created_external_at=created,
                merged_at=merged,
            )
            session.add(pr)

        # ================================================================
        # 10. COMMITS (25 commits across sprints)
        # ================================================================
        commits_data = [
            # Sprint 23 commits (historical)
            ("cm-101", "repo-1", "a1b2c3d1", "feat: add checkout form components",        "tm-1", "feature/checkout-redesign",       ["wi-201"], utc(2026, 2, 12, 10, 30)),
            ("cm-102", "repo-2", "e4f5g6h1", "feat: stripe webhook handler",              "tm-2", "feature/payment-integration",      ["wi-202"], utc(2026, 2, 13, 14, 0)),
            ("cm-103", "repo-1", "i7j8k9l1", "feat: cart animation transitions",          "tm-3", "feature/cart-animations",           ["wi-203"], utc(2026, 2, 14, 11, 15)),
            ("cm-104", "repo-4", "m0n1o2p1", "chore: kubernetes deployment manifests",    "tm-4", "infra/k8s-config",                 ["wi-204"], utc(2026, 2, 11, 9, 30)),
            ("cm-105", "repo-3", "q3r4s5t1", "feat: push notification POC",               "tm-5", "feature/push-notifications",       ["wi-206"], utc(2026, 2, 15, 15, 45)),

            # Sprint 24 commits (current sprint - recent activity)
            ("cm-1",   "repo-1", "a1b2c3d0", "feat: payment form validation logic",       "tm-1", "feature/checkout-v2",              ["wi-1"],   utc(2026, 3, 3, 10, 30)),
            ("cm-2",   "repo-1", "c3d4e5f0", "feat: payment form error states",           "tm-1", "feature/checkout-v2",              ["wi-1"],   utc(2026, 3, 4, 14, 20)),
            ("cm-3",   "repo-1", "g7h8i9j0", "fix: aria labels for checkout",             "tm-1", "fix/accessibility-audit",          ["wi-11"],  utc(2026, 3, 3, 16, 0)),
            ("cm-4",   "repo-2", "k0l1m2n0", "feat: API gateway caching layer",           "tm-2", "feature/api-gateway-optimization", ["wi-2"],   utc(2026, 3, 2, 11, 0)),
            ("cm-5",   "repo-2", "o3p4q5r0", "perf: add composite DB indexes",            "tm-2", "perf/db-indexing",                 ["wi-8"],   utc(2026, 2, 28, 15, 30)),
            ("cm-6",   "repo-2", "s6t7u8v0", "fix: API gateway rate limit edge case",     "tm-2", "feature/api-gateway-optimization", ["wi-2"],   utc(2026, 3, 4, 10, 15)),
            ("cm-7",   "repo-1", "w9x0y1z0", "feat: product card component refactor",     "tm-3", "feature/product-card-redesign",    ["wi-3"],   utc(2026, 2, 26, 14, 0)),
            ("cm-8",   "repo-1", "a2b3c4d0", "style: product card hover animations",      "tm-3", "feature/product-card-redesign",    ["wi-3"],   utc(2026, 2, 27, 9, 30)),
            ("cm-9",   "repo-4", "e5f6g7h0", "feat: grafana dashboard templates",         "tm-4", "feature/monitoring-dashboard",     ["wi-4"],   utc(2026, 3, 3, 14, 0)),
            ("cm-10",  "repo-4", "i8j9k0l0", "chore: cost analysis terraform modules",    "tm-4", "chore/infra-cost-optimization",    ["wi-10"],  utc(2026, 3, 2, 10, 0)),
            # Priya's after-hours commits (for burnout detection)
            ("cm-11",  "repo-4", "m1n2o3p0", "fix: monitoring alerting thresholds",       "tm-4", "feature/monitoring-dashboard",     ["wi-4"],   utc(2026, 3, 3, 22, 30)),
            ("cm-12",  "repo-4", "q4r5s6t0", "chore: update helm charts",                 "tm-4", "feature/monitoring-dashboard",     ["wi-4"],   utc(2026, 3, 4, 21, 0)),
            ("cm-13",  "repo-3", "u7v8w9x0", "feat: deep link routing for push",          "tm-5", "feature/push-v2-deep-link",       ["wi-5"],   utc(2026, 3, 3, 15, 45)),
            ("cm-14",  "repo-3", "y0z1a2b0", "feat: iOS widget scaffold",                 "tm-5", "feature/ios-widget",              ["wi-9"],   utc(2026, 3, 4, 11, 30)),
            ("cm-15",  "repo-2", "c3d4e5f1", "feat: collaborative filtering model v2",    "tm-6", "feature/recommendation-v2",        ["wi-6"],   utc(2026, 2, 27, 10, 0)),
            ("cm-16",  "repo-2", "g6h7i8j1", "feat: order tracking data models",          "tm-6", "feature/order-tracking",           ["wi-12"],  utc(2026, 3, 4, 9, 30)),
            # Weekend commit (for weekend_work signal)
            ("cm-17",  "repo-4", "k9l0m1n1", "fix: critical monitoring alert fix",        "tm-4", "hotfix/monitoring-alert",          ["wi-4"],   utc(2026, 3, 1, 10, 0)),
            ("cm-18",  "repo-4", "o2p3q4r1", "chore: weekend deploy fix",                 "tm-4", "hotfix/deploy-fix",               [],         utc(2026, 2, 28, 15, 0)),
            # Recent commit today for standup generation
            ("cm-19",  "repo-1", "s5t6u7v1", "feat: payment form submit handler",         "tm-1", "feature/checkout-v2",              ["wi-1"],   utc(2026, 3, 5, 8, 15)),
            ("cm-20",  "repo-2", "w8x9y0z1", "feat: order tracking endpoints",            "tm-6", "feature/order-tracking",           ["wi-12"],  utc(2026, 3, 5, 7, 45)),
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

        # ================================================================
        # 11. ACTIVITY EVENTS (80+ events for health signal evaluation)
        # ================================================================
        activity_events = []
        ae_counter = [0]

        def ae(member_id, event_type, source, occurred, ext_id=None, ticket=None, meta=None):
            ae_counter[0] += 1
            is_after_hours = occurred.hour < 9 or occurred.hour >= 18
            is_weekend = occurred.weekday() in (5, 6)
            ev = ActivityEvent(
                id=f"ae-{ae_counter[0]:03d}",
                organization_id="demo-org",
                team_member_id=member_id,
                event_type=event_type,
                source_tool=source,
                external_id=ext_id,
                linked_ticket_id=ticket,
                metadata_=meta,
                is_after_hours=is_after_hours,
                is_weekend=is_weekend,
                occurred_at=occurred,
            )
            activity_events.append(ev)

        # --- Alex Chen (tm-1): Normal working pattern ---
        for day in range(23, 28):
            if date(2026, 2, day).weekday() < 5:
                ae("tm-1", "COMMIT_PUSHED", "GITHUB", utc(2026, 2, day, 10, 30), ticket="wi-1")
                ae("tm-1", "TICKET_STATUS_CHANGED", "JIRA", utc(2026, 2, day, 11, 0), ticket="wi-1")
        for day in range(2, 6):
            if date(2026, 3, day).weekday() < 5:
                ae("tm-1", "COMMIT_PUSHED", "GITHUB", utc(2026, 3, day, 10, 30), ticket="wi-1")
                ae("tm-1", "PR_OPENED", "GITHUB", utc(2026, 3, day, 14, 0), ticket="wi-1")

        # --- Sarah Kim (tm-2): Steady backend work ---
        for day in range(23, 28):
            if date(2026, 2, day).weekday() < 5:
                ae("tm-2", "COMMIT_PUSHED", "GITHUB", utc(2026, 2, day, 9, 30), ticket="wi-2")
        for day in range(2, 6):
            if date(2026, 3, day).weekday() < 5:
                ae("tm-2", "COMMIT_PUSHED", "GITHUB", utc(2026, 3, day, 11, 0), ticket="wi-2")
                ae("tm-2", "TICKET_STATUS_CHANGED", "JIRA", utc(2026, 3, day, 15, 0), ticket="wi-8")

        # --- Marcus Johnson (tm-3): Normal ---
        for day in range(24, 28):
            if date(2026, 2, day).weekday() < 5:
                ae("tm-3", "COMMIT_PUSHED", "GITHUB", utc(2026, 2, day, 14, 0), ticket="wi-3")
        ae("tm-3", "PR_MERGED", "GITHUB", utc(2026, 3, 1, 14, 0), ticket="wi-3")
        ae("tm-3", "TICKET_STATUS_CHANGED", "JIRA", utc(2026, 3, 1, 14, 30), ticket="wi-3")

        # --- Priya Patel (tm-4): HEAVY AFTER-HOURS + WEEKEND WORK (burnout risk) ---
        for day in range(23, 28):
            if date(2026, 2, day).weekday() < 5:
                ae("tm-4", "COMMIT_PUSHED", "GITHUB", utc(2026, 2, day, 10, 0), ticket="wi-4")
                ae("tm-4", "COMMIT_PUSHED", "GITHUB", utc(2026, 2, day, 22, 0), ticket="wi-4")
                ae("tm-4", "COMMIT_PUSHED", "GITHUB", utc(2026, 2, day, 23, 30), ticket="wi-10")
        # Weekend work
        ae("tm-4", "COMMIT_PUSHED", "GITHUB", utc(2026, 2, 28, 15, 0))
        ae("tm-4", "COMMIT_PUSHED", "GITHUB", utc(2026, 3, 1, 10, 0), ticket="wi-4")
        ae("tm-4", "COMMIT_PUSHED", "GITHUB", utc(2026, 3, 1, 14, 0), ticket="wi-4")
        ae("tm-4", "COMMIT_PUSHED", "GITHUB", utc(2026, 3, 1, 18, 0), ticket="wi-10")
        # Weekdays with after-hours
        for day in range(2, 6):
            if date(2026, 3, day).weekday() < 5:
                ae("tm-4", "COMMIT_PUSHED", "GITHUB", utc(2026, 3, day, 10, 0), ticket="wi-4")
                ae("tm-4", "COMMIT_PUSHED", "GITHUB", utc(2026, 3, day, 21, 0), ticket="wi-4")
                ae("tm-4", "COMMIT_PUSHED", "GITHUB", utc(2026, 3, day, 22, 30), ticket="wi-10")

        # --- James Wilson (tm-5): Normal mobile dev ---
        for day in range(24, 28):
            if date(2026, 2, day).weekday() < 5:
                ae("tm-5", "COMMIT_PUSHED", "GITHUB", utc(2026, 2, day, 11, 0), ticket="wi-5")
        for day in range(2, 6):
            if date(2026, 3, day).weekday() < 5:
                ae("tm-5", "COMMIT_PUSHED", "GITHUB", utc(2026, 3, day, 11, 0), ticket="wi-5")
                ae("tm-5", "COMMIT_PUSHED", "GITHUB", utc(2026, 3, day, 15, 0), ticket="wi-9")

        # --- Emma Davis (tm-6): Normal ML work ---
        for day in range(25, 28):
            if date(2026, 2, day).weekday() < 5:
                ae("tm-6", "COMMIT_PUSHED", "GITHUB", utc(2026, 2, day, 10, 30), ticket="wi-6")
        for day in range(2, 6):
            if date(2026, 3, day).weekday() < 5:
                ae("tm-6", "COMMIT_PUSHED", "GITHUB", utc(2026, 3, day, 10, 0), ticket="wi-6")
                ae("tm-6", "COMMIT_PUSHED", "GITHUB", utc(2026, 3, day, 14, 0), ticket="wi-12")

        for ev in activity_events:
            session.add(ev)

        # ================================================================
        # 12. STANDUP REPORTS (6 weekdays of Sprint 24)
        # ================================================================
        # Reports for: Feb 25, 26, 27, Mar 2, 3, 4
        # NOT for today (Mar 5) - auto-generation will handle today

        standup_dates = [
            utc(2026, 2, 25, 9, 30),
            utc(2026, 2, 26, 9, 30),
            utc(2026, 2, 27, 9, 30),
            utc(2026, 3, 2, 9, 30),
            utc(2026, 3, 3, 9, 30),
            utc(2026, 3, 4, 9, 30),
        ]

        sr_counter = [0]
        def make_standup(member_id, report_date, completed, in_progress, blockers, narrative, ack=True, note=None):
            sr_counter[0] += 1
            sr = StandupReport(
                id=f"sr-{sr_counter[0]:03d}",
                organization_id="demo-org",
                team_member_id=member_id,
                iteration_id="iter-1",
                report_date=report_date,
                completed_items=completed,
                in_progress_items=in_progress,
                blockers=blockers,
                narrative_text=narrative,
                acknowledged=ack,
                acknowledged_at=report_date if ack else None,
                developer_note=note,
                is_inactive=False,
            )
            session.add(sr)
            return sr

        # -- Feb 25 (Day 1) --
        make_standup("tm-1", standup_dates[0],
            [{"title": "Sprint planning complete", "ticketId": "ACME-301"}],
            [{"title": "Checkout flow v2 - payment form", "ticketId": "ACME-301"}],
            [], "Alex Chen starting checkout v2 work. Set up branch and initial components.")
        make_standup("tm-2", standup_dates[0],
            [],
            [{"title": "API gateway optimization", "ticketId": "ACME-302"}, {"title": "Database indexing optimization", "ticketId": "ACME-308"}],
            [], "Sarah Kim beginning API gateway and DB optimization work.")
        make_standup("tm-3", standup_dates[0],
            [],
            [{"title": "Product card redesign", "ticketId": "ACME-303"}],
            [], "Marcus Johnson started product card redesign. Reviewing Figma specs.")
        make_standup("tm-4", standup_dates[0],
            [],
            [{"title": "Monitoring dashboard", "ticketId": "ACME-304"}, {"title": "Infra cost optimization", "ticketId": "ACME-310"}],
            [], "Priya Patel setting up monitoring dashboard and starting cost analysis.")
        make_standup("tm-5", standup_dates[0],
            [],
            [{"title": "Mobile push v2 - deep linking", "ticketId": "ACME-305"}, {"title": "iOS widget feature", "ticketId": "ACME-309"}],
            [], "James Wilson continuing push v2 from last sprint. Starting iOS widget.")
        make_standup("tm-6", standup_dates[0],
            [],
            [{"title": "Recommendation engine v2", "ticketId": "ACME-306"}],
            [], "Emma Davis starting recommendation engine v2 with new collaborative filtering.")

        # -- Feb 26 (Day 2) --
        make_standup("tm-1", standup_dates[1],
            [],
            [{"title": "Checkout flow v2 - payment form", "ticketId": "ACME-301"}],
            [], "Alex Chen working on payment form validation. 2 commits pushed.")
        make_standup("tm-2", standup_dates[1],
            [],
            [{"title": "API gateway optimization", "ticketId": "ACME-302"}, {"title": "Database indexing optimization", "ticketId": "ACME-308"}],
            [], "Sarah Kim implementing caching layer for API gateway.")
        make_standup("tm-3", standup_dates[1],
            [],
            [{"title": "Product card redesign", "ticketId": "ACME-303"}],
            [], "Marcus Johnson building product card components. Hover animations in progress.")
        make_standup("tm-4", standup_dates[1],
            [],
            [{"title": "Monitoring dashboard", "ticketId": "ACME-304"}, {"title": "Infra cost optimization", "ticketId": "ACME-310"}],
            [], "Priya Patel configuring Grafana dashboards. Working late to meet deadline.",
            note="Running into some Grafana config issues, may need extra time.")
        make_standup("tm-5", standup_dates[1],
            [],
            [{"title": "Mobile push v2 - deep linking", "ticketId": "ACME-305"}],
            [], "James Wilson implementing deep link routing for push notifications.")
        make_standup("tm-6", standup_dates[1],
            [],
            [{"title": "Recommendation engine v2", "ticketId": "ACME-306"}],
            [], "Emma Davis training collaborative filtering model. Initial results promising.")

        # -- Feb 27 (Day 3) --
        make_standup("tm-1", standup_dates[2],
            [],
            [{"title": "Checkout flow v2 - payment form", "ticketId": "ACME-301"}, {"title": "Accessibility audit fixes", "ticketId": "ACME-311"}],
            [], "Alex Chen continuing payment form. Also started accessibility audit fixes.")
        make_standup("tm-2", standup_dates[2],
            [{"title": "Database indexing optimization", "ticketId": "ACME-308"}],
            [{"title": "API gateway optimization", "ticketId": "ACME-302"}],
            [], "Sarah Kim completed DB indexing optimization. PR merged. API gateway on track.")
        make_standup("tm-3", standup_dates[2],
            [],
            [{"title": "Product card redesign", "ticketId": "ACME-303"}],
            [], "Marcus Johnson finalizing product card redesign. PR opened for review.")
        make_standup("tm-4", standup_dates[2],
            [],
            [{"title": "Monitoring dashboard", "ticketId": "ACME-304"}, {"title": "Infra cost optimization", "ticketId": "ACME-310"}],
            [], "Priya Patel pushing late commits on monitoring. Weekend work needed for alerts.",
            note="Had to fix critical monitoring alerts over the weekend.")
        make_standup("tm-5", standup_dates[2],
            [],
            [{"title": "Mobile push v2 - deep linking", "ticketId": "ACME-305"}, {"title": "iOS widget feature", "ticketId": "ACME-309"}],
            [], "James Wilson deep linking nearly complete. Started iOS widget scaffold.")
        make_standup("tm-6", standup_dates[2],
            [],
            [{"title": "Recommendation engine v2", "ticketId": "ACME-306"}],
            [], "Emma Davis model tuning complete. Preparing PR for review.")

        # -- Mar 2 (Day 6) --
        make_standup("tm-1", standup_dates[3],
            [],
            [{"title": "Checkout flow v2 - payment form", "ticketId": "ACME-301"}, {"title": "Accessibility audit fixes", "ticketId": "ACME-311"}],
            [], "Alex Chen payment form error states in progress. Accessibility PR submitted.")
        make_standup("tm-2", standup_dates[3],
            [{"title": "Database indexing optimization", "ticketId": "ACME-308", "type": "pr"}],
            [{"title": "API gateway optimization", "ticketId": "ACME-302"}],
            [], "Sarah Kim DB indexing merged. API gateway cache layer needs rework.")
        make_standup("tm-3", standup_dates[3],
            [{"title": "Product card redesign", "ticketId": "ACME-303"}],
            [],
            [], "Marcus Johnson product card redesign completed and merged!")
        make_standup("tm-4", standup_dates[3],
            [],
            [{"title": "Monitoring dashboard", "ticketId": "ACME-304"}, {"title": "Infra cost optimization", "ticketId": "ACME-310"}],
            [], "Priya Patel monitoring dashboard 70% complete. Cost optimization scripts running.")
        make_standup("tm-5", standup_dates[3],
            [],
            [{"title": "Mobile push v2 - deep linking", "ticketId": "ACME-305"}, {"title": "iOS widget feature", "ticketId": "ACME-309"}],
            [], "James Wilson deep linking PR opened. iOS widget scaffold committed.")
        make_standup("tm-6", standup_dates[3],
            [{"title": "Recommendation engine v2", "ticketId": "ACME-306"}],
            [{"title": "Order tracking feature", "ticketId": "ACME-312"}],
            [], "Emma Davis recommendation engine v2 merged! Starting order tracking feature.")

        # -- Mar 3 (Day 7) --
        make_standup("tm-1", standup_dates[4],
            [],
            [{"title": "Checkout flow v2 - payment form", "ticketId": "ACME-301"}, {"title": "Accessibility audit fixes", "ticketId": "ACME-311"}],
            [], "Alex Chen payment form validation complete. Accessibility PR approved, awaiting merge.")
        make_standup("tm-2", standup_dates[4],
            [],
            [{"title": "API gateway optimization", "ticketId": "ACME-302"}],
            [{"description": "API gateway changes requested - need to rework caching strategy", "status": "OPEN"}],
            "Sarah Kim got changes requested on API gateway PR. Reworking caching approach.")
        make_standup("tm-3", standup_dates[4],
            [{"title": "Product card redesign", "ticketId": "ACME-303"}],
            [],
            [], "Marcus Johnson product card done. Waiting for next assignment (email templates).",
            ack=True, note="Product card redesign shipped. Ready for email templates task.")
        make_standup("tm-4", standup_dates[4],
            [],
            [{"title": "Monitoring dashboard", "ticketId": "ACME-304"}, {"title": "Infra cost optimization", "ticketId": "ACME-310"}],
            [], "Priya Patel monitoring dashboard alerting configured. Still working late hours.",
            note="Had to fix critical alerts again. Running on low sleep.")
        make_standup("tm-5", standup_dates[4],
            [],
            [{"title": "Mobile push v2 - deep linking", "ticketId": "ACME-305"}, {"title": "iOS widget feature", "ticketId": "ACME-309"}],
            [], "James Wilson deep linking PR awaiting review. iOS widget making progress.")
        make_standup("tm-6", standup_dates[4],
            [],
            [{"title": "Order tracking feature", "ticketId": "ACME-312"}],
            [], "Emma Davis building order tracking data models and API endpoints.")

        # -- Mar 4 (Day 8 - yesterday) --
        make_standup("tm-1", standup_dates[5],
            [],
            [{"title": "Checkout flow v2 - payment form", "ticketId": "ACME-301"}],
            [], "Alex Chen payment form PR opened for review. Working on submit handler.",
            note="Payment form v2 PR is ready for review. Please take a look when you can.")
        sr_mar4_sarah = make_standup("tm-2", standup_dates[5],
            [],
            [{"title": "API gateway optimization", "ticketId": "ACME-302"}],
            [{"description": "CI failing on API gateway PR after caching rework", "status": "OPEN"}],
            "Sarah Kim reworking API gateway caching. CI is failing - investigating.")
        make_standup("tm-3", standup_dates[5],
            [{"title": "Product card redesign", "ticketId": "ACME-303"}],
            [],
            [], "Marcus Johnson completed all assigned work. Picking up email templates next.",
            ack=True)
        make_standup("tm-4", standup_dates[5],
            [],
            [{"title": "Monitoring dashboard", "ticketId": "ACME-304"}, {"title": "Infra cost optimization", "ticketId": "ACME-310"}],
            [], "Priya Patel monitoring PR opened. Working on infra cost analysis.")
        make_standup("tm-5", standup_dates[5],
            [],
            [{"title": "Mobile push v2 - deep linking", "ticketId": "ACME-305"}, {"title": "iOS widget feature", "ticketId": "ACME-309"}],
            [{"description": "Waiting for deep linking PR review - approaching 24h threshold", "status": "OPEN"}],
            "James Wilson PR #23 awaiting review for 16h. iOS widget basic scaffold committed.",
            note="PR #23 for deep linking is ready. Could someone review it today?")
        make_standup("tm-6", standup_dates[5],
            [],
            [{"title": "Order tracking feature", "ticketId": "ACME-312"}],
            [], "Emma Davis order tracking endpoints PR opened. Good progress.",
            note="Order tracking API endpoints are up for review.")

        # Create blocker flags for Sarah's Mar 4 standup
        bf1 = BlockerFlag(
            id="bf-1",
            standup_report_id=sr_mar4_sarah.id,
            description="CI failing on API gateway PR after caching rework",
            ticket_reference="ACME-302",
            status="OPEN",
        )
        session.add(bf1)

        # ================================================================
        # 13. TEAM STANDUP DIGESTS (for each standup day)
        # ================================================================
        digest_data = [
            ("tsd-1", standup_dates[0], 10.0,  83.0, "GREEN", [], 0, "Sprint 24 Day 1. Team ramping up. All developers assigned and active."),
            ("tsd-2", standup_dates[1], 15.0,  100.0,"GREEN", [], 0, "Sprint 24 Day 2. Good momentum. 2 commits per developer on average."),
            ("tsd-3", standup_dates[2], 25.0,  100.0,"GREEN", [], 0, "Sprint 24 Day 3. DB indexing completed. Product card PR opened."),
            ("tsd-4", standup_dates[3], 50.0,  100.0,"GREEN", [], 0, "Sprint 24 Day 6. 3 items done (product card, DB indexing, rec engine). Good pacing."),
            ("tsd-5", standup_dates[4], 58.0,  83.0, "AMBER", ["wi-2"], 1, "Sprint 24 Day 7. API gateway got changes requested. 1 blocker flagged."),
            ("tsd-6", standup_dates[5], 62.0,  83.0, "AMBER", ["wi-2", "wi-5"], 2, "Sprint 24 Day 8. 2 blockers active. API gateway CI failing, deep link PR awaiting review."),
        ]
        for did, ddate, pacing, ack_pct, health, at_risk, blockers, summary in digest_data:
            d = TeamStandupDigest(
                id=did,
                organization_id="demo-org",
                iteration_id="iter-1",
                digest_date=ddate,
                sprint_pacing=pacing,
                acknowledged_pct=ack_pct,
                sprint_health=health,
                at_risk_items={"items": [{"workItemId": w} for w in at_risk]},
                blocker_count=blockers,
                summary_text=summary,
            )
            session.add(d)

        # ================================================================
        # 14. SPRINT PLANS + ASSIGNMENTS
        # ================================================================

        # Sprint 22 Plan (SYNCED - old, completed)
        plan22 = SprintPlan(
            id="plan-22",
            organization_id="demo-org",
            project_id="proj-1",
            iteration_id="iter-22",
            status="SYNCED",
            confidence_score=88.0,
            risk_summary="Low risk sprint. Well-scoped features with experienced team.",
            total_story_points=36.0,
            ai_model_used="claude-sonnet",
            approved_by_id="demo-user-1",
            approved_at=utc(2026, 1, 26, 10),
            synced_at=utc(2026, 1, 26, 10, 5),
            estimated_weeks_total=3,
            project_completion_summary="At current velocity, project backlog estimated at 3 sprints (~6 weeks).",
            capacity_recommendations={"team_utilization_pct": 82, "understaffed": False, "recommended_additions": 0, "bottleneck_skills": [], "summary": "Team is well-balanced for current backlog."},
        )
        session.add(plan22)

        # Sprint 23 Plan (SYNCED)
        plan23 = SprintPlan(
            id="plan-23",
            organization_id="demo-org",
            project_id="proj-1",
            iteration_id="iter-23",
            status="SYNCED",
            confidence_score=75.0,
            risk_summary="Payment integration has high complexity. Push notification service may spill.",
            total_story_points=50.0,
            ai_model_used="claude-sonnet",
            approved_by_id="demo-user-1",
            approved_at=utc(2026, 2, 9, 10),
            synced_at=utc(2026, 2, 9, 10, 5),
            estimated_weeks_total=4,
            project_completion_summary="With carry-forward items, estimated 4 weeks remaining.",
            capacity_recommendations={"team_utilization_pct": 90, "understaffed": False, "recommended_additions": 0, "bottleneck_skills": ["mobile"], "summary": "Mobile capacity is stretched. Consider pairing."},
        )
        session.add(plan23)

        # Sprint 24 Plan (APPROVED - current sprint)
        plan24 = SprintPlan(
            id="plan-1",
            organization_id="demo-org",
            project_id="proj-1",
            iteration_id="iter-1",
            status="APPROVED",
            confidence_score=82.0,
            risk_summary="Payment form v2 is critical path. Priya's capacity at risk due to dual-tasking.",
            overall_rationale="Balanced sprint targeting payments, monitoring, and mobile features. High-priority items assigned to strongest skill matches.",
            total_story_points=58.0,
            ai_model_used="claude-sonnet",
            approved_by_id="demo-user-1",
            approved_at=utc(2026, 2, 23, 10),
            estimated_sprints=2,
            estimated_end_date=utc(2026, 3, 20),
            success_probability=75,
            spillover_risk_sp=8,
            estimated_weeks_total=6,
            project_completion_summary="Based on current velocity and remaining backlog of 79 SP, the project is estimated to require approximately 6 more weeks (3 sprints) to complete all items.",
            capacity_recommendations={
                "team_utilization_pct": 85,
                "understaffed": False,
                "recommended_additions": 0,
                "bottleneck_skills": ["devops"],
                "summary": "DevOps capacity (Priya) is stretched at 109% utilization. Consider redistributing infra cost optimization to next sprint."
            },
        )
        session.add(plan24)

        # Sprint 24 Assignments
        assignments_data = [
            ("pa-1",  "plan-1", "wi-1",  "tm-1", 8,  0.91, "Strong frontend skills - 8 similar React tickets completed. Available capacity of 40 SP makes this a comfortable fit.", 1, None),
            ("pa-2",  "plan-1", "wi-2",  "tm-2", 5,  0.88, "Backend expertise with FastAPI and PostgreSQL. Previously optimized similar API endpoints.", 1, None),
            ("pa-3",  "plan-1", "wi-3",  "tm-3", 5,  0.92, "Animation specialist with proven track record on similar UI component work.", 1, None),
            ("pa-4",  "plan-1", "wi-4",  "tm-4", 3,  0.95, "DevOps lead. Kubernetes and monitoring are core competencies.", 1, None),
            ("pa-5",  "plan-1", "wi-5",  "tm-5", 8,  0.82, "Continuing push notification work from Sprint 23. Deep context already established.", 1, None),
            ("pa-6",  "plan-1", "wi-6",  "tm-6", 5,  0.90, "ML background ideally suited for recommendation engine improvements.", 1, None),
            ("pa-7",  "plan-1", "wi-7",  "tm-3", 5,  0.85, "Frontend skills match for email templates. Second assignment this sprint.", 2, 3),
            ("pa-8",  "plan-1", "wi-8",  "tm-2", 3,  0.93, "Database expertise. Quick task given proven PostgreSQL optimization skills.", 1, None),
            ("pa-9",  "plan-1", "wi-9",  "tm-5", 5,  0.80, "iOS expertise for widget feature. Parallel with push notification work.", 1, None),
            ("pa-10", "plan-1", "wi-10", "tm-4", 3,  0.88, "Terraform and AWS cost analysis within DevOps scope.", 1, None),
            ("pa-11", "plan-1", "wi-11", "tm-1", 3,  0.86, "Frontend developer handling accessibility fixes for own components.", 2, None),
            ("pa-12", "plan-1", "wi-12", "tm-6", 8,  0.84, "Backend + data pipeline expertise for order tracking feature.", 1, None),
        ]
        for paid, plan_id, wi_id, tm_id, sp, conf, rationale, sprint_num, suggested_priority in assignments_data:
            pa = PlanAssignment(
                id=paid,
                sprint_plan_id=plan_id,
                work_item_id=wi_id,
                team_member_id=tm_id,
                story_points=sp,
                confidence_score=conf,
                rationale=rationale,
                risk_flags=[],
                sprint_number=sprint_num,
                suggested_priority=suggested_priority,
            )
            session.add(pa)

        # ================================================================
        # 15. VELOCITY PROFILES (8 sprints x 6 members = 48)
        # ================================================================
        sprint_iterations = [
            "sprint-17", "sprint-18", "sprint-19", "sprint-20",
            "sprint-21", "iter-22", "iter-23", "iter-1",
        ]
        velocity_data = {
            "tm-1": [(8,7), (10,9), (8,8), (10,8), (8,7), (10,10), (11,9),  (11,5)],
            "tm-2": [(13,11),(10,10),(13,12),(10,8),(13,10),(10,9),  (16,15), (13,8)],
            "tm-3": [(5,5),  (8,7),  (5,4),  (8,8), (5,5),  (8,6),  (5,5),   (5,5)],
            "tm-4": [(3,3),  (5,4),  (3,3),  (5,5), (3,2),  (5,5),  (6,6),   (6,3)],
            "tm-5": [(8,6),  (8,7),  (10,8), (8,8), (8,7),  (10,9), (8,5),   (13,3)],
            "tm-6": [(5,5),  (8,8),  (5,5),  (8,7), (5,5),  (8,8),  (7,7),   (13,5)],
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
                    iteration_id=sprint_iterations[i],
                    planned_sp=planned,
                    completed_sp=completed,
                    rolling_average=round(rolling_avg, 1),
                    by_ticket_type={"story": int(completed * 0.7), "bug": int(completed * 0.15), "task": int(completed * 0.15)},
                    is_cold_start=(i < 2),
                )
                session.add(vp)
                vp_count += 1

        # ================================================================
        # 16. HEALTH SIGNALS (6 signals)
        # ================================================================
        signals_data = [
            ("hs-1", "tm-4", "AFTER_HOURS",       "RED",   "52% of activity is after hours (26/50 events). Priya is consistently working beyond 6 PM.", {"ratio": 0.52, "after_hours": 26, "total": 50}),
            ("hs-2", "tm-4", "CAPACITY_OVERLOAD",  "RED",   "Priya at 109% capacity utilization for 3 consecutive sprints", {"utilization": 1.09, "sprints": 3}),
            ("hs-3", "tm-2", "STALLED_TICKET",     "AMBER", "ACME-302 (API gateway) has CI failing for 36 hours", {"ticketId": "ACME-302", "hoursStalled": 36}),
            ("hs-4", "tm-5", "REVIEW_LAG",         "AMBER", "PR #23 (deep linking) awaiting review for 20 hours", {"prNumber": 23, "hoursWaiting": 20}),
            ("hs-5", "tm-4", "BURNOUT_RISK",       "RED",   "Burnout risk detected: after-hours work + weekend commits + capacity overload", {"afterHoursRatio": 0.52, "weekendEvents": 4, "consecutiveSprints": 3}),
            ("hs-6", "tm-6", "INACTIVITY",         "GREEN", "Emma's activity has been lower than usual this week", {"lastActivity": "2026-03-04T14:00:00Z"}),
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

        # ================================================================
        # 17. BURNOUT ALERTS (2 alerts)
        # ================================================================
        ba1 = BurnoutAlert(
            id="ba-1",
            organization_id="demo-org",
            team_member_id="tm-4",
            severity="RED",
            capacity_utilization=1.09,
            consecutive_sprints=3,
            after_hours_frequency=0.52,
        )
        ba2 = BurnoutAlert(
            id="ba-2",
            organization_id="demo-org",
            team_member_id="tm-5",
            severity="AMBER",
            capacity_utilization=0.95,
            consecutive_sprints=2,
            after_hours_frequency=0.12,
        )
        session.add_all([ba1, ba2])

        # ================================================================
        # 18. RETROSPECTIVES (for Sprint 22 and Sprint 23)
        # ================================================================

        # Sprint 22 Retro (successful sprint)
        retro22 = Retrospective(
            id="retro-22",
            organization_id="demo-org",
            iteration_id="iter-22",
            what_went_well=[
                "AI sprint planning saved the team ~2 hours of manual planning",
                "All 7 items completed - 100% delivery rate",
                "CI/CD pipeline setup by Priya enabled faster deployments",
                "Good cross-team collaboration between frontend and backend",
            ],
            what_didnt_go_well=[
                "Some story point estimates were slightly optimistic",
                "PR review turnaround averaged 18 hours (target: 12h)",
            ],
            root_cause_analysis={
                "key_issues": ["Estimation calibration needed", "PR review process"],
                "recommendations": ["Use reference class forecasting for estimates", "Add PR review SLA reminders"],
            },
            is_draft=False,
            finalized_at=utc(2026, 2, 7, 16),
        )
        session.add(retro22)

        rai_22_1 = RetroActionItem(
            id="rai-22-1",
            retrospective_id="retro-22",
            title="Add PR review SLA reminder to Slack notifications",
            assignee_id="tm-4",
            status="completed",
        )
        rai_22_2 = RetroActionItem(
            id="rai-22-2",
            retrospective_id="retro-22",
            title="Conduct estimation calibration session with team",
            assignee_id="tm-1",
            status="completed",
        )
        session.add_all([rai_22_1, rai_22_2])

        # Sprint 23 Retro (partial completion - more actionable)
        retro23 = Retrospective(
            id="retro-23",
            organization_id="demo-org",
            iteration_id="iter-23",
            what_went_well=[
                "Checkout flow redesign delivered on time with good quality",
                "Stripe payment integration completed despite complexity",
                "Team adapted well to new CI/CD pipeline",
            ],
            what_didnt_go_well=[
                "Push notification service did not complete - carried forward",
                "Order confirmation page was not started at all",
                "Priya worked excessive after-hours to meet K8s deadline",
                "Sprint was slightly over-committed at 50 SP (team avg velocity: 42 SP)",
            ],
            root_cause_analysis={
                "key_issues": [
                    "Over-commitment relative to team velocity",
                    "Push notification had hidden complexity (deep linking)",
                    "DevOps tasks underestimated - Priya overloaded",
                ],
                "recommendations": [
                    "Cap sprint commitment at 85% of average velocity",
                    "Break down push notification into smaller deliverables",
                    "Redistribute infra work or hire DevOps support",
                ],
            },
            failure_classification="over_commitment",
            failure_evidence={
                "planned_sp": 50,
                "completed_sp": 37,
                "carry_forward_items": ["ACME-206", "ACME-207"],
                "completion_rate": 0.74,
            },
            pattern_detected=True,
            consecutive_failure_count=1,
            feed_forward_signals=[
                {"type": "capacity_warning", "message": "Priya at 109% utilization - reduce next sprint load"},
                {"type": "estimation_adjustment", "message": "Mobile features consistently underestimated by 30%"},
            ],
            is_draft=False,
            finalized_at=utc(2026, 2, 21, 16),
        )
        session.add(retro23)

        rai_23_1 = RetroActionItem(
            id="rai-23-1",
            retrospective_id="retro-23",
            title="Cap sprint commitment at 85% of rolling velocity average",
            assignee_id="tm-1",
            status="open",
            is_carry_forward=True,
        )
        rai_23_2 = RetroActionItem(
            id="rai-23-2",
            retrospective_id="retro-23",
            title="Break push notification into 3 smaller stories for Sprint 24",
            assignee_id="tm-5",
            status="completed",
        )
        rai_23_3 = RetroActionItem(
            id="rai-23-3",
            retrospective_id="retro-23",
            title="Review Priya's workload - consider pairing on infra tasks",
            assignee_id="tm-4",
            status="open",
        )
        session.add_all([rai_23_1, rai_23_2, rai_23_3])

        # ================================================================
        # 19. AUDIT LOG ENTRIES (key events across lifecycle)
        # ================================================================
        audit_data = [
            ("al-1",  "connection.created",      "ToolConnection", "conn-jira",   utc(2026, 1, 20, 10)),
            ("al-2",  "sync.completed",          "ToolConnection", "conn-jira",   utc(2026, 1, 20, 10, 1)),
            ("al-3",  "connection.created",      "ToolConnection", "conn-github", utc(2026, 1, 20, 10, 5)),
            ("al-4",  "sync.completed",          "ToolConnection", "conn-github", utc(2026, 1, 20, 10, 6)),
            ("al-5",  "project.imported",        "ImportedProject","proj-1",      utc(2026, 1, 20, 10, 10)),
            ("al-6",  "sprint_plan.generated",   "SprintPlan",     "plan-22",     utc(2026, 1, 26, 9, 50)),
            ("al-7",  "sprint_plan.approved",    "SprintPlan",     "plan-22",     utc(2026, 1, 26, 10)),
            ("al-8",  "writeback.executed",      "SprintPlan",     "plan-22",     utc(2026, 1, 26, 10, 1)),
            ("al-9",  "sprint_plan.generated",   "SprintPlan",     "plan-23",     utc(2026, 2, 9, 9, 50)),
            ("al-10", "sprint_plan.approved",    "SprintPlan",     "plan-23",     utc(2026, 2, 9, 10)),
            ("al-11", "writeback.executed",      "SprintPlan",     "plan-23",     utc(2026, 2, 9, 10, 1)),
            ("al-12", "retrospective.generated", "Retrospective",  "retro-22",    utc(2026, 2, 7, 15)),
            ("al-13", "retrospective.finalized", "Retrospective",  "retro-22",    utc(2026, 2, 7, 16)),
            ("al-14", "retrospective.generated", "Retrospective",  "retro-23",    utc(2026, 2, 21, 15)),
            ("al-15", "retrospective.finalized", "Retrospective",  "retro-23",    utc(2026, 2, 21, 16)),
            ("al-16", "sprint_plan.generated",   "SprintPlan",     "plan-1",      utc(2026, 2, 23, 9, 50)),
            ("al-17", "sprint_plan.approved",    "SprintPlan",     "plan-1",      utc(2026, 2, 23, 10)),
            ("al-18", "sync.completed",          "ToolConnection", "conn-jira",   utc(2026, 3, 5, 8, 0)),
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

        # ================================================================
        # COMMIT ALL DATA
        # ================================================================
        await session.commit()

        print("\n[OK] Comprehensive seed data committed successfully!")
        print(f"   - 1 Organization (Acme Technologies)")
        print(f"   - 1 User (Product Owner)")
        print(f"   - 6 TeamMembers")
        print(f"   - 2 ToolConnections (Jira + GitHub)")
        print(f"   - 1 ImportedProject (Acme Checkout Platform)")
        print(f"   - 3 Iterations (Sprint 22 closed, Sprint 23 closed, Sprint 24 active)")
        print(f"   - {len(all_items)} WorkItems across sprints")
        print(f"   - 5 Repositories")
        print(f"   - {len(prs_data)} PullRequests, {len(commits_data)} Commits")
        print(f"   - {ae_counter[0]} ActivityEvents (with after-hours + weekend events)")
        print(f"   - {sr_counter[0]} StandupReports + {len(digest_data)} TeamStandupDigests")
        print(f"   - 3 SprintPlans + {len(assignments_data)} PlanAssignments")
        print(f"   - {vp_count} VelocityProfiles (6 members x 8 sprints)")
        print(f"   - {len(signals_data)} HealthSignals, 2 BurnoutAlerts")
        print(f"   - 2 Retrospectives + 5 RetroActionItems")
        print(f"   - {len(audit_data)} AuditLogEntries")
        print(f"\n   Sprint 24 status:")
        print(f"     Done: wi-3 (Product card), wi-6 (Rec engine), wi-8 (DB indexing)")
        print(f"     In Progress: wi-1 (Checkout v2), wi-4 (Monitoring), wi-5 (Push v2), wi-9 (iOS widget), wi-10 (Infra cost), wi-12 (Order tracking)")
        print(f"     In Review: wi-2 (API gateway), wi-11 (Accessibility)")
        print(f"     Todo: wi-7 (Email templates)")
        print(f"     Backlog: wi-13, wi-14 (future)")
        print(f"\n   Burnout indicators:")
        print(f"     Priya Patel: RED - 52% after-hours, weekend work, 109% capacity x 3 sprints")
        print(f"     James Wilson: AMBER - 95% capacity x 2 sprints")
        print(f"\n   Today's standups will auto-generate from real data on page load.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())

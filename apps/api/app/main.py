import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings

# Hotfix 32 — Step C: surface application logs at INFO level.
# Without this, every ``logger.info(...)`` in the codebase is silently
# dropped because Python's default logger level is WARNING. Container
# Apps reads stdout, so as long as we emit a record we'll see it. We
# also force-propagate to root so per-module loggers don't get
# accidentally suppressed by uvicorn's default config.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
# Reduce noisy libraries that shouldn't drown our own output.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# Import routers
from .routers import analytics, dashboard, github, sprints, standups, team_health, notifications, projects, writeback, ws, retrospectives, phases, organizations, profile, agents, export, notes, reports
from .routers.integrations import connections, sync, audit_log
from .routers.integrations import jira as jira_router
from .routers.integrations import ado as ado_router
from .routers.integrations import github as github_int_router
from .routers.integrations import slack as slack_router
from .routers.integrations import teams as teams_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"Plan2Sprint API starting... (demo_mode={settings.is_demo_mode})")

    # Auto-migrate: add new columns if they don't exist
    from .database import engine
    from sqlalchemy import text
    try:
        async with engine.begin() as conn:
            # source_status on work_items (Task 3 — dynamic board columns)
            await conn.execute(text(
                "ALTER TABLE work_items ADD COLUMN IF NOT EXISTS source_status VARCHAR(100)"
            ))
            # in_app_notifications table (Task 2 — notification system)
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS in_app_notifications (
                    id VARCHAR(25) PRIMARY KEY,
                    organization_id VARCHAR(25) NOT NULL,
                    recipient_email VARCHAR NOT NULL,
                    notification_type VARCHAR NOT NULL,
                    title VARCHAR NOT NULL,
                    body TEXT NOT NULL,
                    read BOOLEAN DEFAULT FALSE,
                    data_json JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_in_app_notifications_org ON in_app_notifications(organization_id)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_in_app_notifications_email ON in_app_notifications(recipient_email)"
            ))
            # planned_start / planned_end on work_items (Feature/Epic progress + Gantt)
            await conn.execute(text(
                "ALTER TABLE work_items ADD COLUMN IF NOT EXISTS planned_start TIMESTAMPTZ"
            ))
            await conn.execute(text(
                "ALTER TABLE work_items ADD COLUMN IF NOT EXISTS planned_end TIMESTAMPTZ"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_work_items_epic_id ON work_items(epic_id)"
            ))
            # invitations table (Workspace & Org Management)
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS invitations (
                    id VARCHAR(25) PRIMARY KEY,
                    organization_id VARCHAR(25) NOT NULL REFERENCES organizations(id),
                    email VARCHAR NOT NULL,
                    role VARCHAR(50) NOT NULL DEFAULT 'developer',
                    token VARCHAR UNIQUE NOT NULL,
                    invited_by VARCHAR NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    expires_at TIMESTAMPTZ NOT NULL,
                    accepted_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_invitations_org ON invitations(organization_id)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_invitations_token ON invitations(token)"
            ))
            # stakeholder_project_assignments table
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS stakeholder_project_assignments (
                    id VARCHAR(25) PRIMARY KEY,
                    user_id VARCHAR(25) NOT NULL REFERENCES users(id),
                    imported_project_id VARCHAR(25) NOT NULL REFERENCES imported_projects(id),
                    organization_id VARCHAR(25) NOT NULL REFERENCES organizations(id),
                    assigned_by VARCHAR(25),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_id, imported_project_id)
                )
            """))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_stakeholder_proj_user ON stakeholder_project_assignments(user_id)"
            ))
            # Per-developer GitHub connection fields
            await conn.execute(text(
                "ALTER TABLE team_members ADD COLUMN IF NOT EXISTS github_username VARCHAR"
            ))
            await conn.execute(text(
                "ALTER TABLE team_members ADD COLUMN IF NOT EXISTS github_access_token VARCHAR"
            ))
            # Hotfix 73 / 74 — per-user Slack/Teams identity link.
            # When a developer or stakeholder OAuths their personal
            # Slack / Teams account, we store the resulting account
            # ID on the User row (one row per person, vs team_members
            # which is one row per project). The message router prefers
            # this over the legacy team_members lookup.
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS slack_user_id VARCHAR"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS slack_team_id VARCHAR"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS slack_team_name VARCHAR"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS slack_handle VARCHAR"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS teams_user_id VARCHAR"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS teams_user_principal_name VARCHAR"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS teams_display_name VARCHAR"
            ))
            # Timeline revamp (Sprint 1) — target launch date + persisted phase
            # dates + Ready phase backfill. Idempotent: ALTER IF NOT EXISTS, and
            # the Ready insert skips projects that already have it.
            await conn.execute(text(
                "ALTER TABLE imported_projects ADD COLUMN IF NOT EXISTS target_launch_date TIMESTAMPTZ"
            ))
            await conn.execute(text(
                "ALTER TABLE imported_projects ADD COLUMN IF NOT EXISTS target_launch_source VARCHAR(10)"
            ))
            await conn.execute(text(
                "ALTER TABLE project_phases ADD COLUMN IF NOT EXISTS planned_start TIMESTAMPTZ"
            ))
            await conn.execute(text(
                "ALTER TABLE project_phases ADD COLUMN IF NOT EXISTS planned_end TIMESTAMPTZ"
            ))
            # Backfill Ready phase for every project that doesn't have one.
            # Using cuid-ish random id (25 chars: 'c' + 24 random hex) to match
            # the format generate_cuid() produces elsewhere.
            await conn.execute(text("""
                INSERT INTO project_phases (
                    id, organization_id, project_id, name, slug, color,
                    sort_order, is_default, created_at, updated_at
                )
                SELECT
                    'c' || substr(md5(random()::text || ip.id), 1, 24),
                    ip.organization_id,
                    ip.id,
                    'Ready',
                    'ready',
                    '#10b981',
                    6,
                    FALSE,
                    NOW(),
                    NOW()
                FROM imported_projects ip
                WHERE NOT EXISTS (
                    SELECT 1 FROM project_phases pp
                    WHERE pp.project_id = ip.id AND pp.slug = 'ready'
                )
            """))
        print("Auto-migration complete.")
    except Exception as e:
        print(f"WARNING: DB migration skipped (DB unreachable): {e}")

    # Hotfix 32 — Step D: heal stuck GENERATING sprint plans on startup.
    # Background tasks die when the container scales to 0 (Container Apps
    # does not gracefully wait for FastAPI BackgroundTasks). A user who
    # hits Regenerate then closes their tab leaves a GENERATING stub in
    # the DB forever, which then occupies the "latest plan" slot and
    # blanks out their dashboard. On startup, mark anything stuck for
    # >5 min as FAILED with an actionable message. Best-effort — never
    # block startup if this fails.
    try:
        async with engine.begin() as conn:
            recovered = await conn.execute(text(
                """
                UPDATE sprint_plans
                   SET status = 'FAILED',
                       risk_summary = COALESCE(
                           NULLIF(risk_summary, ''),
                           'Generation interrupted (container restarted before completion). Click Regenerate to try again.'
                       )
                 WHERE status = 'GENERATING'
                   AND created_at < NOW() - INTERVAL '5 minutes'
                """
            ))
            if recovered.rowcount:
                print(f"Healed {recovered.rowcount} stuck GENERATING sprint plan(s) on startup")
    except Exception as e:
        print(f"WARNING: stuck-plan recovery skipped: {e}")

    # Start the delivery queue background worker
    from .services.delivery_queue import start_delivery_worker, stop_delivery_worker
    await start_delivery_worker()

    # Start Redis-backed services (graceful if Redis unavailable)
    from .services.ws_relay import start_ws_relay
    from .services.sync_scheduler import start_sync_scheduler

    ws_relay_task = await start_ws_relay()
    sync_scheduler_task = await start_sync_scheduler()

    # Start notification scheduler (daily digests, nudges)
    from .services.notification_scheduler import start_notification_scheduler, stop_notification_scheduler
    await start_notification_scheduler()

    # Hotfix 56 (MED-5) — verify every OAuth redirect_uri points at a host
    # we know belongs to Plan2Sprint. A misconfigured env var that points
    # at attacker.example.com would let any provider's auth code be
    # delivered to the attacker. We don't crash on mismatch (some
    # deployments use bespoke hosts) but we LOG LOUDLY so the misconfig
    # is visible during routine log review.
    _allowed_redirect_hosts = {
        "localhost",
        "127.0.0.1",
        # API's deployed FQDN (Container Apps default + custom domain)
        "plan2sprint-api.purplebeach-150945ee.westus3.azurecontainerapps.io",
        "api.plan2sprint.com",
    }
    from urllib.parse import urlparse as _urlparse
    import os as _os
    # Pull redirect URIs defensively — some are on Settings, GITHUB is
    # read directly from os.environ at the consumer site, and others
    # may be missing entirely on a misconfigured deployment. Use
    # ``getattr(..., "", "")`` so an unset attribute doesn't crash boot.
    _redirect_uris = (
        ("jira_redirect_uri", getattr(settings, "jira_redirect_uri", "") or ""),
        ("ado_redirect_uri", getattr(settings, "ado_redirect_uri", "") or ""),
        ("github_redirect_uri", _os.environ.get("GITHUB_REDIRECT_URI", "")),
        ("slack_redirect_uri", getattr(settings, "slack_redirect_uri", "") or ""),
        ("teams_redirect_uri", getattr(settings, "teams_redirect_uri", "") or ""),
    )
    for label, value in _redirect_uris:
        if not value:
            continue
        host = (_urlparse(value).hostname or "").lower()
        if host and host not in _allowed_redirect_hosts:
            logging.warning(
                f"[SECURITY] {label} points at unfamiliar host '{host}'. "
                f"If this is intentional add it to _allowed_redirect_hosts; "
                f"otherwise OAuth codes could be redirected to an attacker."
            )

    yield

    # Shutdown — stop background tasks
    await stop_notification_scheduler()
    if sync_scheduler_task:
        sync_scheduler_task.cancel()
        try:
            await sync_scheduler_task
        except asyncio.CancelledError:
            pass
    if ws_relay_task:
        ws_relay_task.cancel()
        try:
            await ws_relay_task
        except asyncio.CancelledError:
            pass

    from .services.redis_pool import close_redis
    await close_redis()

    await stop_delivery_worker()
    from .database import engine
    await engine.dispose()
    print("Plan2Sprint API shut down.")

app = FastAPI(
    title="Plan2Sprint API",
    version="1.0.0",
    description="AI-powered sprint planning backend",
    lifespan=lifespan,
    redirect_slashes=False,
)

# Trust proxy headers (X-Forwarded-Proto, X-Forwarded-For) so redirects use https
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# CORS — restrict to safe methods only
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Health check — minimal info to prevent config leakage
@app.get("/health")
async def health_check():
    redis_status = "disabled"
    if settings.redis_enabled:
        try:
            from .services.redis_pool import get_redis
            redis = await get_redis()
            if redis:
                await redis.ping()
                redis_status = "connected"
            else:
                redis_status = "unavailable"
        except Exception:
            redis_status = "unavailable"

    return {
        "status": "ok",
        "redis": redis_status,
    }

# Mount routers
app.include_router(analytics.router, prefix="/api", tags=["analytics"])
app.include_router(dashboard.router, prefix="/api", tags=["dashboard"])
app.include_router(github.router, prefix="/api", tags=["github"])
app.include_router(sprints.router, prefix="/api", tags=["sprints"])
app.include_router(standups.router, prefix="/api", tags=["standups"])
app.include_router(team_health.router, prefix="/api", tags=["team-health"])
app.include_router(notifications.router, prefix="/api", tags=["notifications"])
app.include_router(connections.router, prefix="/api/integrations", tags=["integrations-connections"])
app.include_router(sync.router, prefix="/api/integrations", tags=["integrations-sync"])
app.include_router(audit_log.router, prefix="/api/integrations", tags=["integrations-audit"])
app.include_router(jira_router.router, prefix="/api/integrations/jira", tags=["integrations-jira"])
app.include_router(ado_router.router, prefix="/api/integrations/ado", tags=["integrations-ado"])
app.include_router(github_int_router.router, prefix="/api/integrations/github", tags=["integrations-github"])
app.include_router(slack_router.router, prefix="/api/integrations/slack", tags=["integrations-slack"])
app.include_router(teams_router.router, prefix="/api/integrations/teams", tags=["integrations-teams"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(writeback.router, prefix="/api", tags=["writeback"])
app.include_router(retrospectives.router, prefix="/api", tags=["retrospectives"])
app.include_router(ws.router, prefix="/api", tags=["websocket"])
app.include_router(phases.router, prefix="/api", tags=["phases"])
app.include_router(organizations.router, prefix="/api/organizations", tags=["organizations"])
app.include_router(profile.router, prefix="/api", tags=["profile"])
app.include_router(notes.router, prefix="/api", tags=["notes"])
app.include_router(reports.router, prefix="/api", tags=["reports"])
app.include_router(agents.router, prefix="/api", tags=["agents"])
app.include_router(export.router, prefix="/api", tags=["export"])

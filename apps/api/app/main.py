import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings

# Import routers
from .routers import analytics, dashboard, github, sprints, standups, team_health, notifications, projects, writeback, ws, retrospectives, phases, organizations, profile, agents, export
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
        print("Auto-migration complete.")
    except Exception as e:
        print(f"WARNING: DB migration skipped (DB unreachable): {e}")

    # Start the delivery queue background worker
    from .services.delivery_queue import start_delivery_worker, stop_delivery_worker
    await start_delivery_worker()

    # Start Redis-backed services (graceful if Redis unavailable)
    from .services.ws_relay import start_ws_relay
    from .services.sync_scheduler import start_sync_scheduler

    ws_relay_task = await start_ws_relay()
    sync_scheduler_task = await start_sync_scheduler()

    yield

    # Shutdown — stop background tasks
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
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check
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
        "demo_mode": settings.is_demo_mode,
        "debug": settings.debug,
        "redis": redis_status,
        "sync_scheduler": settings.sync_scheduler_enabled,
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
app.include_router(agents.router, prefix="/api", tags=["agents"])
app.include_router(export.router, prefix="/api", tags=["export"])

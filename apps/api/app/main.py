from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings

# Import routers
from .routers import analytics, dashboard, github, sprints, standups, team_health, notifications, projects, writeback, ws, retrospectives
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

    # Start the delivery queue background worker
    from .services.delivery_queue import start_delivery_worker, stop_delivery_worker
    await start_delivery_worker()

    yield

    # Shutdown
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
    return {
        "status": "ok",
        "demo_mode": settings.is_demo_mode,
        "debug": settings.debug,
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

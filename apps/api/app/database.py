from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from .config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    # Hotfix 25 — bumped from pool_size=2/overflow=3 (5 total) to a more
    # realistic capacity. Sprint generation runs in BackgroundTasks and
    # opens its own AsyncSession, the dashboard project-plan endpoint
    # also schedules background AI classification, plus WebSocket
    # broadcasts and the regular request handlers all need connections.
    # The previous limit was getting saturated within seconds when a
    # user clicked Generate more than once, surfacing as
    # "QueuePool limit of size 2 overflow 3 reached, timeout 30s".
    # 10 + 20 = up to 30 simultaneous connections is well within Azure
    # Postgres Flexible Server B2s defaults (~ 60-100 max conns) and
    # gives meaningful headroom for parallel work.
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=120,     # Recycle every 2 min
    pool_timeout=30,
    pool_reset_on_return="rollback",
    connect_args={
        "statement_cache_size": 0,   # Disable to avoid prepared statement conflicts
        "timeout": 15,               # Connection timeout
    },
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

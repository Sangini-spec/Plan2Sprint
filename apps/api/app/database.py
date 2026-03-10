from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from .config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,  # Never log SQL in hot path — use debug logging separately
    pool_size=20,  # Increased from 10 to handle concurrent dashboard requests
    max_overflow=30,  # Increased from 20 for burst traffic
    pool_pre_ping=True,
    pool_recycle=600,  # Recycle connections every 10 min to avoid stale connections
    connect_args={
        "statement_cache_size": 200,  # Re-enable query plan caching (was 0 = disabled!)
        "timeout": 10,  # Increased from 5s to avoid premature failures
    },
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

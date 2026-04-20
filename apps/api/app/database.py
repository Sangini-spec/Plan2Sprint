from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from .config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=2,          # Minimal pool — Azure PostgreSQL basic tier has limited slots
    max_overflow=3,       # Burst to 5 max
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

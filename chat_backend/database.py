from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from chat_backend.config import settings

# Pooling tuned for a long-lived container behind a pooler (gap D9): pre-ping
# before handing out a connection, recycle before the pooler drops idle ones,
# and size the pool below the pooler's own limit. A serverless deployment
# would swap this for `poolclass=NullPool` instead.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
)
SessionLocal = async_sessionmaker(engine, autoflush=False, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    async with SessionLocal() as session:
        yield session
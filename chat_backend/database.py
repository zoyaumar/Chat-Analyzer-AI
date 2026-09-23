from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from chat_backend.config import settings

engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, autoflush=False, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    async with SessionLocal() as session:
        yield session
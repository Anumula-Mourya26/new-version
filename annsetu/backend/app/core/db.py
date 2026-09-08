from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import get_settings

settings = get_settings()

is_sqlite = settings.DATABASE_URL.startswith("sqlite")

connect_args = {"check_same_thread": False} if is_sqlite else {}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def migrate_users_table(sync_conn):
            from sqlalchemy import inspect, text
            inspector = inspect(sync_conn)
            table_names = inspector.get_table_names()
            if 'users' in table_names:
                columns = [c['name'] for c in inspector.get_columns('users')]
                if 'pin' not in columns:
                    sync_conn.execute(text("ALTER TABLE users ADD COLUMN pin VARCHAR(10)"))
                # Backfill all pre-existing farmer and vendor accounts with default PIN 1234
                sync_conn.execute(text(
                    "UPDATE users SET pin = '1234' WHERE (pin IS NULL OR pin = '') AND role IN ('farmer', 'vendor')"
                ))

        await conn.run_sync(migrate_users_table)

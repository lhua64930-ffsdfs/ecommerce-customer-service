"""异步数据库连接与 Session 管理。"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,      # 取连接前心跳,避免 MySQL 8h 断连
    pool_recycle=3600,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖:每个请求一个 Session,异常自动回滚。

    注意:不在依赖里自动 commit —— 由 service 层显式提交,
    避免只读请求也产生事务开销。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

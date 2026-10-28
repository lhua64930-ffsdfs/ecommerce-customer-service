"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import app.models  # noqa: F401 - 注册全部 ORM 模型
from app.api.v1 import agent, analytics, chat, intent, knowledge, order, product
from app.core.config import settings
from app.core.database import AsyncSessionLocal, Base, engine
from app.core.seed import seed_all
from app.services.rag_service import RAGService
from app.utils.cache import close_redis, get_redis
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("应用启动中...")

    # 开发期自动建表;生产环境应使用 Alembic 迁移
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await seed_all(session)

    logger.info("应用启动完成")
    yield

    logger.info("应用关闭中...")
    await close_redis()
    await engine.dispose()
    logger.info("应用已关闭")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="售后智答 API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api/v1/chat", tags=["对话服务"])
app.include_router(intent.router, prefix="/api/v1/intent", tags=["意图识别"])
app.include_router(agent.router, prefix="/api/v1/agent", tags=["Agent服务"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["知识库"])
app.include_router(order.router, prefix="/api/v1/order", tags=["订单服务"])
app.include_router(product.router, prefix="/api/v1/product", tags=["商品服务"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["数据分析"])


@app.get("/")
async def root() -> dict:
    return {"message": "售后智答 API", "version": settings.VERSION}


@app.get("/health")
async def health_check() -> dict:
    database_ok = False
    redis_ok = False

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("数据库健康检查失败: {}", exc)

    try:
        redis_ok = bool(await get_redis().ping())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 健康检查失败: {}", exc)

    milvus_ok = await RAGService().health()

    return {
        "status": "healthy" if database_ok and redis_ok else "degraded",
        "database": database_ok,
        "redis": redis_ok,
        "milvus": milvus_ok,
        "version": settings.VERSION,
    }

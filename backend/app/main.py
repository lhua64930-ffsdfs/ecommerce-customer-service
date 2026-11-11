"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import app.models  # noqa: F401 - 注册全部 ORM 模型
from app.api.deps import require_admin
from app.api.v1 import (
    admin_users,
    agent,
    analytics,
    approvals,
    auth,
    chat,
    feedback,
    intent,
    jobs,
    knowledge,
    observability,
    order,
    product,
    rag_eval,
    review,
)
from app.agents.graph.checkpointer import (
    checkpointer_backend,
    close_checkpointer,
    init_checkpointer,
)
from app.core.auth_middleware import AuthMiddleware
from app.core.config import settings
from app.core.database import AsyncSessionLocal, Base, engine
from app.core.observability import shutdown_observability
from app.core.ratelimit_middleware import RateLimitMiddleware
from app.core.seed import seed_all
from app.services.rag_service import RAGService
from app.utils.cache import close_redis, get_redis, redis_configured
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("应用启动中...")
    if settings.AUTH_ENABLED and (
        len(settings.JWT_SECRET_KEY) < 32
        or settings.JWT_SECRET_KEY.startswith("please-change")
    ):
        raise RuntimeError(
            "AUTH_ENABLED=true 时必须配置至少 32 字节的 JWT_SECRET_KEY"
        )
    if settings.AUTH_ENABLED:
        logger.info("鉴权已启用")

    # 开发期自动建表;生产环境应使用 Alembic 迁移
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await seed_all(session)
    await init_checkpointer()

    logger.info("应用启动完成")
    yield

    logger.info("应用关闭中...")
    shutdown_observability()
    await close_checkpointer()
    await close_redis()
    await engine.dispose()
    logger.info("应用已关闭")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="售后智答 API",
    lifespan=lifespan,
)

app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["认证"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["对话服务"])
app.include_router(approvals.router, prefix="/api/v1/chat", tags=["售后审批"])
app.include_router(
    review.router,
    prefix="/api/v1/review",
    tags=["知识飞轮"],
    dependencies=[Depends(require_admin)],
)
app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["用户反馈"])
app.include_router(
    rag_eval.router,
    prefix="/api/v1/rag-eval",
    tags=["RAG 评测"],
    dependencies=[Depends(require_admin)],
)
app.include_router(
    jobs.router,
    prefix="/api/v1/jobs",
    tags=["后台作业"],
    dependencies=[Depends(require_admin)],
)
app.include_router(intent.router, prefix="/api/v1/intent", tags=["意图识别"])
app.include_router(
    agent.router,
    prefix="/api/v1/agent",
    tags=["Agent服务"],
    dependencies=[Depends(require_admin)],
)
app.include_router(
    knowledge.router,
    prefix="/api/v1/knowledge",
    tags=["知识库"],
    dependencies=[Depends(require_admin)],
)
app.include_router(order.router, prefix="/api/v1/order", tags=["订单服务"])
app.include_router(product.router, prefix="/api/v1/product", tags=["商品服务"])
app.include_router(
    analytics.router,
    prefix="/api/v1/analytics",
    tags=["数据分析"],
    dependencies=[Depends(require_admin)],
)
app.include_router(
    observability.router,
    prefix="/api/v1/observability",
    tags=["可观测"],
    dependencies=[Depends(require_admin)],
)
app.include_router(
    admin_users.router,
    prefix="/api/v1/admin/users",
    tags=["用户管理"],
    dependencies=[Depends(require_admin)],
)


@app.get("/")
async def root() -> dict:
    return {"message": "售后智答 API", "version": settings.VERSION}


@app.get("/health")
async def health_check() -> dict:
    database_ok = False
    redis_ok = False
    redis_on = redis_configured()

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("数据库健康检查失败: {}", exc)

    if redis_on:
        try:
            redis_ok = bool(await get_redis().ping())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis 健康检查失败: {}", exc)

    milvus_ok = await RAGService().health()
    healthy = database_ok and (redis_ok or not redis_on)

    return {
        "status": "healthy" if healthy else "degraded",
        "database": database_ok,
        "redis": redis_ok,
        "redis_configured": redis_on,
        "milvus": milvus_ok,
        "checkpointer": checkpointer_backend(),
        "version": settings.VERSION,
    }

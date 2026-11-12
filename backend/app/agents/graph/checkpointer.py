"""LangGraph checkpointer:SQLite 默认、Postgres 可选、内存兜底。

- 只在 lifespan 初始化一次,图每次请求编译但共享同一个 saver;
- thread_id 使用会话 ID,跨轮续接历史(MewHelp 风格);
  每轮的步骤/工具记录在图状态里重置,不会跨轮累加;
- 初始化失败降级 InMemorySaver,不阻断应用启动。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.utils.logger import logger

GRAPH_VERSION = "multi_step_v1"
_saver: Any = None
_cm: Any = None
_backend = "none"


def turn_thread_id(session_id: str, user_message_id: int | None = None) -> str:
    """会话级 thread:保留 user_message_id 参数只为兼容旧调用方。

    MewHelp 用 conversation_id 作为 checkpoint thread;这里统一用 session_id,
    每轮在图状态里重置 steps/tool_records/run_steps,消息由 add_messages 累积。
    """
    return session_id


def get_checkpointer() -> Any:
    return _saver


def checkpointer_backend() -> str:
    return _backend


async def init_checkpointer() -> Any:
    """按配置初始化;失败降级内存,保证应用可启动。"""
    global _saver, _cm, _backend

    if _saver is not None:
        return _saver

    backend = settings.CHECKPOINTER_BACKEND
    if backend == "none":
        _backend = "none"
        return None

    if backend == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        _saver = InMemorySaver()
        _backend = "memory"
        logger.info("Checkpointer 使用内存模式(进程重启丢失)")
        return _saver

    try:
        if backend == "postgres":
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            _cm = AsyncPostgresSaver.from_conn_string(
                settings.CHECKPOINTER_POSTGRES_URL
            )
            saver = await _cm.__aenter__()
            await saver.setup()
        else:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            path = Path(settings.CHECKPOINTER_DB_PATH)
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[3] / path
            path.parent.mkdir(parents=True, exist_ok=True)
            _cm = AsyncSqliteSaver.from_conn_string(str(path))
            saver = await _cm.__aenter__()
            await saver.setup()

        _saver = saver
        _backend = backend
        logger.info("Checkpointer 已初始化: {}", backend)
        return _saver
    except Exception as exc:  # noqa: BLE001 - 持久化失败不阻断主流程
        logger.warning("Checkpointer 初始化失败,降级内存: {}", exc)
        from langgraph.checkpoint.memory import InMemorySaver

        _saver = InMemorySaver()
        _backend = "memory"
        return _saver


async def close_checkpointer() -> None:
    global _saver, _cm, _backend
    if _cm is not None:
        try:
            await _cm.__aexit__(None, None, None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Checkpointer 关闭失败: {}", exc)
    _saver = None
    _cm = None
    _backend = "none"


async def delete_thread(thread_id: str) -> None:
    if _saver is None:
        return
    delete = getattr(_saver, "adelete_thread", None)
    if delete is None:
        return
    try:
        await delete(thread_id)
    except Exception as exc:  # noqa: BLE001 - 清理失败不影响业务
        logger.warning("清理 checkpoint 失败 [{}]: {}", thread_id, exc)


async def cleanup_expired_threads() -> dict[str, int]:
    """清理超过 CHECKPOINT_TTL_HOURS 的未完成 thread。"""
    from datetime import datetime, timedelta

    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.session import Session

    if _saver is None:
        return {"threads": 0, "backend": _backend}

    cutoff = datetime.now() - timedelta(hours=settings.CHECKPOINT_TTL_HOURS)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Session.session_id).where(
                    func.coalesce(
                        Session.last_message_at, Session.started_at
                    )
                    < cutoff
                )
            )
        ).scalars().all()

    cleaned = 0
    for session_uuid in rows:
        await delete_thread(session_uuid)
        cleaned += 1
    return {"threads": cleaned, "backend": _backend}

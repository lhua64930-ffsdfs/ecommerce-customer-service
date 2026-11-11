"""可选 Langfuse 观测:未配置时完全 no-op。

三条链路都只做增强,失败绝不阻断主流程:
1. LangGraph / LangChain:给图执行挂 ``CallbackHandler``,并通过 metadata
   写入 session / user / trace 名称;
2. 原生 OpenAI 调用:``LLMService`` 在启用时改用 ``langfuse.openai.AsyncOpenAI``,
   自动记录 generation(模型、token、延迟、输入输出);
3. 聊天入口:``trace_scope`` 设置 trace 级属性,让同一会话/用户的 span 可聚合。
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

from app.core.config import settings
from app.utils.logger import logger

_handler: Any = None
_warned = False


def langfuse_enabled() -> bool:
    """三项配置齐全才启用;缺任意一项按未配置处理。"""
    enabled = bool(
        settings.LANGFUSE_PUBLIC_KEY
        and settings.LANGFUSE_SECRET_KEY
        and settings.LANGFUSE_BASE_URL
    )
    if enabled:
        # LLMService 可能先于 get_callbacks() 初始化,这里提前同步 SDK 环境变量
        _prepare_env()
    return enabled


def _prepare_env() -> None:
    """Langfuse SDK 从环境变量读取密钥;配置中心的值同步一次即可。"""
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.LANGFUSE_PUBLIC_KEY)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.LANGFUSE_SECRET_KEY)
    # v5 优先 LANGFUSE_BASE_URL;LANGFUSE_HOST 是兼容旧版的别名
    os.environ.setdefault("LANGFUSE_BASE_URL", settings.LANGFUSE_BASE_URL)
    os.environ.setdefault("LANGFUSE_HOST", settings.LANGFUSE_BASE_URL)
    os.environ.setdefault(
        "LANGFUSE_TRACING_ENVIRONMENT", settings.LANGFUSE_TRACING_ENVIRONMENT
    )


def get_callbacks() -> list[Any]:
    """返回 LangChain 回调列表;未启用/不可用时返回空列表。"""
    if not langfuse_enabled():
        return []

    global _handler, _warned
    if _handler is not None:
        return [_handler]

    try:
        _prepare_env()
        from langfuse.langchain import CallbackHandler

        _handler = CallbackHandler()
        logger.info("Langfuse 观测已启用: {}", settings.LANGFUSE_BASE_URL)
        return [_handler]
    except Exception as exc:  # noqa: BLE001 - 观测是增强,不阻断主流程
        if not _warned:
            logger.warning("Langfuse 初始化失败,继续无观测运行: {}", exc)
            _warned = True
        return []


def langchain_config(
    session_id: str = "",
    user_id: int | str | None = None,
    trace_name: str = "after_sales_chat",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """构造 LangGraph/LangChain 的 config,附带 Langfuse trace 元数据。"""
    callbacks = get_callbacks()
    if not callbacks:
        return {}

    metadata: dict[str, Any] = {"langfuse_trace_name": trace_name}
    if session_id:
        metadata["langfuse_session_id"] = session_id
    if user_id is not None:
        metadata["langfuse_user_id"] = str(user_id)
    if tags:
        metadata["langfuse_tags"] = tags
    return {"callbacks": callbacks, "metadata": metadata}


def tag_current_trace(
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    name: str = "trace-annotation",
) -> None:
    """给当前 trace 追加 metadata/tags(如意图与置信度)。

    用 ``create_event`` 创建一个存活的事件 span 再写属性,避免当前 span
    已结束时 OTel 静默丢弃写入;未启用时 no-op。
    """
    if not langfuse_enabled():
        return
    try:
        _prepare_env()
        from langfuse import get_client, propagate_attributes

        with propagate_attributes(metadata=metadata, tags=tags):
            get_client().create_event(name=name)
    except Exception as exc:  # noqa: BLE001 - 观测失败不阻断业务
        logger.warning("Langfuse trace 标注失败(已忽略): {}", exc)


@contextmanager
def trace_scope(
    session_id: str = "",
    user_id: int | str | None = None,
    trace_name: str = "after_sales_chat",
    tags: list[str] | None = None,
    input_data: Any = None,
) -> Iterator[None]:
    """给一次聊天请求建根 span 并写入 trace 属性;未启用时 no-op。

    放在 ``CustomerServiceAgent.chat / stream_chat`` 入口:
    - 即使 LLM 走 mock、没有 generation,也会留下一条可观测的 trace;
    - LangGraph 回调与直接 OpenAI generation 会挂在这个根 span 下;
    - 失败只记 warning,不影响主流程。
    """
    if not langfuse_enabled():
        yield
        return

    with ExitStack() as stack:
        try:
            _prepare_env()
            from langfuse import get_client, propagate_attributes

            stack.enter_context(
                propagate_attributes(
                    session_id=session_id or None,
                    user_id=str(user_id) if user_id is not None else None,
                    trace_name=trace_name,
                    tags=tags or None,
                )
            )
            stack.enter_context(
                get_client().start_as_current_observation(
                    name=trace_name,
                    as_type="span",
                    input=input_data,
                )
            )
        except Exception as exc:  # noqa: BLE001 - 观测失败不阻断业务
            logger.warning("Langfuse trace 上下文初始化失败: {}", exc)
        yield


def shutdown_observability() -> None:
    """关闭前 flush,避免进程退出丢失最后一批 span。"""
    if not langfuse_enabled():
        return
    try:
        _prepare_env()
        from langfuse import get_client

        client = get_client()
        client.flush()
        client.shutdown()
        logger.info("Langfuse 观测已 flush 并关闭")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Langfuse 关闭时 flush 失败: {}", exc)

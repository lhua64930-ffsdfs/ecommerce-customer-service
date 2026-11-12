"""会话上下文:短窗口 + 异步摘要。

- build_window:按字符预算保留最近消息,避免上下文无限增长;
- summarize_session:会话足够长时用 LLM 生成摘要,异步执行,不阻塞回复。
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.message import Message
from app.models.session import Session
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService
from app.utils.logger import logger

SUMMARY_PROMPT = """你是电商售后客服的会话摘要模块。请把下面的对话压缩成一段摘要,保留:
- 用户的核心诉求与订单号;
- 已经确认的事实与用户偏好;
- 尚未解决的问题。

已有摘要(如有):{old_summary}

新增对话:
{history}

不要编造信息,不超过 200 字。
"""

_summary_tasks: dict[int, asyncio.Task] = {}

# 摘要/语义历史行:滑窗截断时必须始终保留,否则 coref/意图/模型都看不到早期上下文
CONTEXT_PREFIXES = ("[会话摘要]", "[较早的相关历史]")


def is_context_message(item: dict[str, Any]) -> bool:
    return str(item.get("content") or "").startswith(CONTEXT_PREFIXES)


def take_recent_with_context(
    history: list[dict[str, Any]], last_n: int
) -> list[dict[str, Any]]:
    """取最近 N 条,同时保留摘要/语义历史行(MewHelp ch07 的三处上下文注入)。"""
    recent = history[-last_n:] if last_n > 0 else []
    recent_ids = {id(item) for item in recent}
    prefix = [
        item
        for item in history
        if id(item) not in recent_ids and is_context_message(item)
    ]
    return prefix + recent


def build_window(
    messages: list[dict[str, Any]],
    max_chars: int = 6000,
    max_turns: int = 12,
    after_id: int | None = None,
) -> list[dict[str, Any]]:
    """按字符预算保留最近消息;after_id 用于排除已摘要的边界之前。"""
    if after_id:
        messages = [
            item
            for item in messages
            if int(item.get("id") or 0) > after_id
        ]
    selected: list[dict[str, Any]] = []
    total = 0
    for item in reversed(messages):
        content = str(item.get("content") or "")
        if selected and (
            total + len(content) > max_chars or len(selected) >= max_turns * 2
        ):
            break
        selected.append(item)
        total += len(content)
    return list(reversed(selected))


async def search_history(
    query: str,
    turns: list[str],
    top_k: int | None = None,
    min_score: float | None = None,
) -> list[int]:
    """语义检索历史轮次,返回相关轮次下标(按分数降序)。"""
    if not turns:
        return []
    vectors = await EmbeddingService().encode([query, *turns])
    query_vector, turn_vectors = vectors[0], vectors[1:]
    threshold = (
        settings.SEMANTIC_HISTORY_MIN_SCORE
        if min_score is None
        else min_score
    )
    scored: list[tuple[float, int]] = []
    for index, vector in enumerate(turn_vectors):
        # EmbeddingService 已做归一化,点积即余弦相似度
        score = sum(a * b for a, b in zip(query_vector, vector))
        if score >= threshold:
            scored.append((score, index))
    scored.sort(reverse=True)
    limit = settings.SEMANTIC_HISTORY_TOP_K if top_k is None else top_k
    return [index for _, index in scored[:limit]]


async def build_semantic_history(
    db: Any,
    session: Session,
    query: str,
    window_ids: set[int],
) -> str:
    """从被滑窗丢弃的历史消息中补捞语义相关轮次;失败静默跳过。"""
    if not settings.SEMANTIC_HISTORY_ENABLED:
        return ""
    try:
        rows = (
            (
                await db.execute(
                    select(Message)
                    .where(
                        Message.session_id == session.id,
                        Message.sender_type == "user",
                    )
                    .order_by(Message.id.desc())
                    .limit(settings.SEMANTIC_HISTORY_MAX_CANDIDATES)
                )
            )
            .scalars()
            .all()
        )
        candidates = [row for row in rows if row.id not in window_ids]
        if len(candidates) < 2:
            return ""
        turns = [str(row.content)[:300] for row in candidates]
        indices = await search_history(query, turns)
        if not indices:
            return ""
        text = "\n".join(f"- {turns[index]}" for index in indices)
        return text[: settings.SEMANTIC_HISTORY_MAX_CHARS]
    except Exception as exc:  # noqa: BLE001 - 语义历史是增强
        logger.warning("语义历史检索失败,跳过: {}", exc)
        return ""


def maybe_schedule_summary(session_db_id: int) -> None:
    """同一会话同时只跑一个摘要任务,避免重复 LLM 调用。"""
    task = _summary_tasks.get(session_db_id)
    if task is not None and not task.done():
        return
    task = asyncio.create_task(summarize_session(session_db_id))
    _summary_tasks[session_db_id] = task
    task.add_done_callback(lambda _: _summary_tasks.pop(session_db_id, None))


async def summarize_session(session_db_id: int) -> None:
    """只摘要边界之后的新消息;mock 模式直接跳过。"""
    llm = LLMService()
    if llm.is_mock:
        return

    try:
        async with AsyncSessionLocal() as db:
            session = await db.get(Session, session_db_id)
            if session is None:
                return

            summary_data = session.summary if isinstance(session.summary, dict) else {}
            boundary = int(
                session.summary_upto_message_id
                or summary_data.get("upto_message_id")
                or 0
            )
            rows = (
                (
                    await db.execute(
                        select(Message)
                        .where(
                            Message.session_id == session_db_id,
                            Message.id > boundary,
                        )
                        .order_by(Message.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            if len(rows) < settings.SUMMARY_TRIGGER_MESSAGES:
                return

            history = "\n".join(
                f"{'用户' if item.sender_type == 'user' else '客服'}:{item.content}"
                for item in rows
            )
            summary = await llm.generate(
                SUMMARY_PROMPT.format(
                    old_summary=summary_data.get("text", "") or "无",
                    history=history,
                ),
                temperature=0.2,
            )
            last_id = rows[-1].id
            session.summary = {
                "text": summary[:1000],
                "upto_message_id": last_id,
            }
            session.summary_upto_message_id = last_id
            await db.commit()
            logger.info("会话摘要已更新: session_db_id={}", session_db_id)
    except Exception as exc:  # noqa: BLE001 - 摘要失败不影响主流程
        logger.warning("会话摘要生成失败: {}", exc)

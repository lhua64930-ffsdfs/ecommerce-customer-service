"""低置信度问题池写入。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.low_confidence import LowConfidenceQuestion
from app.models.session import Session
from app.utils.logger import logger


async def record_low_confidence(
    db: AsyncSession | None,
    session_uuid: str,
    query: str,
    source: str,
    reason: str,
    snapshot: list[dict] | None = None,
) -> int | None:
    """记录一条低置信度问题;同一会话 + 同一问题 + 同一来源的 pending 记录不重复写。"""
    if db is None or not query.strip():
        return None

    try:
        session = (
            await db.execute(select(Session).where(Session.session_id == session_uuid))
        ).scalar_one_or_none()
        session_id = session.id if session is not None else None
        user_id = session.user_id if session is not None else None

        existing = (
            await db.execute(
                select(LowConfidenceQuestion.id)
                .where(
                    LowConfidenceQuestion.session_id == session_id,
                    LowConfidenceQuestion.query == query,
                    LowConfidenceQuestion.source == source,
                    LowConfidenceQuestion.status == "pending",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        row = LowConfidenceQuestion(
            session_id=session_id,
            user_id=user_id,
            query=query[:4000],
            source=source,
            reason=reason[:500],
            retrieved_snapshot=snapshot or [],
            status="pending",
        )
        db.add(row)
        await db.flush()
        logger.info("低置信度问题已入池: source={} id={}", source, row.id)
        return row.id
    except Exception as exc:  # noqa: BLE001 - 入池失败不阻断回答
        logger.warning("低置信度问题入池失败: {}", exc)
        return None

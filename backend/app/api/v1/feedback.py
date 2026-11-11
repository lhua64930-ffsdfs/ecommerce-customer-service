"""用户反馈入口:👎 进入低置信度池,👍 只记日志。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.access import can_access_session
from app.models.session import Session
from app.services.knowledge_pool import record_low_confidence
from app.utils.logger import logger

router = APIRouter()


class FeedbackRequest(BaseModel):
    session_id: str
    question: str = Field(..., min_length=1, max_length=4000)
    rating: str = Field(..., pattern="^(up|down)$")
    comment: str | None = Field(None, max_length=500)


@router.post("", summary="提交回答反馈")
async def submit_feedback(
    payload: FeedbackRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    session = (
        await db.execute(
            select(Session).where(Session.session_id == payload.session_id)
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if not can_access_session(request, session):
        raise HTTPException(status_code=404, detail="会话不存在")

    if payload.rating == "up":
        logger.info("用户反馈满意: session={} question={!r}", payload.session_id, payload.question[:40])
        return {"success": True, "pooled": False}

    reason = "用户反馈未解决"
    if payload.comment:
        reason = f"{reason}:{payload.comment}"
    row_id = await record_low_confidence(
        db,
        payload.session_id,
        payload.question,
        "user_feedback",
        reason,
        [],
    )
    await db.commit()
    logger.info("用户反馈未解决,已入池: session={} id={}", payload.session_id, row_id)
    return {"success": True, "pooled": row_id is not None, "id": row_id}

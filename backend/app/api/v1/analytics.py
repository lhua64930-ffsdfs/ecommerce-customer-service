"""数据分析接口。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.intent import Intent
from app.models.message import Message
from app.models.session import Session
from app.models.ticket import Ticket
from app.models.user import User

router = APIRouter()


@router.get("/summary", summary="核心指标")
async def summary(db: AsyncSession = Depends(get_db)) -> dict:
    total_sessions = await db.scalar(select(func.count()).select_from(Session))
    today_sessions = await db.scalar(
        select(func.count())
        .select_from(Session)
        .where(func.date(Session.started_at) == date.today())
    )
    total_messages = await db.scalar(select(func.count()).select_from(Message))
    total_users = await db.scalar(select(func.count()).select_from(User))
    open_tickets = await db.scalar(
        select(func.count()).select_from(Ticket).where(Ticket.status.in_(["pending", "processing"]))
    )

    bot_messages = await db.scalar(
        select(func.count()).select_from(Message).where(Message.sender_type == "bot")
    )
    transfer_messages = await db.scalar(
        select(func.count()).select_from(Message).where(Message.is_human_transfer.is_(True))
    )
    ai_resolution_rate = (
        1 - (transfer_messages or 0) / bot_messages if bot_messages else 0.0
    )

    satisfaction = await db.scalar(
        select(func.avg(Session.satisfaction_score)).where(
            Session.satisfaction_score.isnot(None)
        )
    )

    intent_rows = (
        await db.execute(
            select(Intent.intent_name, func.count(Message.id))
            .join(Message, Message.intent_id == Intent.id)
            .group_by(Intent.intent_name)
            .order_by(func.count(Message.id).desc())
        )
    ).all()

    sentiment_rows = (
        await db.execute(
            select(Message.sentiment, func.count(Message.id))
            .where(Message.sentiment.isnot(None))
            .group_by(Message.sentiment)
        )
    ).all()

    return {
        "sessions_total": int(total_sessions or 0),
        "sessions_today": int(today_sessions or 0),
        "messages_total": int(total_messages or 0),
        "users_total": int(total_users or 0),
        "open_tickets": int(open_tickets or 0),
        "ai_resolution_rate": round(max(0.0, ai_resolution_rate), 4),
        "transfer_rate": round(
            (transfer_messages or 0) / bot_messages if bot_messages else 0.0, 4
        ),
        "satisfaction_avg": round(float(satisfaction), 2) if satisfaction is not None else None,
        "intent_distribution": [
            {"name": name, "count": int(count)} for name, count in intent_rows
        ],
        "sentiment_distribution": [
            {"name": name, "count": int(count)} for name, count in sentiment_rows
        ],
    }


@router.get("/sessions", summary="会话列表")
async def sessions(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
) -> dict:
    total = await db.scalar(select(func.count()).select_from(Session))
    rows = (
        (
            await db.execute(
                select(Session)
                .order_by(Session.started_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "session_id": item.session_id,
                "user_id": item.user_id,
                "status": item.status,
                "channel": item.channel,
                "message_count": item.message_count,
                "satisfaction_score": item.satisfaction_score,
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "last_message_at": item.last_message_at.isoformat()
                if item.last_message_at
                else None,
            }
            for item in rows
        ],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }

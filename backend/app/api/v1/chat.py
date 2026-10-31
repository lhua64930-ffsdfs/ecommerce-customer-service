"""对话接口。"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.customer_agent import CustomerServiceAgent
from app.agents.graph.multi_step_agent import MultiStepAgent
from app.api.deps import get_db, get_multi_step_agent
from app.core.config import settings
from app.models.intent import Intent
from app.models.message import Message
from app.models.session import Session
from app.models.user import User
from app.schemas.chat import (
    CreateSessionRequest,
    CreateSessionResponse,
    IntentInfo,
    MessageListResponse,
    MessageResponse,
    RateRequest,
    SendMessageRequest,
    SendMessageResponse,
    SessionInfo,
    TransferRequest,
)
from app.utils.cache import incr_with_ttl
from app.utils.logger import logger

router = APIRouter()

WELCOME_MESSAGE = (
    "您好!我是智能客服小e,很高兴为您服务~\n\n"
    "我可以帮您查订单、了解商品、处理退款退货等。请问有什么可以帮到您的?"
)
DEFAULT_QUICK_REPLIES = ["查订单", "商品咨询", "退款退货", "转人工"]


async def _get_default_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.username == "demo_customer"))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            username="demo_customer",
            password_hash="!",
            user_type="customer",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


@router.post("/session", response_model=CreateSessionResponse, summary="创建会话")
async def create_session(
    payload: CreateSessionRequest, db: AsyncSession = Depends(get_db)
) -> CreateSessionResponse:
    if payload.user_id:
        user = await db.get(User, payload.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
    else:
        user = await _get_default_user(db)

    session = Session(
        session_id=uuid.uuid4().hex,
        user_id=user.id,
        status="active",
        channel=payload.channel,
        message_count=0,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    logger.info("会话已创建: {} user={}", session.session_id, user.id)
    return CreateSessionResponse(
        session=SessionInfo(
            session_id=session.session_id,
            user_id=user.id,
            status=session.status,
            started_at=session.started_at,
            message_count=session.message_count,
        ),
        welcome_message=WELCOME_MESSAGE,
        quick_replies=DEFAULT_QUICK_REPLIES,
    )


@router.post("/send", response_model=SendMessageResponse, summary="发送消息")
async def send_message(
    payload: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    multi_step_agent: MultiStepAgent | None = Depends(get_multi_step_agent),
) -> SendMessageResponse:
    # 限流:同一会话每分钟最多 N 条
    count = await incr_with_ttl(f"rate:chat:{payload.session_id}", 60)
    if count is not None and count > settings.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="请求过于频繁,请稍后再试")

    result = await db.execute(select(Session).where(Session.session_id == payload.session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在,请先创建会话")

    # 身份以会话为准,忽略请求体中可能伪造的 user_id
    user_id = session.user_id

    # 最近 10 条历史作为上下文
    history_rows = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .order_by(Message.id.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    history = [
        {
            "role": "user" if message.sender_type == "user" else "assistant",
            "content": message.content,
        }
        for message in reversed(history_rows)
    ]

    # 保存用户消息
    db.add(
        Message(
            session_id=session.id,
            sender_type="user",
            sender_id=user_id,
            content=payload.content,
            content_type=payload.content_type,
            meta=payload.metadata or None,
        )
    )

    agent = CustomerServiceAgent(
        session_id=payload.session_id,
        user_id=user_id,
        db=db,
        history=history,
        multi_step_agent=multi_step_agent,
    )
    agent_result = await agent.chat(payload.content)

    intent_data = agent_result["intent"]
    intent_row = (
        await db.execute(select(Intent).where(Intent.intent_code == intent_data["intent_code"]))
    ).scalar_one_or_none()

    bot_message = Message(
        session_id=session.id,
        sender_type="bot",
        content=agent_result["response"],
        content_type="text",
        intent_id=intent_row.id if intent_row else None,
        intent_confidence=Decimal(str(round(intent_data["confidence"], 4))),
        sentiment=agent_result["sentiment"],
        sentiment_score=Decimal(str(round(agent_result["sentiment_score"], 2))),
        is_generated=True,
        is_human_transfer=agent_result["need_transfer"],
        meta={
            "tool_calls": agent_result.get("tool_calls", []),
            "handler_type": intent_data.get("handler_type"),
            "entities": intent_data.get("entities", []),
            "agent_mode": agent_result.get("agent_mode"),
        },
    )
    db.add(bot_message)

    session.message_count = (session.message_count or 0) + 2
    session.last_message_at = datetime.now()
    if agent_result["need_transfer"]:
        session.status = "transferred"

    await db.commit()
    await db.refresh(bot_message)

    return SendMessageResponse(
        response=agent_result["response"],
        intent=IntentInfo(**intent_data),
        sentiment=agent_result["sentiment"],
        sentiment_score=agent_result["sentiment_score"],
        quick_replies=agent_result.get("quick_replies", []),
        need_transfer=agent_result["need_transfer"],
        message_id=bot_message.id,
        tool_calls=agent_result.get("tool_calls", []),
        agent_mode=agent_result.get("agent_mode", "single_step"),
    )


@router.get("/history", response_model=MessageListResponse, summary="获取历史消息")
async def get_history(
    session_id: str = Query(..., description="会话ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> MessageListResponse:
    result = await db.execute(select(Session).where(Session.session_id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    total = await db.scalar(
        select(func.count()).select_from(Message).where(Message.session_id == session.id)
    )

    rows = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .order_by(Message.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    # 一次性取出涉及的意图,避免 N+1 查询
    intent_ids = {message.intent_id for message in rows if message.intent_id}
    intents: dict[int, Intent] = {}
    if intent_ids:
        intent_rows = (
            (await db.execute(select(Intent).where(Intent.id.in_(intent_ids)))).scalars().all()
        )
        intents = {intent.id: intent for intent in intent_rows}

    messages = []
    for message in rows:
        intent_info = None
        if message.intent_id and message.intent_id in intents:
            intent = intents[message.intent_id]
            intent_info = IntentInfo(
                intent_code=intent.intent_code,
                intent_name=intent.intent_name,
                confidence=float(message.intent_confidence or 0),
                entities=[],
                handler_type=intent.handler_type,
                priority=intent.priority,
            )
        messages.append(
            MessageResponse(
                id=message.id,
                session_id=session_id,
                sender_type=message.sender_type,
                content=message.content,
                content_type=message.content_type,
                intent=intent_info,
                sentiment=message.sentiment,
                sentiment_score=float(message.sentiment_score)
                if message.sentiment_score is not None
                else None,
                created_at=message.created_at,
            )
        )

    return MessageListResponse(
        messages=messages, total=int(total or 0), page=page, page_size=page_size
    )


@router.post("/transfer", summary="转人工")
async def transfer_to_human(
    payload: TransferRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    result = await db.execute(select(Session).where(Session.session_id == payload.session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    session.status = "transferred"
    await db.commit()
    logger.info("会话转人工: {} reason={}", payload.session_id, payload.reason)
    return {
        "success": True,
        "session_id": payload.session_id,
        "status": "transferred",
        "message": "已为您转接人工客服,请稍候",
    }


@router.post("/rate", summary="评价会话")
async def rate_session(
    payload: RateRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    result = await db.execute(select(Session).where(Session.session_id == payload.session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    session.satisfaction_score = payload.score
    await db.commit()
    return {"success": True, "score": payload.score}

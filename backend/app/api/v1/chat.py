"""对话接口。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.customer_agent import CustomerServiceAgent
from app.agents.graph.checkpointer import turn_thread_id
from app.agents.graph.multi_step_agent import (
    MultiStepAgent,
    MultiStepResumeError,
)
from app.agents.tools.transfer_human import TransferHumanTool
from app.api.deps import get_db, get_multi_step_agent
from app.core.access import can_access_session, identity
from app.core.config import settings
from app.models.approval import Approval
from app.models.intent import Intent
from app.models.message import Message
from app.models.session import Session
from app.models.user import User
from app.runtime.runs import RunRecorder
from app.services.memory_service import (
    build_semantic_history,
    build_window,
    maybe_schedule_summary,
)
from app.schemas.chat import (
    AgentMode,
    CreateSessionRequest,
    CreateSessionResponse,
    IntentInfo,
    MessageListResponse,
    MessageResponse,
    RateRequest,
    ResumeRequest,
    ResumeResponse,
    SendMessageRequest,
    SendMessageResponse,
    SessionInfo,
    TransferRequest,
)
from app.utils.cache import record_rate_hit
from app.utils.logger import logger

router = APIRouter()

WELCOME_MESSAGE = (
    "您好!我是智能客服小e,很高兴为您服务~\n\n"
    "我可以帮您查订单、了解商品、处理退款退货等。请问有什么可以帮到您的?"
)
DEFAULT_QUICK_REPLIES = ["查订单", "商品咨询", "退款退货", "转人工"]


def _ensure_session_access(request: Request, session: Session) -> None:
    """鉴权开启时校验会话归属;顾客访问他人会话统一返回 404。"""
    if not can_access_session(request, session):
        raise HTTPException(status_code=404, detail="会话不存在")


async def _load_history(
    db: AsyncSession, session: Session, query: str
) -> list[dict]:
    """摘要 + 滑窗 + 可选语义历史,供 send / send-stream 共用。"""
    rows = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .order_by(Message.id.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    history = [
        {
            "id": message.id,
            "role": "user" if message.sender_type == "user" else "assistant",
            "content": message.content,
        }
        for message in reversed(rows)
    ]
    summary_data = session.summary if isinstance(session.summary, dict) else {}
    boundary = int(
        session.summary_upto_message_id
        or summary_data.get("upto_message_id")
        or 0
    )
    history = build_window(
        history, max_chars=6000, max_turns=12, after_id=boundary
    )
    insert_at = 0
    if summary_data.get("text"):
        history.insert(
            0,
            {
                "role": "assistant",
                "content": f"[会话摘要] {summary_data['text']}",
            },
        )
        insert_at = 1

    window_ids = {
        int(item["id"])
        for item in history
        if isinstance(item.get("id"), int)
    }
    semantic = await build_semantic_history(
        db, session, query, window_ids
    )
    if semantic:
        history.insert(
            insert_at,
            {
                "role": "assistant",
                "content": f"[较早的相关历史]\n{semantic}",
            },
        )
    return history


async def _check_chat_rate_limit(session_id: str) -> None:
    """按会话限流;Redis 可选,内存降级时同样限制。"""
    count = await record_rate_hit(
        f"rate:chat:sw:{session_id}",
        limit=settings.RATE_LIMIT_PER_MINUTE,
        window_seconds=60,
        burst=settings.RATE_LIMIT_BURST,
    )
    capacity = settings.RATE_LIMIT_PER_MINUTE + max(0, settings.RATE_LIMIT_BURST)
    if count is not None and count > capacity:
        raise HTTPException(
            status_code=429,
            detail="请求过于频繁,请稍后再试",
            headers={"Retry-After": "60"},
        )


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
    payload: CreateSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CreateSessionResponse:
    principal = identity(request)
    requested_user_id = payload.user_id
    if principal and principal.get("user_id") is not None:
        # 鉴权开启时以 token 主体为准,忽略请求体里可能伪造的 user_id
        requested_user_id = int(principal["user_id"])

    if requested_user_id:
        user = await db.get(User, requested_user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
    else:
        user = await _get_default_user(db)

    session = Session(
        session_id=uuid.uuid4().hex,
        tenant_id=(
            principal.get("tenant_id", "default")
            if principal
            else (user.tenant_id or "default")
        ),
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
    request: Request,
    db: AsyncSession = Depends(get_db),
    multi_step_agent: MultiStepAgent | None = Depends(get_multi_step_agent),
) -> SendMessageResponse:
    # 限流:同一会话每分钟最多 N 条(Redis 或内存滑动窗口)
    await _check_chat_rate_limit(payload.session_id)

    result = await db.execute(select(Session).where(Session.session_id == payload.session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在,请先创建会话")
    _ensure_session_access(request, session)

    # 身份以会话为准,忽略请求体中可能伪造的 user_id
    user_id = session.user_id

    history = await _load_history(db, session, payload.content)

    # 先提交用户消息:即使后续工具异常并 rollback,用户输入也不会丢失
    user_message = Message(
        session_id=session.id,
        sender_type="user",
        sender_id=user_id,
        content=payload.content,
        content_type=payload.content_type,
        meta=payload.metadata or None,
    )
    db.add(user_message)
    await db.commit()
    await db.refresh(user_message)
    thread_id = turn_thread_id(payload.session_id, user_message.id)

    agent = CustomerServiceAgent(
        session_id=payload.session_id,
        user_id=user_id,
        db=db,
        history=history,
        multi_step_agent=multi_step_agent,
        thread_id=thread_id,
    )
    agent_result = await agent.chat(payload.content)

    pending_approval = agent_result.get("pending_approval")
    recorder = RunRecorder(db)
    run = recorder.start(
        session_id=session.id,
        agent_mode=agent_result.get("agent_mode", AgentMode.SINGLE_STEP.value),
    )
    await recorder.record_steps(run, agent_result.get("run_steps", []))
    await recorder.finish(
        run, "awaiting_approval" if pending_approval else "succeeded"
    )

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
            "citations": agent_result.get("citations", []),
            "pending_approval": pending_approval,
            "evidence_status": agent_result.get("evidence_status"),
            "run_id": run.run_id,
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

    # 长会话后台摘要:不阻塞本次回复;mock 模式内部直接跳过
    if session.message_count >= 20 and (
        not isinstance(session.summary, dict)
        or int(session.summary.get("upto_message_id") or 0) < bot_message.id
    ):
        maybe_schedule_summary(session.id)

    return SendMessageResponse(
        response=agent_result["response"],
        intent=IntentInfo(**intent_data),
        sentiment=agent_result["sentiment"],
        sentiment_score=agent_result["sentiment_score"],
        quick_replies=agent_result.get("quick_replies", []),
        need_transfer=agent_result["need_transfer"],
        message_id=bot_message.id,
        tool_calls=agent_result.get("tool_calls", []),
        citations=agent_result.get("citations", []),
        pending_approval=pending_approval,
        evidence_status=agent_result.get("evidence_status"),
        run_id=run.run_id,
        agent_mode=agent_result.get("agent_mode", AgentMode.SINGLE_STEP.value),
        thread_id=agent_result.get("thread_id"),
        interrupt=agent_result.get("interrupt"),
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _persist_stream_result(
    db: AsyncSession, session: Session, result: dict
) -> tuple[str, int]:
    """把 SSE 最终结果落库:run/steps + bot message + 会话状态。"""
    pending_approval = result.get("pending_approval")
    recorder = RunRecorder(db)
    run = recorder.start(
        session_id=session.id,
        agent_mode=result.get("agent_mode", AgentMode.SINGLE_STEP.value),
    )
    await recorder.record_steps(run, result.get("run_steps", []))
    await recorder.finish(
        run, "awaiting_approval" if pending_approval else "succeeded"
    )

    intent_data = result["intent"]
    intent_row = (
        await db.execute(
            select(Intent).where(Intent.intent_code == intent_data["intent_code"])
        )
    ).scalar_one_or_none()
    bot_message = Message(
        session_id=session.id,
        sender_type="bot",
        content=result["response"],
        content_type="text",
        intent_id=intent_row.id if intent_row else None,
        intent_confidence=Decimal(str(round(intent_data.get("confidence", 0), 4))),
        sentiment=result.get("sentiment"),
        sentiment_score=Decimal(
            str(round(result.get("sentiment_score", 0), 2))
        ),
        is_generated=True,
        is_human_transfer=bool(result.get("need_transfer")),
        meta={
            "tool_calls": result.get("tool_calls", []),
            "citations": result.get("citations", []),
            "pending_approval": pending_approval,
            "evidence_status": result.get("evidence_status"),
            "run_id": run.run_id,
            "handler_type": intent_data.get("handler_type"),
            "entities": intent_data.get("entities", []),
            "agent_mode": result.get("agent_mode"),
            "thread_id": result.get("thread_id"),
            "interrupt": result.get("interrupt"),
        },
    )
    db.add(bot_message)
    session.message_count = (session.message_count or 0) + 2
    session.last_message_at = datetime.now()
    if result.get("need_transfer"):
        session.status = "transferred"

    await db.commit()
    await db.refresh(bot_message)
    if session.message_count >= 20 and (
        not isinstance(session.summary, dict)
        or int(session.summary.get("upto_message_id") or 0) < bot_message.id
    ):
        maybe_schedule_summary(session.id)
    return run.run_id, bot_message.id


@router.post("/send-stream", summary="发送消息(SSE 流式)")
async def send_message_stream(
    payload: SendMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    multi_step_agent: MultiStepAgent | None = Depends(get_multi_step_agent),
) -> StreamingResponse:
    await _check_chat_rate_limit(payload.session_id)

    result = await db.execute(
        select(Session).where(Session.session_id == payload.session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在,请先创建会话")
    _ensure_session_access(request, session)
    user_id = session.user_id

    history = await _load_history(db, session, payload.content)

    user_message = Message(
        session_id=session.id,
        sender_type="user",
        sender_id=user_id,
        content=payload.content,
        content_type=payload.content_type,
        meta=payload.metadata or None,
    )
    db.add(user_message)
    await db.commit()
    await db.refresh(user_message)
    thread_id = turn_thread_id(payload.session_id, user_message.id)

    agent = CustomerServiceAgent(
        session_id=payload.session_id,
        user_id=user_id,
        db=db,
        history=history,
        multi_step_agent=multi_step_agent,
        thread_id=thread_id,
    )

    async def event_stream():
        final_result: dict | None = None
        try:
            async for event in agent.stream_chat(payload.content):
                if event.get("event") == "done":
                    final_result = event.get("result")
                    break
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001 - 流中断也要给前端明确结束
            logger.exception("SSE 流处理失败: {}", exc)
            yield _sse({"event": "error", "message": "服务暂时不可用,请稍后重试"})

        if final_result is None:
            final_result = {
                "response": "抱歉,系统繁忙,请稍后再试,或回复「转人工」联系客服。",
                "intent": {
                    "intent_code": "fallback",
                    "intent_name": "其他",
                    "confidence": 0.0,
                    "entities": [],
                    "handler_type": "llm",
                    "priority": 0,
                },
                "sentiment": "neutral",
                "sentiment_score": 0.0,
                "quick_replies": [],
                "need_transfer": False,
                "tool_calls": [],
                "citations": [],
                "pending_approval": None,
                "evidence_status": None,
                "run_steps": [],
                "agent_mode": AgentMode.SINGLE_STEP.value,
                "thread_id": None,
                "interrupt": None,
            }

        if final_result.get("interrupt"):
            interrupt_payload = final_result["interrupt"]
            yield _sse(
                {
                    "event": "interrupt",
                    "thread_id": final_result.get("thread_id"),
                    "kind": interrupt_payload.get("type", ""),
                    "orders": interrupt_payload.get("orders", []),
                    "message": interrupt_payload.get("message", ""),
                    "preview": interrupt_payload.get("preview"),
                }
            )

        run_id, message_id = await _persist_stream_result(
            db, session, final_result
        )
        yield _sse(
            {
                "event": "done",
                "message_id": message_id,
                "run_id": run_id,
                "result": final_result,
            }
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/resume", response_model=ResumeResponse, summary="继续被暂停的对话")
async def resume_message(
    payload: ResumeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    multi_step_agent: MultiStepAgent | None = Depends(get_multi_step_agent),
) -> ResumeResponse:
    if payload.thread_id != payload.session_id:
        raise HTTPException(status_code=400, detail="thread_id 无效")

    session = (
        await db.execute(
            select(Session).where(Session.session_id == payload.session_id)
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    _ensure_session_access(request, session)

    if multi_step_agent is None:
        raise HTTPException(status_code=503, detail="多步 Agent 不可用")

    agent = CustomerServiceAgent(
        session_id=payload.session_id,
        user_id=session.user_id,
        db=db,
        multi_step_agent=multi_step_agent,
    )
    try:
        result = await agent.resume(payload.thread_id, payload.resume)
    except MultiStepResumeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    pending_approval = result.get("pending_approval")
    recorder = RunRecorder(db)
    run = recorder.start(
        session_id=session.id,
        agent_mode=AgentMode.MULTI_STEP.value,
    )
    await recorder.record_steps(run, result.get("run_steps", []))
    await recorder.finish(
        run,
        "awaiting_approval"
        if pending_approval or result.get("interrupt")
        else "succeeded",
    )

    bot_message = Message(
        session_id=session.id,
        sender_type="bot",
        content=result["response"],
        content_type="text",
        is_generated=True,
        is_human_transfer=bool(result.get("need_transfer")),
        meta={
            "tool_calls": result.get("tool_calls", []),
            "citations": result.get("citations", []),
            "pending_approval": pending_approval,
            "run_id": run.run_id,
            "thread_id": result.get("thread_id") or payload.thread_id,
            "interrupt": result.get("interrupt"),
            "agent_mode": AgentMode.MULTI_STEP.value,
        },
    )
    db.add(bot_message)
    session.message_count = (session.message_count or 0) + 1
    session.last_message_at = datetime.now()
    if result.get("need_transfer"):
        session.status = "transferred"
    await db.commit()
    await db.refresh(bot_message)

    return ResumeResponse(
        response=result["response"],
        thread_id=result.get("thread_id") or payload.thread_id,
        interrupt=result.get("interrupt"),
        pending_approval=pending_approval,
        tool_calls=result.get("tool_calls", []),
        citations=result.get("citations", []),
        run_id=run.run_id,
        message_id=bot_message.id,
        agent_mode=AgentMode.MULTI_STEP,
    )


@router.get("/history", response_model=MessageListResponse, summary="获取历史消息")
async def get_history(
    request: Request,
    session_id: str = Query(..., description="会话ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> MessageListResponse:
    result = await db.execute(select(Session).where(Session.session_id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    _ensure_session_access(request, session)

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

    # 会话回放时用审批表的最新状态覆盖消息里的快照,避免历史卡片一直显示“待确认”
    approval_ids = set()
    for message in rows:
        meta = message.meta if isinstance(message.meta, dict) else {}
        pending = meta.get("pending_approval")
        if isinstance(pending, dict) and pending.get("approval_id"):
            approval_ids.add(str(pending["approval_id"]))
    approvals: dict[str, Approval] = {}
    if approval_ids:
        approval_rows = (
            (
                await db.execute(
                    select(Approval).where(Approval.approval_no.in_(approval_ids))
                )
            )
            .scalars()
            .all()
        )
        approvals = {item.approval_no: item for item in approval_rows}

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
        meta = message.meta if isinstance(message.meta, dict) else {}
        pending = meta.get("pending_approval")
        if isinstance(pending, dict) and pending.get("approval_id"):
            approval = approvals.get(str(pending["approval_id"]))
            if approval is not None:
                pending = {**pending, "status": approval.status}
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
                citations=meta.get("citations") or [],
                pending_approval=pending,
                evidence_status=meta.get("evidence_status"),
                created_at=message.created_at,
            )
        )

    return MessageListResponse(
        messages=messages, total=int(total or 0), page=page, page_size=page_size
    )


@router.post("/transfer", summary="转人工")
async def transfer_to_human(
    payload: TransferRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Session).where(Session.session_id == payload.session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    _ensure_session_access(request, session)
    result = await TransferHumanTool().execute(
        {
            "db": db,
            "session_id": payload.session_id,
            "user_id": session.user_id,
            "user_message": "",
            "reason": payload.reason,
        }
    )
    logger.info("会话转人工: {} reason={}", payload.session_id, payload.reason)
    return {
        "success": bool(result.get("success")),
        "session_id": payload.session_id,
        "status": "transferred" if result.get("success") else session.status,
        "message": result.get("response", "已为您转接人工客服,请稍候"),
        "transfer_id": result.get("transfer_id"),
        "queue_backend": result.get("queue_backend"),
    }


@router.post("/rate", summary="评价会话")
async def rate_session(
    payload: RateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Session).where(Session.session_id == payload.session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    _ensure_session_access(request, session)
    session.satisfaction_score = payload.score
    await db.commit()
    return {"success": True, "score": payload.score}

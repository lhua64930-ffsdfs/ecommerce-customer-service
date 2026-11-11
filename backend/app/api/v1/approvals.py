"""售后审批与订单核验接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.access import can_access_session, identity, is_staff
from app.core.config import settings
from app.models.approval import Approval
from app.models.session import Session
from app.runtime.approvals import ApprovalError, ApprovalService
from app.schemas.approval import ApproveRequest, RejectRequest, VerifyOrderRequest
from app.utils.logger import logger

router = APIRouter()


def _raise_approval_error(exc: ApprovalError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


async def _load_session_for_access(
    request: Request, db: AsyncSession, session_id: str
) -> Session:
    session = (
        await db.execute(
            select(Session).where(Session.session_id == session_id)
        )
    ).scalar_one_or_none()
    if session is None or not can_access_session(request, session):
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


def _reviewer(request: Request, fallback: str | None) -> str | None:
    principal = identity(request)
    if principal and settings.AUTH_ENABLED:
        return principal.get("username") or fallback
    return fallback


@router.post("/verify-order", summary="核验订单(订单号 + 手机后四位)")
async def verify_order(
    payload: VerifyOrderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _load_session_for_access(request, db, payload.session_id)
    try:
        result = await ApprovalService(db).verify(
            payload.session_id, payload.order_no, payload.phone_last4
        )
    except ApprovalError as exc:
        _raise_approval_error(exc)
        raise  # pragma: no cover - _raise 总会抛出

    logger.info("订单核验: session={} order={} success={}", payload.session_id, payload.order_no, result.get("success"))
    return result


@router.post("/approvals/{approval_id}/approve", summary="确认/审批售后申请")
async def approve(
    approval_id: str,
    payload: ApproveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _load_session_for_access(request, db, payload.session_id)
    if settings.AUTH_ENABLED:
        approval = (
            await db.execute(
                select(Approval).where(Approval.approval_no == approval_id)
            )
        ).scalar_one_or_none()
        if approval is not None and approval.requires_human and not is_staff(request):
            raise HTTPException(
                status_code=403, detail="高风险申请需要客服/管理员审核"
            )
    reviewer = _reviewer(request, payload.reviewer)
    try:
        result = await ApprovalService(db).approve(
            approval_id, payload.session_id, reviewer
        )
    except ApprovalError as exc:
        _raise_approval_error(exc)
        raise  # pragma: no cover

    logger.info(
        "审批处理: {} reviewer={} success={}",
        approval_id,
        reviewer,
        result.get("success"),
    )
    return result


@router.post("/approvals/{approval_id}/reject", summary="拒绝售后申请")
async def reject(
    approval_id: str,
    payload: RejectRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _load_session_for_access(request, db, payload.session_id)
    reviewer = _reviewer(request, payload.reviewer)
    try:
        result = await ApprovalService(db).reject(
            approval_id, payload.session_id, payload.reason, reviewer
        )
    except ApprovalError as exc:
        _raise_approval_error(exc)
        raise  # pragma: no cover

    logger.info("审批拒绝: {} reason={}", approval_id, payload.reason)
    return result


@router.get("/approvals", summary="会话的售后审批列表")
async def list_approvals(
    request: Request,
    session_id: str = Query(..., description="会话ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _load_session_for_access(request, db, session_id)
    try:
        items = await ApprovalService(db).list_approvals(session_id)
    except ApprovalError as exc:
        _raise_approval_error(exc)
        raise  # pragma: no cover
    return {"items": items, "total": len(items)}

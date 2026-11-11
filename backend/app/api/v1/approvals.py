"""售后审批与订单核验接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.runtime.approvals import ApprovalError, ApprovalService
from app.schemas.approval import ApproveRequest, RejectRequest, VerifyOrderRequest
from app.utils.logger import logger

router = APIRouter()


def _raise_approval_error(exc: ApprovalError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post("/verify-order", summary="核验订单(订单号 + 手机后四位)")
async def verify_order(
    payload: VerifyOrderRequest, db: AsyncSession = Depends(get_db)
) -> dict:
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
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await ApprovalService(db).approve(
            approval_id, payload.session_id, payload.reviewer
        )
    except ApprovalError as exc:
        _raise_approval_error(exc)
        raise  # pragma: no cover

    logger.info(
        "审批处理: {} reviewer={} success={}",
        approval_id,
        payload.reviewer,
        result.get("success"),
    )
    return result


@router.post("/approvals/{approval_id}/reject", summary="拒绝售后申请")
async def reject(
    approval_id: str,
    payload: RejectRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await ApprovalService(db).reject(
            approval_id, payload.session_id, payload.reason, payload.reviewer
        )
    except ApprovalError as exc:
        _raise_approval_error(exc)
        raise  # pragma: no cover

    logger.info("审批拒绝: {} reason={}", approval_id, payload.reason)
    return result


@router.get("/approvals", summary="会话的售后审批列表")
async def list_approvals(
    session_id: str = Query(..., description="会话ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        items = await ApprovalService(db).list_approvals(session_id)
    except ApprovalError as exc:
        _raise_approval_error(exc)
        raise  # pragma: no cover
    return {"items": items, "total": len(items)}

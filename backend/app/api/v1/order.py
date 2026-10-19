"""订单服务接口。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.order import Order

router = APIRouter()


def _to_dict(order: Order) -> dict:
    return {
        "id": order.id,
        "order_no": order.order_no,
        "user_id": order.user_id,
        "product_name": order.remark,
        "status": order.status,
        "total_amount": float(order.total_amount),
        "pay_amount": float(order.pay_amount) if order.pay_amount is not None else None,
        "shipping_address": order.shipping_address,
        "receiver_name": order.receiver_name,
        "receiver_phone": order.receiver_phone,
        "tracking_no": order.tracking_no,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "shipped_at": order.shipped_at.isoformat() if order.shipped_at else None,
    }


@router.get("/list", summary="订单列表")
async def list_orders(
    user_id: int | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    statement = select(Order)
    count_statement = select(func.count()).select_from(Order)
    if user_id is not None:
        statement = statement.where(Order.user_id == user_id)
        count_statement = count_statement.where(Order.user_id == user_id)
    if status:
        statement = statement.where(Order.status == status)
        count_statement = count_statement.where(Order.status == status)

    total = await db.scalar(count_statement)
    rows = (
        (
            await db.execute(
                statement.order_by(Order.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [_to_dict(order) for order in rows],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


@router.get("/{order_no}", summary="订单详情")
async def get_order(order_no: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Order).where(Order.order_no == order_no.upper()))
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return _to_dict(order)

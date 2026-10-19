"""订单查询工具:查询真实数据库,并校验订单归属。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.utils.logger import logger

STATUS_MAP = {
    "pending": ("⏳", "待支付"),
    "paid": ("💳", "已支付,待发货"),
    "shipped": ("🚚", "已发货"),
    "delivered": ("✅", "已收货"),
    "completed": ("🎉", "已完成"),
    "cancelled": ("❌", "已取消"),
    "refunded": ("💰", "已退款"),
}


class QueryOrderTool:
    """按订单号或用户查询订单。"""

    def __init__(self) -> None:
        self.name = "query_order"
        self.description = "查询用户订单信息,包括订单状态、物流信息、收货地址等"
        self.requires_auth = True

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        db: AsyncSession | None = params.get("db")
        user_id: int | None = params.get("user_id")
        message: str = params.get("user_message", "")
        order_no: str | None = params.get("order_no")

        if db is None:
            return {"success": False, "response": "查询服务暂时不可用,请稍后重试"}

        try:
            order_no = order_no or self._extract_order_no(message)

            if order_no:
                order = await self._get_order(db, order_no)
                if order is None:
                    return {
                        "success": False,
                        "response": f"未找到订单号 {order_no},请确认订单号是否正确",
                        "error_code": "ORDER_NOT_FOUND",
                    }
                # 归属校验:防止通过订单号窥探他人订单
                if user_id is None or order.user_id != user_id:
                    logger.warning("越权查询尝试: user={} order={}", user_id, order_no)
                    return {
                        "success": False,
                        "response": "未找到该订单,请确认订单号是否属于当前账号",
                        "error_code": "ORDER_FORBIDDEN",
                    }
                return {
                    "success": True,
                    "response": self._format_order_detail(order),
                    "order": self._order_to_dict(order),
                }

            if user_id is None:
                return {
                    "success": True,
                    "response": "请提供您的订单号(格式如 ORDER20260315001),或登录后查看全部订单。",
                    "orders": [],
                }

            orders = await self._query_user_orders(db, user_id)
            return {
                "success": True,
                "response": self._format_order_list(orders),
                "orders": [self._order_to_dict(item) for item in orders],
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("订单查询失败: {}", exc)
            return {"success": False, "response": "查询服务暂时不可用,请稍后重试", "error_code": "QUERY_FAILED"}

    # ---------------- 内部实现 ----------------
    @staticmethod
    def _extract_order_no(text: str) -> str | None:
        # 只接受 ORDER/DD 前缀,避免把普通长英文词误判为订单号
        match = re.search(r"\b(?:ORDER|DD)[A-Za-z0-9]{8,20}\b", text, re.IGNORECASE)
        return match.group(0).upper() if match else None

    @staticmethod
    async def _get_order(db: AsyncSession, order_no: str) -> Order | None:
        result = await db.execute(select(Order).where(Order.order_no == order_no.upper()))
        return result.scalar_one_or_none()

    @staticmethod
    async def _query_user_orders(db: AsyncSession, user_id: int) -> list[Order]:
        result = await db.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(5)
        )
        return list(result.scalars().all())

    @staticmethod
    def _format_order_detail(order: Order) -> str:
        emoji, status_text = STATUS_MAP.get(order.status, ("📦", order.status))
        product = order.remark or "—"
        lines = [
            "📦 订单详情\n",
            "━━━━━━━━━━━━━━━━━━━━\n",
            f"订单号:{order.order_no}\n",
            f"商品:{product}\n",
            f"实付金额:¥{float(order.pay_amount or order.total_amount):.2f}\n",
            f"订单状态:{emoji} {status_text}\n",
        ]
        if order.tracking_no:
            lines.append(f"运单号:{order.tracking_no}\n")
        lines.extend(
            [
                "━━━━━━━━━━━━━━━━━━━━\n",
                "📍 收货信息\n",
                f"{order.receiver_name or ''} {order.receiver_phone or ''}\n",
                f"{QueryOrderTool._format_address(order.shipping_address)}\n",
                f"下单时间:{order.created_at:%Y-%m-%d %H:%M}\n",
            ]
        )
        return "".join(lines)

    @staticmethod
    def _format_address(address: Any) -> str:
        if isinstance(address, dict):
            province = str(address.get("province", ""))
            city = str(address.get("city", ""))
            detail = str(address.get("detail", ""))
            # 直辖市省市同名时只保留一个
            return f"{province}{'' if city == province else city}{detail}"
        return str(address or "")

    @staticmethod
    def _format_order_list(orders: list[Order]) -> str:
        if not orders:
            return "您还没有订单记录"
        lines = ["📋 您的订单列表\n\n"]
        for index, order in enumerate(orders, 1):
            emoji, status_text = STATUS_MAP.get(order.status, ("📦", order.status))
            lines.append(
                f"{index}. {emoji} {order.order_no}\n"
                f"   商品:{order.remark or '—'}\n"
                f"   金额:¥{float(order.total_amount):.2f}\n"
                f"   状态:{status_text}\n\n"
            )
        lines.append('回复"查订单 [订单号]"可查看详情')
        return "".join(lines)

    @staticmethod
    def _order_to_dict(order: Order) -> dict[str, Any]:
        return {
            "order_no": order.order_no,
            "product_name": order.remark,
            "total_amount": float(order.total_amount),
            "pay_amount": float(order.pay_amount) if order.pay_amount is not None else None,
            "status": order.status,
            "tracking_no": order.tracking_no,
            "receiver_name": order.receiver_name,
            "receiver_phone": order.receiver_phone,
            "shipping_address": order.shipping_address,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        }

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "order_no": {
                        "type": "string",
                        "description": "订单号(可选,不提供则返回用户所有订单)",
                    }
                },
                "required": [],
            },
        }

"""退款退货工具:取消订单真正写库,退款/退货给出流程指引。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.utils.logger import logger

REFUND_POLICY = (
    "📋 退款政策说明:\n\n"
    "【退款时效】\n"
    "• 取消订单:1-3 个工作日原路退回\n"
    "• 退货退款:收到商品后 1-3 个工作日\n"
    "• 退款至原支付账户(不支持现金)\n\n"
    "【退货条件】\n"
    "• 7 天无理由退货(商品不影响二次销售)\n"
    "• 质量问题由平台承担运费\n"
    "• 请保持商品、配件、包装完好\n\n"
    "如需申请,请提供订单号。"
)


class RefundTool:
    """处理取消订单、退款申请、退货流程。"""

    def __init__(self) -> None:
        self.name = "refund"
        self.description = "处理退款退货申请、取消订单、查询退款进度"
        self.requires_auth = True

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        db: AsyncSession | None = params.get("db")
        user_id: int | None = params.get("user_id")
        message: str = params.get("user_message", "")
        order_no: str | None = params.get("order_no")
        action: str | None = params.get("action")

        if db is None:
            return {"success": False, "response": "服务处理失败,请稍后重试或联系人工客服"}

        try:
            action = action or self._detect_action(message)
            order_no = order_no or self._extract_order_no(message)

            if action == "cancel":
                return await self._handle_cancel(db, user_id, order_no)
            if action in ("return", "refund"):
                return await self._handle_return_or_refund(db, user_id, order_no, action)
            return {"success": True, "response": REFUND_POLICY, "action": "consult"}
        except Exception as exc:  # noqa: BLE001
            logger.error("退款处理失败: {}", exc)
            await db.rollback()
            return {"success": False, "response": "服务处理失败,请稍后重试或联系人工客服"}

    # ---------------- 各动作 ----------------
    @staticmethod
    async def _handle_cancel(
        db: AsyncSession, user_id: int | None, order_no: str | None
    ) -> dict[str, Any]:
        if not order_no:
            return {
                "success": True,
                "action": "cancel",
                "response": (
                    "请提供您要取消的订单号,格式如:\n"
                    "• 取消订单 ORDER20260315001\n\n"
                    "或者回复「查订单」查看最近订单。"
                ),
            }

        order = await RefundTool._get_order(db, order_no)
        if order is None or user_id is None or order.user_id != user_id:
            return {
                "success": False,
                "action": "cancel",
                "response": "未找到该订单,或该订单不属于当前账号。",
            }

        if order.status not in ("pending", "paid"):
            return {
                "success": False,
                "action": "cancel",
                "response": (
                    f"订单 {order.order_no} 当前状态为「{order.status}」,已无法直接取消。\n"
                    "如已发货,建议收到商品后申请退货退款。"
                ),
            }

        order.status = "cancelled"
        await db.commit()
        logger.info("订单已取消: {}", order.order_no)

        return {
            "success": True,
            "action": "cancel_order",
            "order_no": order.order_no,
            "response": (
                f"✅ 已为您取消订单 {order.order_no}\n\n"
                "支付金额将在 1-3 个工作日内原路退回。\n"
                "如有疑问,请联系人工客服。"
            ),
        }

    @staticmethod
    async def _handle_return_or_refund(
        db: AsyncSession, user_id: int | None, order_no: str | None, action: str
    ) -> dict[str, Any]:
        if not order_no:
            return {"success": True, "action": action, "response": REFUND_POLICY}

        order = await RefundTool._get_order(db, order_no)
        if order is None or user_id is None or order.user_id != user_id:
            return {
                "success": False,
                "action": action,
                "response": "未找到该订单,或该订单不属于当前账号。",
            }

        if action == "return":
            response = (
                f"📦 退货申请指引(订单 {order.order_no})\n\n"
                "退货流程:\n"
                "1. 请在 7 天内将商品寄回(保持完好)\n"
                "2. 我们在收到商品后 1-3 个工作日退款\n"
                "3. 质量问题由平台承担运费\n\n"
                "需要我为您创建退货工单吗?"
            )
        else:
            response = (
                f"💰 订单 {order.order_no} 退款说明\n\n"
                f"订单状态:{order.status}\n"
                "退款将原路退回,通常 1-3 个工作日到账。\n"
                "如商品已签收,请先申请退货。"
            )

        return {"success": True, "action": action, "order_no": order.order_no, "response": response}

    # ---------------- 工具方法 ----------------
    @staticmethod
    def _detect_action(message: str) -> str:
        if any(word in message for word in ("取消", "撤单", "不要了")):
            return "cancel"
        if any(word in message for word in ("退货", "退回")):
            return "return"
        if any(word in message for word in ("退款", "退钱", "返款")):
            return "refund"
        return "consult"

    @staticmethod
    def _extract_order_no(text: str) -> str | None:
        match = re.search(r"\b(?:ORDER|DD)[A-Za-z0-9]{8,20}\b", text, re.IGNORECASE)
        return match.group(0).upper() if match else None

    @staticmethod
    async def _get_order(db: AsyncSession, order_no: str) -> Order | None:
        result = await db.execute(select(Order).where(Order.order_no == order_no.upper()))
        return result.scalar_one_or_none()

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["cancel", "return", "refund", "query"],
                        "description": "操作类型",
                    },
                    "order_no": {"type": "string", "description": "订单号"},
                    "reason": {"type": "string", "description": "原因"},
                },
                "required": ["action"],
            },
        }

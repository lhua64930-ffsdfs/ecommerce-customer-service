"""售后申请工具:模型只能提出申请,不能直接修改订单。

真正执行由审批接口在用户确认/人工审核后调用 ``ApprovalService.approve`` 完成。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.runtime.approvals import ApprovalError, ApprovalService
from app.utils.logger import logger


class ProposeActionTool:
    """提交取消/退款/退货申请,生成待确认或待审批的售后单。"""

    def __init__(self) -> None:
        self.name = "propose_after_sales_action"
        self.description = (
            "提交售后申请(取消订单/退款/退货),生成待用户确认或待人工审核的申请单。"
            "该工具不会直接修改订单;用户确认后由系统执行。"
        )
        self.requires_auth = True

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        db: AsyncSession | None = params.get("db")
        session_id: str = params.get("session_id", "")
        user_id: int | None = params.get("user_id")
        action: str = str(params.get("action") or "").strip()
        order_no: str | None = params.get("order_no")
        reason: str | None = params.get("reason")

        if db is None or user_id is None:
            return {
                "success": False,
                "response": "售后申请服务暂时不可用,请稍后重试",
                "error_code": "SERVICE_UNAVAILABLE",
            }

        service = ApprovalService(db)
        try:
            result = await service.propose(
                session_uuid=session_id,
                user_id=user_id,
                action=action,
                order_no=order_no,
                reason=reason,
            )
        except ApprovalError as exc:
            logger.warning("售后申请失败: {} {}", exc.code, exc.message)
            return {
                "success": False,
                "response": exc.message,
                "error_code": exc.code,
            }

        return {
            "success": True,
            "response": result.get("response", "售后申请已处理"),
            "proposal": result.get("pending"),
            "decision": result.get("decision"),
            "task_id": result.get("task_id"),
            "approval_no": result.get("approval_no"),
            "executed": bool(result.get("executed")),
            "result": result.get("result"),
        }

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["cancel", "refund", "return"],
                        "description": "售后动作:取消订单 / 退款 / 退货",
                    },
                    "order_no": {
                        "type": "string",
                        "description": "订单号,例如 ORDER20260401001",
                    },
                    "reason": {"type": "string", "description": "申请原因(可选)"},
                },
                "required": ["action"],
            },
        }

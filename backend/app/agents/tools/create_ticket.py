"""创建工单工具:写入 tickets 表。"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket import Ticket
from app.utils.logger import logger

TYPE_NAMES = {
    "complaint": "投诉建议",
    "refund": "退款申请",
    "consult": "业务咨询",
    "suggestion": "意见反馈",
    "other": "其他",
}


class CreateTicketTool:
    """创建客服工单,记录用户问题和反馈。"""

    def __init__(self) -> None:
        self.name = "create_ticket"
        self.description = "创建客服工单,记录用户问题和反馈"
        self.requires_auth = True

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        db: AsyncSession | None = params.get("db")
        user_id: int | None = params.get("user_id")
        session_id: str | None = params.get("session_id")
        ticket_type: str = params.get("type", "consult")
        title: str = params.get("title", "用户咨询")
        content: str = params.get("content") or params.get("user_message", "")

        if db is None or user_id is None:
            return {"success": False, "response": "工单创建失败,请先登录后再试"}

        try:
            ticket_no = f"TKT{int(time.time())}"
            ticket = Ticket(
                ticket_no=ticket_no,
                session_id=None,
                user_id=user_id,
                type=ticket_type if ticket_type in TYPE_NAMES else "other",
                title=title[:200],
                content=content or title,
                status="pending",
                priority="normal",
            )
            db.add(ticket)
            await db.commit()
            logger.info("工单已创建: {} ({})", ticket_no, session_id)

            return {
                "success": True,
                "ticket_no": ticket_no,
                "response": (
                    "✅ 工单已创建\n\n"
                    f"工单编号:{ticket_no}\n"
                    f"问题类型:{TYPE_NAMES.get(ticket_type, '其他')}\n"
                    "我们的工作人员将在 24 小时内处理,处理结果会通过站内消息通知您。"
                ),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("创建工单失败: {}", exc)
            await db.rollback()
            return {"success": False, "response": "工单创建失败,请稍后重试"}

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["complaint", "refund", "consult", "suggestion"],
                        "description": "工单类型",
                    },
                    "title": {"type": "string", "description": "工单标题"},
                    "content": {"type": "string", "description": "工单内容"},
                },
                "required": ["type", "content"],
            },
        }

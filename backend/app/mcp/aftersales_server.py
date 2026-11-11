"""订单 / 售后 / 转人工 / 工单 MCP Server。"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

import app.models  # noqa: F401 - 注册全部 ORM 模型
from app.agents.tools.create_ticket import CreateTicketTool
from app.agents.tools.propose_action import ProposeActionTool
from app.agents.tools.query_order import QueryOrderTool
from app.agents.tools.transfer_human import TransferHumanTool
from app.core.config import settings
from app.mcp.common import (
    add_health_route,
    create_server,
    run_server,
    run_with_db,
)
from app.utils.logger import logger

UserId = Annotated[int | None, Field(description="内部上下文:用户 ID")]
SessionId = Annotated[str, Field(description="内部上下文:会话 ID")]
UserMessage = Annotated[str, Field(description="内部上下文:原始用户消息")]

mcp = create_server(
    "after-sales-aftersales",
    "售后智答订单/售后工具服务;调用方注入 user_id / session_id。",
)


@mcp.tool(name="query_order")
async def query_order(
    order_no: Annotated[
        str | None, Field(description="订单号;不传返回用户最近订单")
    ] = None,
    user_id: UserId = None,
    session_id: SessionId = "",
    user_message: UserMessage = "",
) -> dict[str, Any]:
    """查询订单状态、物流与脱敏后的收货信息,并校验归属。"""
    logger.info("MCP aftersales.order user={} session={}", user_id, session_id)
    return await run_with_db(
        QueryOrderTool(),
        {
            "order_no": order_no,
            "user_id": user_id,
            "session_id": session_id,
            "user_message": user_message,
        },
    )


@mcp.tool(name="propose_after_sales_action")
async def propose_after_sales_action(
    action: Annotated[
        Literal["cancel", "refund", "return"],
        Field(description="售后动作:取消 / 退款 / 退货"),
    ],
    order_no: Annotated[
        str | None, Field(description="订单号,例如 ORDER20260401001")
    ] = None,
    reason: Annotated[str | None, Field(description="申请原因(可选)")] = None,
    user_id: UserId = None,
    session_id: SessionId = "",
    user_message: UserMessage = "",
) -> dict[str, Any]:
    """提交售后申请,生成待确认/待审核申请单,不直接修改订单。"""
    logger.info(
        "MCP aftersales.propose user={} session={} action={}",
        user_id,
        session_id,
        action,
    )
    return await run_with_db(
        ProposeActionTool(),
        {
            "action": action,
            "order_no": order_no,
            "reason": reason,
            "user_id": user_id,
            "session_id": session_id,
            "user_message": user_message,
        },
    )


@mcp.tool(name="transfer_human")
async def transfer_human(
    reason: Annotated[
        str | None, Field(description="转接原因;不传按用户消息判断")
    ] = None,
    user_id: UserId = None,
    session_id: SessionId = "",
    user_message: UserMessage = "",
) -> dict[str, Any]:
    """转接人工客服,更新会话状态并尽力写 Redis 排队提示。"""
    logger.info("MCP aftersales.transfer user={} session={}", user_id, session_id)
    return await run_with_db(
        TransferHumanTool(),
        {
            "reason": reason,
            "user_id": user_id,
            "session_id": session_id,
            "user_message": user_message,
        },
    )


@mcp.tool(name="create_ticket")
async def create_ticket(
    type: Annotated[
        Literal["complaint", "refund", "consult", "suggestion"],
        Field(description="工单类型"),
    ],
    content: Annotated[str, Field(description="工单内容")],
    title: Annotated[str, Field(description="工单标题")] = "用户咨询",
    user_id: UserId = None,
    session_id: SessionId = "",
    user_message: UserMessage = "",
) -> dict[str, Any]:
    """创建客服工单。写操作仅允许可信内部调用方使用。"""
    logger.info("MCP aftersales.ticket user={} session={}", user_id, session_id)
    return await run_with_db(
        CreateTicketTool(),
        {
            "type": type,
            "title": title,
            "content": content,
            "user_id": user_id,
            "session_id": session_id,
            "user_message": user_message,
        },
    )


health = add_health_route(mcp, "after-sales-aftersales")


def main() -> None:
    logger.info("Aftersales MCP Server 启动: {}", settings.MCP_AFTERSALES_PORT)
    run_server(mcp, settings.MCP_AFTERSALES_PORT)


if __name__ == "__main__":
    main()

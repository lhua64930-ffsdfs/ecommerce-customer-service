"""默认工具集工厂:单步 Agent 与多步图共用同一批工具实现。"""
from __future__ import annotations

from typing import Any

from app.agents.tools.create_ticket import CreateTicketTool
from app.agents.tools.query_order import QueryOrderTool
from app.agents.tools.query_product import QueryProductTool
from app.agents.tools.refund_tool import RefundTool
from app.agents.tools.search_knowledge import SearchKnowledgeTool
from app.agents.tools.transfer_human import TransferHumanTool


def build_default_tools() -> dict[str, Any]:
    """创建一次请求使用的工具字典(工具本身无状态,仅持有名称与描述)。"""
    return {
        "search_knowledge": SearchKnowledgeTool(),
        "query_order": QueryOrderTool(),
        "query_product": QueryProductTool(),
        "refund": RefundTool(),
        "transfer_human": TransferHumanTool(),
        "create_ticket": CreateTicketTool(),
    }

"""默认工具集工厂:单步 Agent 与多步图共用同一批工具实现。

多步图只暴露只读工具 + 售后申请工具;真实写操作由审批接口执行,
模型无法直接调用退款/取消的写逻辑。
"""
from __future__ import annotations

from typing import Any

from app.agents.tools.create_ticket import CreateTicketTool
from app.agents.tools.propose_action import ProposeActionTool
from app.agents.tools.query_order import QueryOrderTool
from app.agents.tools.query_product import QueryProductTool
from app.agents.tools.search_knowledge import SearchKnowledgeTool
from app.agents.tools.transfer_human import TransferHumanTool
from app.core.config import settings


def _maybe_wrap_with_mcp(
    tools: dict[str, Any], use_mcp: bool | None
) -> dict[str, Any]:
    """MCP 开启时把工具包装成远程代理;默认按全局配置判断。"""
    enabled = settings.MCP_ENABLED if use_mcp is None else use_mcp
    if not enabled:
        return tools
    from app.agents.mcp.client import build_mcp_proxies

    return build_mcp_proxies(tools)


def build_default_tools(use_mcp: bool | None = None) -> dict[str, Any]:
    """创建一次请求使用的完整工具字典。"""
    tools = {
        "search_knowledge": SearchKnowledgeTool(),
        "query_order": QueryOrderTool(),
        "query_product": QueryProductTool(),
        "propose_after_sales_action": ProposeActionTool(),
        "transfer_human": TransferHumanTool(),
        "create_ticket": CreateTicketTool(),
    }
    return _maybe_wrap_with_mcp(tools, use_mcp)


def build_graph_tools(use_mcp: bool | None = None) -> dict[str, Any]:
    """多步图专用:只读工具 + 售后申请 + 转人工,不包含任何写库工具。"""
    tools = {
        "search_knowledge": SearchKnowledgeTool(),
        "query_order": QueryOrderTool(),
        "query_product": QueryProductTool(),
        "propose_after_sales_action": ProposeActionTool(),
        "transfer_human": TransferHumanTool(),
    }
    return _maybe_wrap_with_mcp(tools, use_mcp)

"""工具注册表:统一描述工具权限、Schema、超时与重试策略。

写操作权限由我们侧定义,不信任模型或外部工具声明:
- read:只读查询,失败可重试;
- proposal:发起售后申请(不直接写订单),允许模型调用;
- write:真实写库,只能由审批服务执行,多步图内一律拒绝。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

WRITE_TOOLS = {"create_ticket"}
PROPOSAL_TOOLS = {"propose_after_sales_action"}
# 有副作用的工具:超时/网络错误自动重试可能造成重复工单/审批/排队
NO_RETRY_TOOLS = WRITE_TOOLS | PROPOSAL_TOOLS | {"transfer_human"}

DEFAULT_TOOL_TIMEOUT = 20.0
DEFAULT_READ_RETRIES = 1


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    json_schema: dict[str, Any]
    permission: str
    timeout: float = DEFAULT_TOOL_TIMEOUT
    max_retries: int = DEFAULT_READ_RETRIES


def permission_for(name: str) -> str:
    if name in WRITE_TOOLS:
        return "write"
    if name in PROPOSAL_TOOLS:
        return "proposal"
    return "read"


def spec_from_tool(tool: Any) -> ToolSpec:
    schema = tool.get_schema()
    name = schema.get("name") or getattr(tool, "name", "unknown")
    permission = permission_for(name)
    return ToolSpec(
        name=name,
        description=schema.get("description") or getattr(tool, "description", ""),
        json_schema=schema.get("parameters") or {"type": "object", "properties": {}},
        permission=permission,
        # MCP 代理自带超时(含首次模型加载),本地工具用默认值
        timeout=getattr(tool, "timeout", DEFAULT_TOOL_TIMEOUT),
        max_retries=0 if name in NO_RETRY_TOOLS else DEFAULT_READ_RETRIES,
    )

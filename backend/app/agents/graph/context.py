"""图执行上下文:把一次请求的数据库会话与身份注入工具适配层。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ToolContext:
    """一次多步 Agent 请求内共享的上下文。"""

    db: AsyncSession | None
    user_id: int | None
    session_id: str
    user_message: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def tool_params(self, **kwargs: Any) -> dict[str, Any]:
        """合并请求上下文与模型给出的工具参数。"""
        return {
            "db": self.db,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "user_message": self.user_message,
            **kwargs,
        }

    def record_tool_call(self, tool_name: str, result: dict[str, Any]) -> None:
        """按对外契约记录工具调用(只暴露工具名与成功标志)。"""
        self.tool_calls.append(
            {"tool": tool_name, "success": bool(result.get("success"))}
        )

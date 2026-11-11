"""图执行上下文:把一次请求的数据库会话与身份注入工具适配层。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.citations import build_citations


@dataclass
class ToolContext:
    """一次多步 Agent 请求内共享的上下文。"""

    db: AsyncSession | None
    user_id: int | None
    session_id: str
    user_message: str
    # 只有确认闸在 resume 后才置 True;写工具执行前检查
    write_confirmed: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_records: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    pending_approval: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)

    def tool_params(self, **kwargs: Any) -> dict[str, Any]:
        """合并请求上下文与模型给出的工具参数。"""
        return {
            "db": self.db,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "user_message": self.user_message,
            **kwargs,
        }

    def record_tool_call(
        self,
        tool_name: str,
        result: dict[str, Any],
        args: dict[str, Any] | None = None,
        latency_ms: int = 0,
    ) -> None:
        """记录工具调用、执行步骤、引用与待审批申请。"""
        success = bool(result.get("success"))
        call_record: dict[str, Any] = {"tool": tool_name, "success": success}
        if result.get("transport"):
            call_record["transport"] = result["transport"]
        self.tool_calls.append(call_record)

        output: dict[str, Any] = {"success": success}
        for key in ("decision", "error_code", "executed", "transport"):
            if result.get(key) is not None:
                output[key] = result[key]
        response_text = str(result.get("response") or "")
        if response_text:
            output["response"] = response_text[:300]
        self.steps.append(
            {
                "step_type": "tool",
                "name": tool_name,
                "input": args or {},
                "output": output,
                "success": success,
                "latency_ms": max(0, int(latency_ms)),
            }
        )

        record: dict[str, Any] = {"tool": tool_name, "success": success}
        for key in ("decision", "error_code", "executed", "transport"):
            if result.get(key) is not None:
                record[key] = result[key]
        if result.get("proposal"):
            record["proposal"] = result["proposal"]
        self.tool_records.append(record)

        if tool_name == "propose_after_sales_action" and result.get("proposal"):
            self.pending_approval = result["proposal"]

        if tool_name != "search_knowledge" or not success:
            return

        known_ids = {item["id"] for item in self.citations}
        new_citations: list[dict[str, Any]] = []
        for citation in build_citations(result.get("results") or []):
            if citation["id"] not in known_ids:
                self.citations.append(citation)
                known_ids.add(citation["id"])
                new_citations.append(citation)
        if new_citations:
            record["citations"] = new_citations

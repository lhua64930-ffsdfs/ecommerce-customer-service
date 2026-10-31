"""测试用脚本化 ChatModel:按顺序返回预设消息,绝不访问真实模型。"""
from __future__ import annotations

from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class ScriptedChatModel(BaseChatModel):
    """按调用顺序返回预设 AIMessage;可配置为直接抛错。

    - responses:第 N 次调用返回 responses[N](超出后复用最后一条)
    - fail_with:设置后每次调用都抛出 RuntimeError(用于验证 fallback)
    - calls:记录每次调用收到的完整消息列表,便于断言工具结果
    """

    responses: list[AIMessage] = Field(default_factory=list)
    fail_with: str | None = None
    calls: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        if not self.responses:
            raise AssertionError("ScriptedChatModel 没有配置 responses")
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        # 每次返回独立副本并分配唯一 id:复用同一 AIMessage 会被
        # LangGraph 的 add_messages 当作同一条消息去重,误导条件边。
        message = self.responses[index].model_copy(
            update={"id": f"scripted-{len(self.calls)}"}
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class FakeOrderTool:
    """query_order 的测试替身:不访问数据库,记录收到的参数。"""

    name = "query_order"
    description = "查询订单信息"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(params)
        order_no = params.get("order_no") or "ORDER20260401001"
        return {
            "success": True,
            "response": f"订单 {order_no} 状态:已支付,待发货",
            "order": {"order_no": order_no, "status": "paid"},
        }

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "order_no": {"type": "string", "description": "订单号(可选)"}
                },
                "required": [],
            },
        }

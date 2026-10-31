"""LangGraph 多步 Agent:模型节点 + 工具节点 + 条件边,最多 5 步。

设计要点:
- 图与 ChatModel 从外部注入,测试可传脚本化 Fake ChatModel;
- 工具复用 ``app.agents.tools`` 下的现有实现,适配层只做参数合并与结果序列化;
- 失败、超过步数、空回复或没有产生工具结果时抛出 ``MultiStepError``,
  由 ``CustomerServiceAgent`` 回退到单步路由。
"""
from __future__ import annotations

import json
import operator
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph.context import ToolContext
from app.agents.graph.tool_adapters import build_lc_tools
from app.agents.prompts.system_prompt import get_multi_step_system_prompt
from app.utils.logger import logger

AGENT_MODE_MULTI_STEP = "multi_step"
AGENT_MODE_SINGLE_STEP = "single_step"
AGENT_MODE_SINGLE_STEP_FALLBACK = "single_step_fallback"

DEFAULT_MAX_STEPS = 5


class MultiStepError(RuntimeError):
    """多步 Agent 无法产出可用结果的基类异常。"""


class MultiStepExecutionError(MultiStepError):
    """图执行过程中发生未预期异常。"""


class MultiStepLimitError(MultiStepError):
    """超过最大步数。"""


class MultiStepEmptyResultError(MultiStepError):
    """模型返回空内容,或整次执行没有产生工具结果。"""


class AgentState(TypedDict):
    """图状态。"""

    messages: Annotated[list[BaseMessage], add_messages]
    steps: Annotated[int, operator.add]


@dataclass(frozen=True)
class MultiStepResult:
    """多步 Agent 的最终结果。"""

    response: str
    tool_calls: list[dict[str, Any]]
    steps: int


class MultiStepAgent:
    """把一次用户请求交给 LangGraph 完成多步工具调用。"""

    def __init__(
        self,
        chat_model: BaseChatModel,
        tools: dict[str, Any],
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps 至少为 1")
        self.chat_model = chat_model
        self.tools = tools
        self.max_steps = max_steps

    async def run(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        db: AsyncSession | None = None,
        user_id: int | None = None,
        session_id: str = "",
    ) -> MultiStepResult:
        """执行图并返回最终回复与工具调用链。"""
        context = ToolContext(
            db=db,
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
        )
        graph = self._build_graph(context)

        try:
            final_state = await graph.ainvoke(
                {
                    "messages": self._initial_messages(user_message, history or []),
                    "steps": 0,
                },
                config={"recursion_limit": max(25, self.max_steps * 3)},
            )
        except MultiStepError:
            raise
        except Exception as exc:  # 转成统一的多步失败异常
            logger.warning("多步 Agent 图执行失败: {}", exc)
            raise MultiStepExecutionError(f"多步 Agent 执行失败: {exc}") from exc

        final_message = final_state["messages"][-1]
        if not isinstance(final_message, AIMessage):
            raise MultiStepEmptyResultError("多步 Agent 未产出最终回复")
        response = _message_text(final_message)
        if not response:
            raise MultiStepEmptyResultError("多步 Agent 返回了空回复")
        if not context.tool_calls:
            raise MultiStepEmptyResultError("多步 Agent 没有产生可用的工具结果")

        return MultiStepResult(
            response=response,
            tool_calls=list(context.tool_calls),
            steps=int(final_state.get("steps", 0)),
        )

    # ---------------- 图构建 ----------------
    def _build_graph(self, context: ToolContext) -> Any:
        lc_tools = build_lc_tools(self.tools, context)
        tools_by_name = {tool.name: tool for tool in lc_tools}
        model_with_tools = self.chat_model.bind_tools(lc_tools)

        async def call_model(state: AgentState) -> dict[str, Any]:
            if state["steps"] >= self.max_steps:
                raise MultiStepLimitError(
                    f"多步 Agent 超过 {self.max_steps} 步上限"
                )
            response = await model_with_tools.ainvoke(state["messages"])
            if not isinstance(response, AIMessage):
                response = AIMessage(content=_message_text(response))
            return {"messages": [response], "steps": 1}

        async def call_tools(state: AgentState) -> dict[str, Any]:
            last = state["messages"][-1]
            observations: list[BaseMessage] = []
            for index, call in enumerate(getattr(last, "tool_calls", None) or []):
                name = call.get("name", "")
                args = call.get("args") or {}
                call_id = call.get("id") or f"call_{state['steps']}_{index}"
                tool = tools_by_name.get(name)
                if tool is None:
                    content = json.dumps(
                        {"success": False, "response": f"未知工具: {name}"},
                        ensure_ascii=False,
                    )
                else:
                    try:
                        content = await tool.ainvoke(args)
                    except Exception as exc:  # noqa: BLE001 - 让模型看到工具错误
                        logger.warning("工具 {} 执行失败: {}", name, exc)
                        content = json.dumps(
                            {"success": False, "response": f"工具执行失败: {exc}"},
                            ensure_ascii=False,
                        )
                observations.append(
                    ToolMessage(
                        content=str(content),
                        tool_call_id=call_id,
                        name=name,
                    )
                )
            return {"messages": observations}

        def should_continue(state: AgentState) -> str:
            last = state["messages"][-1]
            return "tools" if getattr(last, "tool_calls", None) else END

        builder = StateGraph(AgentState)
        builder.add_node("model", call_model)
        builder.add_node("tools", call_tools)
        builder.add_edge(START, "model")
        builder.add_conditional_edges(
            "model", should_continue, {"tools": "tools", END: END}
        )
        builder.add_edge("tools", "model")
        return builder.compile()

    @staticmethod
    def _initial_messages(
        user_message: str, history: list[dict[str, str]]
    ) -> list[BaseMessage]:
        messages: list[BaseMessage] = [
            SystemMessage(content=get_multi_step_system_prompt())
        ]
        for item in history:
            content = item.get("content", "")
            role = item.get("role", "user")
            if role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "user":
                messages.append(HumanMessage(content=content))
        messages.append(HumanMessage(content=user_message))
        return messages


def _message_text(message: BaseMessage) -> str:
    """兼容字符串与内容块两种模型输出。"""
    content = message.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts).strip()
    return str(content).strip()

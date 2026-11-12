"""LangGraph 多步 Agent:模型节点 + 工具节点 + 条件边,最多 6 步。

设计要点:
- 图与 ChatModel 从外部注入,测试可传脚本化 Fake ChatModel;
- 可选 checkpointer + 订单选择 interrupt:只在「模型要提交售后申请但没带订单号」
  时暂停,暂停前只做只读查询,resume 后由工具节点执行一次申请;
- 审批单仍是执行真源:interrupt 只解决 slot-filling,不执行写操作;
- 失败、超过步数、空回复或没有产生工具结果时抛出 ``MultiStepError``,
  由调用方强停并返回兜底话术(MewHelp 风格),不再回退单步 Agent。
"""
from __future__ import annotations

import json
import time
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
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph.checkpointer import GRAPH_VERSION
from app.agents.graph.context import ToolContext
from app.agents.graph.tool_adapters import build_lc_tools, tool_error_payload
from app.agents.prompts.system_prompt import get_multi_step_system_prompt
from app.agents.tools.query_order import QueryOrderTool
from app.core.observability import langchain_config
from app.utils.logger import logger

DEFAULT_MAX_STEPS = 6


class MultiStepError(RuntimeError):
    """多步 Agent 无法产出可用结果的基类异常。"""


class MultiStepExecutionError(MultiStepError):
    """图执行过程中发生未预期异常。"""


class MultiStepLimitError(MultiStepError):
    """超过最大步数。"""


class MultiStepEmptyResultError(MultiStepError):
    """模型返回空内容,或整次执行没有产生工具结果。"""


class MultiStepResumeError(MultiStepError):
    """resume 时找不到可续跑的 interrupt。"""


class AgentState(TypedDict, total=False):
    """图状态:消息与本轮审计/工具记录。"""

    messages: Annotated[list[BaseMessage], add_messages]
    # 会话级 checkpoint 下,这些字段必须每轮覆盖而不是累加;
    # 节点自己负责在单轮内累加。
    steps: int
    session_id: str
    user_id: int | None
    user_message: str
    selected_order_no: str
    write_denied: bool
    graph_version: str
    tool_records: list[dict[str, Any]]
    run_steps: list[dict[str, Any]]


@dataclass(frozen=True)
class MultiStepResult:
    """多步 Agent 的最终结果。"""

    response: str
    tool_calls: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    pending_approval: dict[str, Any] | None
    steps: list[dict[str, Any]]
    interrupted: bool = False
    interrupt: dict[str, Any] | None = None
    thread_id: str | None = None


class MultiStepAgent:
    """把一次用户请求交给 LangGraph 完成多步工具调用。"""

    def __init__(
        self,
        chat_model: BaseChatModel,
        tools: dict[str, Any],
        max_steps: int = DEFAULT_MAX_STEPS,
        breaker: Any | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps 至少为 1")
        self.chat_model = chat_model
        self.tools = tools
        self.max_steps = max_steps
        self.breaker = breaker
        self.checkpointer = checkpointer

    async def run(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        db: AsyncSession | None = None,
        user_id: int | None = None,
        session_id: str = "",
        skill: str = "",
        thread_id: str | None = None,
    ) -> MultiStepResult:
        """执行图并返回最终回复、工具调用链或 interrupt。"""
        context = ToolContext(
            db=db,
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
        )
        with_checkpoint = bool(self.checkpointer is not None and thread_id)
        graph = self._build_graph(context, with_checkpoint=with_checkpoint)

        config: dict[str, Any] = {
            "recursion_limit": max(25, self.max_steps * 3)
        }
        config.update(
            langchain_config(
                session_id=session_id,
                user_id=user_id,
                trace_name="multi_step_agent",
                tags=["agent", "langgraph"],
            )
        )
        if with_checkpoint:
            config["configurable"] = {"thread_id": thread_id}

        # 会话级 checkpoint:已有历史时只追加本轮用户消息,
        # 避免把 history 再塞一遍;步骤/工具记录每轮重置。
        messages: list[BaseMessage]
        if with_checkpoint:
            snapshot = await graph.aget_state(config)
            has_state = bool((getattr(snapshot, "values", None) or {}).get("messages"))
            messages = (
                [HumanMessage(content=user_message)]
                if has_state
                else self._initial_messages(user_message, history or [], skill)
            )
        else:
            messages = self._initial_messages(user_message, history or [], skill)

        initial: dict[str, Any] = {
            "messages": messages,
            "steps": 0,
            "session_id": session_id,
            "user_id": user_id,
            "user_message": user_message,
            "selected_order_no": "",
            "write_denied": False,
            "graph_version": GRAPH_VERSION,
            "tool_records": [],
            "run_steps": [],
        }

        try:
            final_state = await graph.ainvoke(initial, config=config)
        except MultiStepError:
            raise
        except Exception as exc:  # 转成统一的多步失败异常
            logger.warning("多步 Agent 图执行失败: {}", exc)
            raise MultiStepExecutionError(f"多步 Agent 执行失败: {exc}") from exc

        interrupt_payload = _extract_interrupt(final_state)
        result = self._build_result(
            final_state,
            context,
            thread_id=thread_id if with_checkpoint else None,
            interrupted=bool(interrupt_payload),
            interrupt_payload=interrupt_payload,
        )
        # 会话级 checkpoint:成功后保留状态,供下一轮续接;不做 per-turn 删除。
        return result

    async def resume(
        self,
        thread_id: str,
        resume_value: Any,
        db: AsyncSession | None = None,
    ) -> MultiStepResult:
        """从同一个 thread_id 的 interrupt 继续执行。"""
        if self.checkpointer is None or not thread_id:
            raise MultiStepResumeError("当前未启用 checkpointer,无法 resume")

        context = ToolContext(
            db=db,
            user_id=None,
            session_id="",
            user_message="",
        )
        graph = self._build_graph(context, with_checkpoint=True)
        config: dict[str, Any] = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": max(25, self.max_steps * 3),
        }

        try:
            snapshot = await graph.aget_state(config)
        except Exception as exc:
            raise MultiStepResumeError(f"读取 checkpoint 失败: {exc}") from exc

        values = getattr(snapshot, "values", None) or {}
        if not values:
            raise MultiStepResumeError("找不到该 thread 的 checkpoint")
        if values.get("graph_version") != GRAPH_VERSION:
            raise MultiStepResumeError("图版本已变化,请重新发送消息")
        if not getattr(snapshot, "next", None):
            raise MultiStepResumeError("当前 thread 没有待恢复的 interrupt")

        context.user_id = values.get("user_id")
        context.session_id = values.get("session_id", "")
        context.user_message = values.get("user_message", "")
        config.update(
            langchain_config(
                session_id=context.session_id,
                user_id=context.user_id,
                trace_name="multi_step_agent_resume",
                tags=["agent", "langgraph", "resume"],
            )
        )

        try:
            final_state = await graph.ainvoke(Command(resume=resume_value), config)
        except MultiStepError:
            raise
        except Exception as exc:
            logger.warning("多步 Agent resume 失败: {}", exc)
            raise MultiStepExecutionError(f"多步 Agent resume 失败: {exc}") from exc

        interrupt_payload = _extract_interrupt(final_state)
        result = self._build_result(
            final_state,
            context,
            thread_id=thread_id,
            interrupted=bool(interrupt_payload),
            interrupt_payload=interrupt_payload,
        )
        return result

    # ---------------- 结果组装 ----------------
    def _build_result(
        self,
        final_state: dict[str, Any],
        context: ToolContext,
        *,
        thread_id: str | None,
        interrupted: bool,
        interrupt_payload: dict[str, Any] | None,
    ) -> MultiStepResult:
        records = final_state.get("tool_records") or context.tool_records
        steps = final_state.get("run_steps") or context.steps

        if interrupted:
            response = str(
                (interrupt_payload or {}).get("message")
                or "请选择要办理的订单"
            )
        else:
            messages = final_state.get("messages") or []
            if not messages:
                raise MultiStepEmptyResultError("多步 Agent 未产出最终回复")
            final_message = messages[-1]
            if not isinstance(final_message, AIMessage):
                raise MultiStepEmptyResultError("多步 Agent 未产出最终回复")
            response = _message_text(final_message)
            if not response:
                raise MultiStepEmptyResultError("多步 Agent 返回了空回复")
            if not records:
                raise MultiStepEmptyResultError("多步 Agent 没有产生可用的工具结果")

        tool_calls: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        pending_approval: dict[str, Any] | None = None
        seen_citation_ids: set[Any] = set()
        for record in records:
            entry = {
                "tool": record.get("tool", "unknown"),
                "success": bool(record.get("success")),
            }
            if record.get("transport"):
                entry["transport"] = record["transport"]
            tool_calls.append(entry)
            for citation in record.get("citations") or []:
                if citation.get("id") not in seen_citation_ids:
                    citations.append(citation)
                    seen_citation_ids.add(citation.get("id"))
            if record.get("proposal"):
                pending_approval = record["proposal"]

        return MultiStepResult(
            response=response,
            tool_calls=tool_calls,
            citations=citations,
            pending_approval=pending_approval,
            steps=list(steps),
            interrupted=interrupted,
            interrupt=interrupt_payload,
            thread_id=thread_id,
        )

    # ---------------- 图构建 ----------------
    def _build_graph(
        self, context: ToolContext, *, with_checkpoint: bool = False
    ) -> Any:
        lc_tools = build_lc_tools(self.tools, context)
        tools_by_name = {tool.name: tool for tool in lc_tools}
        model_with_tools = self.chat_model.bind_tools(lc_tools)

        async def call_model(state: AgentState) -> dict[str, Any]:
            if state.get("steps", 0) >= self.max_steps:
                raise MultiStepLimitError(
                    f"多步 Agent 超过 {self.max_steps} 步上限"
                )
            started = time.perf_counter()
            try:
                if self.breaker is not None:
                    response = await self.breaker.call(
                        model_with_tools.ainvoke, state["messages"]
                    )
                else:
                    response = await model_with_tools.ainvoke(state["messages"])
            except Exception as exc:
                step = {
                    "step_type": "model",
                    "name": "agent_model",
                    "input": {"messages": len(state["messages"])},
                    "output": {"error": str(exc)[:300]},
                    "success": False,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
                context.steps.append(step)
                raise
            if not isinstance(response, AIMessage):
                response = AIMessage(content=_message_text(response))
            tool_names = [
                call.get("name", "")
                for call in (getattr(response, "tool_calls", None) or [])
            ]
            usage = getattr(response, "usage_metadata", None) or {}
            step = {
                "step_type": "model",
                "name": "agent_model",
                "input": {"messages": len(state["messages"])},
                "output": {"tool_calls": tool_names},
                "success": True,
                "tokens": int(usage.get("total_tokens", 0) or 0),
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
            context.steps.append(step)
            return {
                "messages": [response],
                "steps": state.get("steps", 0) + 1,
                "run_steps": [*(state.get("run_steps") or []), step],
            }

        async def call_tools(state: AgentState) -> dict[str, Any]:
            last = state["messages"][-1]
            observations: list[BaseMessage] = []
            record_start = len(context.tool_records)
            step_start = len(context.steps)
            selected_order_no = state.get("selected_order_no", "")

            for index, call in enumerate(getattr(last, "tool_calls", None) or []):
                name = call.get("name", "")
                args = dict(call.get("args") or {})
                call_id = call.get("id") or f"call_{state.get('steps', 0)}_{index}"
                tool = tools_by_name.get(name)
                started = time.perf_counter()

                if (
                    name == "propose_after_sales_action"
                    and not args.get("order_no")
                    and selected_order_no
                ):
                    args["order_no"] = selected_order_no

                if name == "create_ticket" and state.get("write_denied"):
                    payload = {
                        "success": False,
                        "response": "用户取消了本次工单创建,请不要再发起。",
                        "error_code": "WRITE_DENIED",
                    }
                    context.record_tool_call(
                        name,
                        payload,
                        args=args,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
                    observations.append(
                        ToolMessage(
                            content=json.dumps(payload, ensure_ascii=False),
                            tool_call_id=call_id,
                            name=name,
                        )
                    )
                    continue

                if tool is None:
                    payload = {
                        "success": False,
                        "response": f"未知工具: {name}",
                        "error_code": "UNKNOWN_TOOL",
                    }
                    context.record_tool_call(
                        name or "unknown",
                        payload,
                        args=args,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
                    content = json.dumps(payload, ensure_ascii=False)
                else:
                    try:
                        content = await tool.ainvoke(args)
                    except Exception as exc:  # noqa: BLE001 - 让模型看到工具错误
                        logger.warning("工具 {} 执行失败: {}", name, exc)
                        payload = tool_error_payload(name, exc)
                        context.record_tool_call(
                            name,
                            payload,
                            args=args,
                            latency_ms=int(
                                (time.perf_counter() - started) * 1000
                            ),
                        )
                        content = json.dumps(payload, ensure_ascii=False)
                observations.append(
                    ToolMessage(
                        content=str(content),
                        tool_call_id=call_id,
                        name=name,
                    )
                )
            return {
                "messages": observations,
                "tool_records": [
                    *(state.get("tool_records") or []),
                    *context.tool_records[record_start:],
                ],
                "run_steps": [
                    *(state.get("run_steps") or []),
                    *context.steps[step_start:],
                ],
            }

        async def pre_tool_gate(state: AgentState) -> dict[str, Any]:
            """只读 gate:模型要提交售后申请但没订单号时,让用户选择订单。"""
            last = state["messages"][-1]
            calls = getattr(last, "tool_calls", None) or []
            proposals = [
                call
                for call in calls
                if call.get("name") == "propose_after_sales_action"
            ]
            if proposals:
                if any(
                    (call.get("args") or {}).get("order_no")
                    for call in proposals
                ):
                    return {}

                user_message = state.get("user_message", "")
                order_no = QueryOrderTool._extract_order_no(user_message)
                if order_no:
                    check = await self._query_order(context, order_no)
                    if check.get("success"):
                        return {"selected_order_no": order_no}
                    return {}

                result = await self._query_order(context, None)
                orders = result.get("orders") or []
                if not orders:
                    return {}
                if len(orders) == 1:
                    return {
                        "selected_order_no": orders[0].get("order_no", "")
                    }

                resumed = interrupt(
                    {
                        "type": "select_order",
                        "orders": orders,
                        "message": "请选择要办理的订单",
                    }
                )
                if (
                    not isinstance(resumed, dict)
                    or resumed.get("type") != "select_order"
                ):
                    return {}
                selected = str(resumed.get("order_no") or "").strip()
                if not selected:
                    return {}
                check = await self._query_order(context, selected)
                if not check.get("success"):
                    return {}
                return {"selected_order_no": selected}

            # 工单确认:写操作在 resume 确认后才允许执行
            tickets = [
                call for call in calls if call.get("name") == "create_ticket"
            ]
            if not tickets or context.write_confirmed:
                return {}
            preview = tickets[0].get("args") or {}
            resumed = interrupt(
                {
                    "type": "confirm_ticket",
                    "message": "请确认是否创建工单",
                    "preview": preview,
                }
            )
            if (
                isinstance(resumed, dict)
                and resumed.get("type") == "confirm_ticket"
                and resumed.get("confirmed") is True
            ):
                context.write_confirmed = True
                return {}
            return {"write_denied": True}

        def should_continue(state: AgentState) -> str:
            last = state["messages"][-1]
            return "tools" if getattr(last, "tool_calls", None) else END

        builder = StateGraph(AgentState)
        builder.add_node("model", call_model)
        builder.add_node("tools", call_tools)
        builder.add_edge(START, "model")

        if with_checkpoint:
            builder.add_node("pre_tool_gate", pre_tool_gate)
            builder.add_conditional_edges(
                "model",
                should_continue,
                {"tools": "pre_tool_gate", END: END},
            )
            builder.add_edge("pre_tool_gate", "tools")
        else:
            builder.add_conditional_edges(
                "model", should_continue, {"tools": "tools", END: END}
            )

        builder.add_edge("tools", "model")
        return builder.compile(
            checkpointer=self.checkpointer if with_checkpoint else None
        )

    async def _query_order(
        self, context: ToolContext, order_no: str | None
    ) -> dict[str, Any]:
        tool = self.tools.get("query_order")
        if tool is None:
            return {"success": False}
        try:
            params = (
                context.tool_params(order_no=order_no)
                if order_no
                else context.tool_params()
            )
            result = await tool.execute(params)
            return result if isinstance(result, dict) else {"success": False}
        except Exception as exc:  # noqa: BLE001 - gate 查询失败按无结果处理
            logger.warning("订单选择 gate 查询失败: {}", exc)
            return {"success": False}

    @staticmethod
    def _initial_messages(
        user_message: str,
        history: list[dict[str, str]],
        skill: str = "",
    ) -> list[BaseMessage]:
        messages: list[BaseMessage] = [
            SystemMessage(content=get_multi_step_system_prompt(skill))
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


def _extract_interrupt(final_state: dict[str, Any]) -> dict[str, Any] | None:
    interrupts = final_state.get("__interrupt__") or []
    if not interrupts:
        return None
    first = interrupts[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else None


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

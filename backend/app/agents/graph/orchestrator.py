"""确定性路由图:coref → intent → 分支 → finalize。

设计原则:
- 只做路由与编排,具体 RAG/工具/审批仍复用现有服务;
- ReAct 工具循环(model / pre_tool_gate / agent_tools)直接作为主图节点,
  不再另起一层多步 Agent 图;
- 多步失败强停兜底;图整体异常时由 ``CustomerServiceAgent.chat``
  使用旧链路兼容兜底(非多步 Agent fallback);
- 不在这里执行写操作;售后申请仍走审批服务。
"""
from __future__ import annotations

import json
import time
from typing import Annotated, Any, TypedDict

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

from app.agents.graph.checkpointer import GRAPH_VERSION
from app.agents.graph.context import ToolContext
from app.agents.graph.multi_step_agent import (
    MultiStepError,
    MultiStepLimitError,
    MultiStepResumeError,
    _message_text,
)
from app.agents.graph.tool_adapters import build_lc_tools, tool_error_payload
from app.agents.prompts.system_prompt import get_multi_step_system_prompt
from app.agents.tools.query_order import QueryOrderTool
from app.core.config import settings
from app.core.observability import langchain_config, tag_current_trace
from app.schemas.chat import AgentMode
from app.schemas.intent import IntentResult
from app.services.answer_guard import repair_hint, unsupported_entities
from app.services.evidence import evidence_snapshot
from app.services.knowledge_pool import record_low_confidence
from app.services.llm_service import LLMError
from app.services.selfcheck import check_sufficient
from app.utils.logger import logger


class OrchestratorState(TypedDict, total=False):
    user_message: str
    resolved_message: str
    history: list[dict[str, str]]
    sentiment: str
    sentiment_score: float
    intent: dict[str, Any]
    skill_text: str
    rag_result: Any
    rag_ready: bool
    response: str
    citations: list[dict[str, Any]]
    pending_approval: dict[str, Any] | None
    tool_calls: list[dict[str, Any]]
    run_steps: list[dict[str, Any]]
    need_transfer: bool
    evidence_status: str | None
    agent_mode: str
    thread_id: str | None
    interrupt: dict[str, Any] | None
    # ReAct 工具循环
    user_id: int | None
    session_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    steps: int
    tool_records: list[dict[str, Any]]
    selected_order_no: str
    write_denied: bool
    graph_version: str


class GraphOrchestrator:
    """把一次请求按确定性节点走完;ReAct 工具循环也在这一张图里。"""

    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self.react = agent.multi_step_agent
        self.checkpointer = (
            getattr(self.react, "checkpointer", None) if self.react else None
        )
        self.max_steps = getattr(self.react, "max_steps", 6) if self.react else 6
        self.thread_id = agent.thread_id or agent.session_id
        self.context: ToolContext | None = None
        self.tools_by_name: dict[str, Any] = {}
        self.model_with_tools: Any = None

    # ---------------- 入口 ----------------
    async def run(self, user_message: str) -> dict[str, Any]:
        with_checkpoint = bool(
            self.react and self.checkpointer and self.thread_id
        )
        graph = self._build_graph(with_checkpoint=with_checkpoint)
        config = self._config()
        self._setup_context(
            user_id=self.agent.user_id,
            session_id=self.agent.session_id,
            user_message=user_message,
        )

        initial: dict[str, Any] = {
            "user_message": user_message,
            "history": self.agent.get_history(6),
            "run_steps": [],
            "citations": [],
            "tool_calls": [],
            "pending_approval": None,
            "need_transfer": False,
            "evidence_status": None,
            "agent_mode": AgentMode.SINGLE_STEP.value,
            "thread_id": self.thread_id,
            "interrupt": None,
            "user_id": self.agent.user_id,
            "session_id": self.agent.session_id,
            "steps": 0,
            "tool_records": [],
            "selected_order_no": "",
            "write_denied": False,
            "graph_version": GRAPH_VERSION,
            "messages": [],
        }
        if with_checkpoint:
            snapshot = await graph.aget_state(config)
            if (getattr(snapshot, "values", None) or {}).get("messages"):
                # 会话级 checkpoint:已有消息时只追加本轮用户消息
                initial["messages"] = [HumanMessage(content=user_message)]

        try:
            final_state = await graph.ainvoke(initial, config=config)
        except MultiStepError as exc:
            logger.warning("主图 ReAct 强停: {}", exc)
            return self._fallback_result(initial["intent"] if "intent" in initial else None)
        except Exception as exc:  # noqa: BLE001 - 图异常强停,不回退单步 Agent
            logger.exception("主图执行失败,返回兜底话术: {}", exc)
            return self._fallback_result(None)
        return self._result_from_state(final_state)

    async def resume(self, thread_id: str, resume_value: Any) -> dict[str, Any]:
        """从同一会话 thread 的 interrupt 继续执行。"""
        if self.checkpointer is None:
            raise MultiStepResumeError("当前未启用 checkpointer,无法 resume")
        self.thread_id = thread_id
        graph = self._build_graph(with_checkpoint=True)
        config = self._config()
        try:
            snapshot = await graph.aget_state(config)
        except Exception as exc:  # noqa: BLE001
            raise MultiStepResumeError(f"读取 checkpoint 失败: {exc}") from exc
        values = getattr(snapshot, "values", None) or {}
        if not values:
            raise MultiStepResumeError("找不到该 thread 的 checkpoint")
        if values.get("graph_version") != GRAPH_VERSION:
            raise MultiStepResumeError("图版本已变化,请重新发送消息")
        if not getattr(snapshot, "next", None):
            raise MultiStepResumeError("当前 thread 没有待恢复的 interrupt")

        self._setup_context(
            user_id=values.get("user_id"),
            session_id=values.get("session_id", ""),
            user_message=values.get("user_message", ""),
        )
        # resume 从 gate 直接进 agent_tools,不会经过 main_agent,需提前绑定工具
        self._ensure_react_setup()
        try:
            final_state = await graph.ainvoke(
                Command(resume=resume_value), config=config
            )
        except MultiStepError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("主图 resume 失败: {}", exc)
            raise MultiStepResumeError(f"主图 resume 失败: {exc}") from exc
        return self._result_from_state(final_state)

    def _config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "recursion_limit": max(25, self.max_steps * 3)
        }
        config.update(
            langchain_config(
                session_id=self.agent.session_id,
                user_id=self.agent.user_id,
                trace_name="graph_orchestrator",
                tags=["agent", "langgraph", "orchestrator"],
            )
        )
        if self.checkpointer and self.thread_id:
            config["configurable"] = {"thread_id": self.thread_id}
        return config

    def _setup_context(
        self, user_id: int | None, session_id: str, user_message: str
    ) -> None:
        self.context = ToolContext(
            db=self.agent.db,
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
        )
        self.tools_by_name = {}
        self.model_with_tools = None

    def _ensure_react_setup(self) -> None:
        if self.react is None or self.context is None:
            return
        if self.model_with_tools is not None:
            return
        lc_tools = build_lc_tools(self.react.tools, self.context)
        self.tools_by_name = {tool.name: tool for tool in lc_tools}
        self.model_with_tools = self.react.chat_model.bind_tools(lc_tools)

    # ---------------- 节点:预处理 ----------------
    async def _preprocess(self, state: OrchestratorState) -> dict[str, Any]:
        return {"user_message": self.agent._preprocess(state["user_message"])}

    async def _memory_context(
        self, state: OrchestratorState
    ) -> dict[str, Any]:
        from app.services.memory_service import take_recent_with_context

        history = [
            item
            for item in (state.get("history") or [])
            if item.get("role") in ("user", "assistant")
        ]
        return {"history": take_recent_with_context(history, 6)}

    async def _coref(self, state: OrchestratorState) -> dict[str, Any]:
        started = time.perf_counter()
        resolved = await self.agent.coref_service.resolve(
            state["user_message"], state.get("history") or []
        )
        steps = list(state.get("run_steps") or [])
        if resolved != state["user_message"]:
            steps.append(
                {
                    "step_type": "model",
                    "name": "coref_resolve",
                    "input": {"query": state["user_message"][:200]},
                    "output": {"resolved": resolved[:300]},
                    "success": True,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
            )
        return {"resolved_message": resolved, "run_steps": steps}

    async def _intent(self, state: OrchestratorState) -> dict[str, Any]:
        message = state["resolved_message"]
        sentiment, score = await self.agent.sentiment_service.analyze(
            state["user_message"]
        )
        intent = await self.agent.intent_service.recognize(
            message,
            self.agent.user_id,
            context=self.agent.context_text(),
        )
        tag_current_trace(
            metadata={
                "intent": intent.intent_code,
                "intent_confidence": f"{intent.confidence:.2f}",
            },
            tags=[f"intent:{intent.intent_code}"],
        )
        if settings.MCP_ENABLED and intent.handler_type in ("tool", "transfer"):
            await self.agent._refresh_mcp_tools()
        return {
            "sentiment": sentiment.value,
            "sentiment_score": score,
            "intent": intent.model_dump(),
            "skill_text": self.agent.skill_service.get(intent.intent_code),
        }

    def _route(self, state: OrchestratorState) -> str:
        intent = state.get("intent") or {}
        handler = intent.get("handler_type", "llm")
        code = intent.get("intent_code", "fallback")
        if handler == "transfer":
            return "transfer"
        if handler == "rag":
            return "rag"
        if handler == "tool":
            return "main_agent" if self.react is not None else "single_tool"
        if code in ("greeting", "chitchat"):
            return "script"
        return "llm"

    # ---------------- 节点:确定性出口 ----------------
    async def _script(self, state: OrchestratorState) -> dict[str, Any]:
        intent = IntentResult(**state["intent"])
        started = time.perf_counter()
        response = self.agent._script_reply(intent)
        steps = list(state.get("run_steps") or [])
        steps.append(
            {
                "step_type": "model",
                "name": "script_reply",
                "input": {"message": state["resolved_message"][:200]},
                "output": {"response": response[:300]},
                "success": True,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return {"response": response, "run_steps": steps}

    async def _transfer(self, state: OrchestratorState) -> dict[str, Any]:
        started = time.perf_counter()
        result = await self.agent.tools["transfer_human"].execute(
            self.agent._tool_params(state["resolved_message"])
        )
        steps = list(state.get("run_steps") or [])
        steps.append(
            {
                "step_type": "tool",
                "name": "transfer_human",
                "input": {"reason": state["resolved_message"][:100]},
                "output": {
                    "success": bool(result.get("success")),
                    "response": str(result.get("response", ""))[:300],
                    **(
                        {"transport": result["transport"]}
                        if result.get("transport")
                        else {}
                    ),
                },
                "success": bool(result.get("success")),
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        record = {
            "tool": "transfer_human",
            "success": bool(result.get("success")),
        }
        if result.get("transport"):
            record["transport"] = result["transport"]
        return {
            "response": result.get("response", "已为您转接人工客服"),
            "need_transfer": bool(result.get("success")),
            "tool_calls": [record],
            "run_steps": steps,
        }

    # ---------------- 节点:RAG ----------------
    async def _retrieve_knowledge(
        self, state: OrchestratorState
    ) -> dict[str, Any]:
        started = time.perf_counter()
        result = await self.agent.rag_service.retrieve_with_evidence(
            state["resolved_message"], top_k=3
        )
        sufficient = bool(result.hits and result.evidence.strong)
        steps = list(state.get("run_steps") or [])
        steps.append(
            {
                "step_type": "tool",
                "name": "rag_retrieve",
                "input": {"query": state["resolved_message"][:200]},
                "output": {
                    "citations": len(result.citations),
                    "evidence_status": (
                        "sufficient" if sufficient else "insufficient"
                    ),
                },
                "success": sufficient,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return {
            "rag_result": result,
            "citations": result.citations,
            "evidence_status": (
                "sufficient" if sufficient else "insufficient"
            ),
            "run_steps": steps,
        }

    async def _evidence_gate(
        self, state: OrchestratorState
    ) -> dict[str, Any]:
        result = state.get("rag_result")
        if result is None or not result.hits or not result.evidence.strong:
            await record_low_confidence(
                self.agent.db,
                self.agent.session_id,
                state["resolved_message"],
                "retrieval_low_conf",
                f"evidence={result.evidence.score if result else 0} "
                f"mode={result.mode if result else 'none'}",
                evidence_snapshot(result.hits if result else []),
            )
            return {
                "response": self.agent.RAG_FALLBACK_TEXT,
                "evidence_status": "insufficient",
                "citations": [],
            }

        if settings.RAG_SELF_CHECK:
            check = await check_sufficient(
                state["resolved_message"],
                [
                    f"{hit.get('question', '')}: {hit.get('answer', '')}"
                    for hit in result.hits
                ],
                llm=self.agent.llm_service,
            )
            if not check["useful"]:
                await record_low_confidence(
                    self.agent.db,
                    self.agent.session_id,
                    state["resolved_message"],
                    "self_check",
                    check.get("reason") or "self_check 未通过",
                    evidence_snapshot(result.hits),
                )
                return {
                    "response": self.agent.RAG_FALLBACK_TEXT,
                    "evidence_status": "insufficient",
                    "citations": [],
                }
        return {"rag_ready": True}

    async def _generate_answer(
        self, state: OrchestratorState
    ) -> dict[str, Any]:
        result = state["rag_result"]
        message = state["resolved_message"]
        skill = state.get("skill_text", "")
        evidence_text = "\n".join(
            f"{hit.get('question', '')} {hit.get('answer', '')}"
            for hit in result.hits
        )
        started = time.perf_counter()
        try:
            answer = await self.agent.rag_service.generate(
                message, result.context, skill=skill
            )
            bad = unsupported_entities(answer, evidence_text)
            if bad:
                answer = await self.agent.rag_service.generate(
                    f"{message}\n\n{repair_hint(bad)}",
                    result.context,
                    skill=skill,
                )
                bad = unsupported_entities(answer, evidence_text)
            if bad:
                await record_low_confidence(
                    self.agent.db,
                    self.agent.session_id,
                    message,
                    "answer_guard",
                    "unsupported: " + "、".join(bad),
                    evidence_snapshot(result.hits),
                )
                return {
                    "response": self.agent.RAG_FALLBACK_TEXT,
                    "evidence_status": "insufficient",
                    "citations": [],
                }
            response = answer
        except LLMError:
            response = f"根据知识库:\n\n{result.context}"

        steps = list(state.get("run_steps") or [])
        steps.append(
            {
                "step_type": "model",
                "name": "rag_generate",
                "input": {"query": message[:200]},
                "output": {"chars": len(response)},
                "success": True,
                "tokens": max(1, (len(message) + len(response)) // 4),
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return {
            "response": response,
            "citations": result.citations,
            "evidence_status": "sufficient",
            "run_steps": steps,
        }

    # ---------------- 节点:ReAct 工具循环 ----------------
    async def _main_agent(self, state: OrchestratorState) -> dict[str, Any]:
        if self.react is None:
            return await self._single_tool(state)
        self._ensure_react_setup()
        if self.model_with_tools is None:
            raise MultiStepLimitError("ChatModel 不可用,无法执行多步工具循环")
        if state.get("steps", 0) >= self.max_steps:
            raise MultiStepLimitError(
                f"多步 Agent 超过 {self.max_steps} 步上限"
            )

        messages = list(state.get("messages") or [])
        first_turn = not messages
        if first_turn:
            messages = self.react._initial_messages(
                state["user_message"],
                state.get("history") or [],
                state.get("skill_text", ""),
            )

        started = time.perf_counter()
        try:
            if self.react.breaker is not None:
                response = await self.react.breaker.call(
                    self.model_with_tools.ainvoke, messages
                )
            else:
                response = await self.model_with_tools.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001 - 让上层强停兜底
            step = {
                "step_type": "model",
                "name": "agent_model",
                "input": {"messages": len(messages)},
                "output": {"error": str(exc)[:300]},
                "success": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
            if self.context is not None:
                self.context.steps.append(step)
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
            "input": {"messages": len(messages)},
            "output": {"tool_calls": tool_names},
            "success": True,
            "tokens": int(usage.get("total_tokens", 0) or 0),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
        if self.context is not None:
            self.context.steps.append(step)
        update: dict[str, Any] = {
            "messages": ([*messages, response] if first_turn else [response]),
            "steps": state.get("steps", 0) + 1,
            "run_steps": [*(state.get("run_steps") or []), step],
            "agent_mode": AgentMode.MULTI_STEP.value,
            "thread_id": self.thread_id,
        }
        return update

    async def _pre_tool_gate(
        self, state: OrchestratorState
    ) -> dict[str, Any]:
        last = (state.get("messages") or [])[-1]
        calls = getattr(last, "tool_calls", None) or []
        proposals = [
            call
            for call in calls
            if call.get("name") == "propose_after_sales_action"
        ]
        if proposals:
            if any(
                (call.get("args") or {}).get("order_no") for call in proposals
            ):
                return {}

            user_message = state.get("user_message", "")
            order_no = QueryOrderTool._extract_order_no(user_message)
            if order_no:
                check = await self.react._query_order(self.context, order_no)
                if check.get("success"):
                    return {"selected_order_no": order_no}
                return {}

            result = await self.react._query_order(self.context, None)
            orders = result.get("orders") or []
            if not orders:
                return {}
            if len(orders) == 1:
                return {"selected_order_no": orders[0].get("order_no", "")}

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
            check = await self.react._query_order(self.context, selected)
            if not check.get("success"):
                return {}
            return {"selected_order_no": selected}

        tickets = [
            call for call in calls if call.get("name") == "create_ticket"
        ]
        if not tickets or (self.context and self.context.write_confirmed):
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
            if self.context is not None:
                self.context.write_confirmed = True
            return {}
        return {"write_denied": True}

    async def _agent_tools(self, state: OrchestratorState) -> dict[str, Any]:
        last = (state.get("messages") or [])[-1]
        observations: list[BaseMessage] = []
        context = self.context
        if context is None:
            return {}
        record_start = len(context.tool_records)
        step_start = len(context.steps)
        selected_order_no = state.get("selected_order_no", "")

        for index, call in enumerate(getattr(last, "tool_calls", None) or []):
            name = call.get("name", "")
            args = dict(call.get("args") or {})
            call_id = call.get("id") or f"call_{state.get('steps', 0)}_{index}"
            tool = self.tools_by_name.get(name)
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
                        latency_ms=int((time.perf_counter() - started) * 1000),
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

    async def _single_tool(self, state: OrchestratorState) -> dict[str, Any]:
        """无 ChatModel 时的单步离线模式,不是多步失败 fallback。"""
        intent = IntentResult(**state["intent"])
        response, tool_calls, pending, step = await self.agent._handle_with_tools(
            intent, state["resolved_message"], state.get("skill_text", "")
        )
        steps = list(state.get("run_steps") or [])
        if step is not None:
            steps.append(step)
        return {
            "response": response,
            "tool_calls": tool_calls,
            "pending_approval": pending,
            "run_steps": steps,
            "agent_mode": AgentMode.SINGLE_STEP.value,
        }

    async def _llm(self, state: OrchestratorState) -> dict[str, Any]:
        started = time.perf_counter()
        response = await self.agent._handle_with_llm(
            state["resolved_message"], state.get("skill_text", "")
        )
        steps = list(state.get("run_steps") or [])
        steps.append(
            {
                "step_type": "model",
                "name": "llm_reply",
                "input": {"message": state["resolved_message"][:200]},
                "output": {"response": response[:300]},
                "success": True,
                "tokens": max(
                    1,
                    (len(state["resolved_message"]) + len(response)) // 4,
                ),
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return {"response": response, "run_steps": steps}

    async def _finalize(self, state: OrchestratorState) -> dict[str, Any]:
        intent = IntentResult(**state["intent"])
        agent_mode = state.get("agent_mode", AgentMode.SINGLE_STEP.value)

        if agent_mode == AgentMode.MULTI_STEP.value:
            response, tool_calls, citations, pending = self._react_result(state)
        else:
            response = state.get("response") or "抱歉,请稍后再试。"
            tool_calls = state.get("tool_calls") or []
            citations = state.get("citations") or []
            pending = state.get("pending_approval")

        response = self.agent._add_sentiment_prefix(
            response, _sentiment(state.get("sentiment", "neutral"))
        )
        self.agent.conversation_history.extend(
            [
                {"role": "user", "content": state["user_message"]},
                {"role": "assistant", "content": response},
            ]
        )

        update: dict[str, Any] = {
            "response": response,
            "intent": intent.model_dump(),
            "sentiment": state.get("sentiment", "neutral"),
            "sentiment_score": state.get("sentiment_score", 0.0),
            "quick_replies": self.agent._quick_replies(intent),
            "need_transfer": bool(state.get("need_transfer"))
            or any(
                call.get("tool") == "transfer_human"
                and call.get("success")
                for call in tool_calls
            ),
            "tool_calls": tool_calls,
            "citations": citations,
            "pending_approval": pending,
            "evidence_status": state.get("evidence_status"),
            "run_steps": state.get("run_steps") or [],
            "agent_mode": agent_mode,
            "thread_id": state.get("thread_id") or self.thread_id,
            "interrupt": None,
        }

        messages = state.get("messages") or []
        if agent_mode != AgentMode.MULTI_STEP.value:
            # 非 ReAct 路径:把本轮用户消息和回复写入会话级 state,
            # 下一轮 ReAct 能看到完整对话。
            if messages:
                update["messages"] = [AIMessage(content=response)]
            else:
                update["messages"] = [
                    SystemMessage(
                        content=get_multi_step_system_prompt(
                            state.get("skill_text", "")
                        )
                    ),
                    HumanMessage(content=state["user_message"]),
                    AIMessage(content=response),
                ]
        else:
            last = messages[-1] if messages else None
            if not isinstance(last, AIMessage) or _message_text(last) != response:
                update["messages"] = [AIMessage(content=response)]
        return update

    def _react_result(
        self, state: OrchestratorState
    ) -> tuple[
        str,
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, Any] | None,
    ]:
        messages = state.get("messages") or []
        response = ""
        if messages and isinstance(messages[-1], AIMessage):
            response = _message_text(messages[-1])
        if not response or state.get("steps", 0) >= self.max_steps:
            response = self.agent.MULTI_STEP_FALLBACK_TEXT

        context = self.context
        records = state.get("tool_records") or (
            context.tool_records if context else []
        )
        tool_calls: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        pending: dict[str, Any] | None = None
        seen: set[Any] = set()
        for record in records:
            entry = {
                "tool": record.get("tool", "unknown"),
                "success": bool(record.get("success")),
            }
            if record.get("transport"):
                entry["transport"] = record["transport"]
            tool_calls.append(entry)
            for citation in record.get("citations") or []:
                if citation.get("id") not in seen:
                    citations.append(citation)
                    seen.add(citation.get("id"))
            if record.get("proposal"):
                pending = record["proposal"]
        return response, tool_calls, citations, pending

    # ---------------- 图 ----------------
    def _build_graph(self, *, with_checkpoint: bool = False) -> Any:
        builder = StateGraph(OrchestratorState)
        builder.add_node("preprocess", self._preprocess)
        builder.add_node("memory_context", self._memory_context)
        builder.add_node("coref", self._coref)
        builder.add_node("intent", self._intent)
        builder.add_node("script", self._script)
        builder.add_node("transfer", self._transfer)
        builder.add_node("retrieve_knowledge", self._retrieve_knowledge)
        builder.add_node("evidence_gate", self._evidence_gate)
        builder.add_node("generate_answer", self._generate_answer)
        builder.add_node("main_agent", self._main_agent)
        builder.add_node("agent_tools", self._agent_tools)
        builder.add_node("single_tool", self._single_tool)
        builder.add_node("llm", self._llm)
        builder.add_node("finalize", self._finalize)
        if with_checkpoint:
            builder.add_node("pre_tool_gate", self._pre_tool_gate)

        builder.add_edge(START, "preprocess")
        builder.add_edge("preprocess", "memory_context")
        builder.add_edge("memory_context", "coref")
        builder.add_edge("coref", "intent")
        builder.add_conditional_edges(
            "intent",
            self._route,
            {
                "script": "script",
                "transfer": "transfer",
                "rag": "retrieve_knowledge",
                "main_agent": "main_agent",
                "single_tool": "single_tool",
                "llm": "llm",
            },
        )
        builder.add_edge("retrieve_knowledge", "evidence_gate")
        builder.add_conditional_edges(
            "evidence_gate",
            self._after_evidence,
            {
                "generate_answer": "generate_answer",
                "finalize": "finalize",
            },
        )

        def should_continue(state: OrchestratorState) -> str:
            last = (state.get("messages") or [])[-1]
            has_tool_calls = isinstance(last, AIMessage) and bool(last.tool_calls)
            if not has_tool_calls:
                return "finalize"
            if state.get("steps", 0) >= self.max_steps:
                return "finalize"
            return "gate" if with_checkpoint else "tools"

        if with_checkpoint:
            builder.add_conditional_edges(
                "main_agent",
                should_continue,
                {"gate": "pre_tool_gate", "finalize": "finalize"},
            )
            builder.add_edge("pre_tool_gate", "agent_tools")
        else:
            builder.add_conditional_edges(
                "main_agent",
                should_continue,
                {"tools": "agent_tools", "finalize": "finalize"},
            )
        builder.add_edge("agent_tools", "main_agent")

        for node in ("script", "transfer", "generate_answer", "single_tool", "llm"):
            builder.add_edge(node, "finalize")
        builder.add_edge("finalize", END)
        return builder.compile(
            checkpointer=self.checkpointer if with_checkpoint else None
        )

    @staticmethod
    def _after_evidence(state: OrchestratorState) -> str:
        return "generate_answer" if state.get("rag_ready") else "finalize"

    # ---------------- 结果组装 ----------------
    def _result_from_state(self, state: OrchestratorState) -> dict[str, Any]:
        interrupts = state.get("__interrupt__") or []
        if interrupts:
            first = interrupts[0]
            payload = getattr(first, "value", first)
            if not isinstance(payload, dict):
                payload = {"message": str(payload)}
            intent_data = state.get("intent") or {}
            intent = (
                IntentResult(**intent_data)
                if intent_data
                else _fallback_intent()
            )
            return {
                "response": payload.get("message") or "请补充必要信息",
                "intent": intent.model_dump(),
                "sentiment": state.get("sentiment", "neutral"),
                "sentiment_score": state.get("sentiment_score", 0.0),
                "quick_replies": self.agent._quick_replies(intent),
                "need_transfer": False,
                "tool_calls": state.get("tool_calls") or [],
                "citations": state.get("citations") or [],
                "pending_approval": state.get("pending_approval"),
                "evidence_status": state.get("evidence_status"),
                "run_steps": state.get("run_steps") or [],
                "agent_mode": AgentMode.MULTI_STEP.value,
                "thread_id": self.thread_id,
                "interrupt": payload,
            }
        return dict(state)

    def _fallback_result(self, intent_data: Any) -> dict[str, Any]:
        intent = (
            IntentResult(**intent_data)
            if isinstance(intent_data, dict) and intent_data
            else _fallback_intent()
        )
        return {
            "response": self.agent.MULTI_STEP_FALLBACK_TEXT,
            "intent": intent.model_dump(),
            "sentiment": "neutral",
            "sentiment_score": 0.0,
            "quick_replies": self.agent._quick_replies(intent),
            "need_transfer": False,
            "tool_calls": [],
            "citations": [],
            "pending_approval": None,
            "evidence_status": None,
            "run_steps": [],
            "agent_mode": AgentMode.MULTI_STEP.value,
            "thread_id": self.thread_id,
            "interrupt": None,
        }


def _fallback_intent() -> IntentResult:
    return IntentResult(
        intent_code="fallback",
        intent_name="其他",
        confidence=0.0,
        entities=[],
        handler_type="llm",
        priority=0,
    )


def _sentiment(value: str):
    from app.services.sentiment_service import SentimentType

    try:
        return SentimentType(value)
    except ValueError:
        return SentimentType.NEUTRAL

"""确定性路由图:coref → intent → 分支 → finalize。

设计原则:
- 只做路由与编排,具体 RAG/工具/审批仍复用现有服务;
- 任何异常由 ``CustomerServiceAgent.chat`` 回退到原单步链路;
- 不在这里执行写操作;售后申请仍走审批服务。
"""
from __future__ import annotations

import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.core.observability import tag_current_trace
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


class GraphOrchestrator:
    """把一次请求按确定性节点走完;节点内部复用 CustomerServiceAgent 的服务。"""

    def __init__(self, agent: Any) -> None:
        self.agent = agent

    async def run(self, user_message: str) -> dict[str, Any]:
        graph = self._build_graph()
        return await graph.ainvoke(
            {
                "user_message": user_message,
                "history": self.agent.get_history(6),
                "run_steps": [],
                "citations": [],
                "tool_calls": [],
                "need_transfer": False,
                "agent_mode": AgentMode.SINGLE_STEP.value,
            }
        )

    # ---------------- 节点 ----------------
    async def _preprocess(self, state: OrchestratorState) -> dict[str, Any]:
        return {"user_message": self.agent._preprocess(state["user_message"])}

    async def _memory_context(
        self, state: OrchestratorState
    ) -> dict[str, Any]:
        history = [
            item
            for item in (state.get("history") or [])
            if item.get("role") in ("user", "assistant")
        ]
        return {"history": history[-6:]}

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
            message, self.agent.user_id
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
            return "main_agent"
        if code in ("greeting", "chitchat"):
            return "script"
        return "llm"

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

    async def _main_agent(self, state: OrchestratorState) -> dict[str, Any]:
        intent = IntentResult(**state["intent"])
        message = state["resolved_message"]
        skill = state.get("skill_text", "")
        steps = list(state.get("run_steps") or [])
        tool_calls: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        pending: dict[str, Any] | None = None
        response: str | None = None
        agent_mode = AgentMode.SINGLE_STEP
        thread_id: str | None = None
        interrupt: dict[str, Any] | None = None

        if self.agent._should_try_multi_step(intent):
            if self.agent.multi_step_agent is None:
                agent_mode = AgentMode.SINGLE_STEP_FALLBACK
            else:
                try:
                    multi = await self.agent.multi_step_agent.run(
                        user_message=message,
                        history=state.get("history") or [],
                        db=self.agent.db,
                        user_id=self.agent.user_id,
                        session_id=self.agent.session_id,
                        skill=skill,
                        thread_id=self.agent.thread_id,
                    )
                except Exception as exc:  # noqa: BLE001 - 回退是预期路径
                    logger.warning(
                        "图编排器:多步 Agent 失败,回退单步: {}", exc
                    )
                    agent_mode = AgentMode.SINGLE_STEP_FALLBACK
                else:
                    response = multi.response
                    tool_calls = list(multi.tool_calls)
                    citations = list(multi.citations)
                    pending = multi.pending_approval
                    steps = list(multi.steps)
                    agent_mode = AgentMode.MULTI_STEP
                    thread_id = multi.thread_id
                    interrupt = multi.interrupt

        if response is None:
            response, tool_calls, pending, step = await self.agent._handle_with_tools(
                intent, message, skill
            )
            if step is not None:
                steps.append(step)

        return {
            "response": response,
            "tool_calls": tool_calls,
            "citations": citations,
            "pending_approval": pending,
            "run_steps": steps,
            "need_transfer": any(
                call.get("tool") == "transfer_human" and call.get("success")
                for call in tool_calls
            ),
            "agent_mode": agent_mode.value,
            "thread_id": thread_id,
            "interrupt": interrupt,
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
        response = self.agent._add_sentiment_prefix(
            state.get("response") or "抱歉,请稍后再试。",
            _sentiment(state.get("sentiment", "neutral")),
        )
        self.agent.conversation_history.extend(
            [
                {"role": "user", "content": state["user_message"]},
                {"role": "assistant", "content": response},
            ]
        )
        return {
            "response": response,
            "intent": intent.model_dump(),
            "sentiment": state.get("sentiment", "neutral"),
            "sentiment_score": state.get("sentiment_score", 0.0),
            "quick_replies": self.agent._quick_replies(intent),
            "need_transfer": bool(state.get("need_transfer")),
            "tool_calls": state.get("tool_calls") or [],
            "citations": state.get("citations") or [],
            "pending_approval": state.get("pending_approval"),
            "evidence_status": state.get("evidence_status"),
            "run_steps": state.get("run_steps") or [],
            "agent_mode": state.get("agent_mode", AgentMode.SINGLE_STEP.value),
            "thread_id": state.get("thread_id"),
            "interrupt": state.get("interrupt"),
        }

    # ---------------- 图 ----------------
    def _build_graph(self) -> Any:
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
        builder.add_node("llm", self._llm)
        builder.add_node("finalize", self._finalize)

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
                "tool": "main_agent",
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
        for node in (
            "script",
            "transfer",
            "generate_answer",
            "main_agent",
            "llm",
        ):
            builder.add_edge(node, "finalize")
        builder.add_edge("finalize", END)
        return builder.compile()

    @staticmethod
    def _after_evidence(state: OrchestratorState) -> str:
        return "generate_answer" if state.get("rag_ready") else "finalize"


def _sentiment(value: str):
    from app.services.sentiment_service import SentimentType

    try:
        return SentimentType(value)
    except ValueError:
        return SentimentType.NEUTRAL

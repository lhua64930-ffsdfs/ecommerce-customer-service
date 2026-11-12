"""电商客服 Agent:情感 + 意图 + 工具/RAG 的完整决策链。"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.graph.multi_step_agent import MultiStepAgent, MultiStepError
from app.agents.prompts.system_prompt import get_system_prompt
from app.agents.tools.factory import build_default_tools
from app.agents.tools.registry import permission_for
from app.core.config import settings
from app.core.observability import tag_current_trace, trace_scope
from app.schemas.chat import AgentMode
from app.schemas.intent import IntentResult
from app.services.answer_guard import repair_hint, unsupported_entities
from app.services.coref_service import CorefService
from app.services.evidence import evidence_snapshot
from app.services.intent_service import IntentService
from app.services.knowledge_pool import record_low_confidence
from app.services.llm_service import LLMError, LLMService
from app.services.rag_service import RAGService
from app.services.selfcheck import check_sufficient
from app.services.sentiment_service import SentimentService, SentimentType
from app.services.skill_service import SkillService
from app.utils.logger import logger


class CustomerServiceAgent(BaseAgent):
    """售后智答 Agent。"""

    # 简单敏感词过滤(示例列表,可按业务扩充)
    SENSITIVE_WORDS = ("傻逼", "操你", "滚蛋", "fuck", "shit")

    # 证据不足时的固定兜底话术(零模型,避免编造政策)
    RAG_FALLBACK_TEXT = (
        "抱歉,我暂时没有找到足够可靠的依据来回答这个问题。"
        "您可以换个说法,或回复「转人工」由客服进一步核实。"
    )

    # 多步图失败/超步/空结果时的强停兜底(不再回退单步 Agent)
    MULTI_STEP_FALLBACK_TEXT = (
        "抱歉,这次自动处理没有完成。"
        "您可以换一种说法,或回复「转人工」由客服进一步处理。"
    )

    # 订单查询与售后写操作接入多步图,支持「查订单 → 判断状态 → 取消/退货」。
    # 其余意图(商品、促销等)仍走单步 Agent,保持链路简单。
    MULTI_STEP_INTENTS = frozenset(
        {"order_query", "cancel_order", "refund_request", "order_modify"}
    )

    def __init__(
        self,
        session_id: str,
        user_id: int | None = None,
        db: AsyncSession | None = None,
        history: list[dict[str, str]] | None = None,
        multi_step_agent: MultiStepAgent | None = None,
        thread_id: str | None = None,
    ) -> None:
        super().__init__(session_id, user_id)
        self.db = db
        self.thread_id = thread_id
        self.intent_service = IntentService()
        self.sentiment_service = SentimentService()
        self.coref_service = CorefService()
        self.rag_service = RAGService()
        self.llm_service = LLMService()
        self.skill_service = SkillService()
        self.tools = build_default_tools()
        self.multi_step_agent = multi_step_agent
        self.conversation_history = history or []

    async def process(self, input_text: str) -> dict[str, Any]:
        return await self.chat(input_text)

    async def chat(self, user_message: str) -> dict[str, Any]:
        """处理一条用户消息;启用 Langfuse 时整条链路归入同一 trace。"""
        with trace_scope(
            self.session_id,
            self.user_id,
            "after_sales_chat",
            tags=["chat", "customer_service"],
            input_data={"message": user_message[:500]},
        ):
            if settings.GRAPH_ORCHESTRATOR_ENABLED:
                try:
                    from app.agents.graph.orchestrator import GraphOrchestrator

                    return await GraphOrchestrator(self).run(user_message)
                except Exception as exc:  # noqa: BLE001 - 图整体异常时保留旧链路兼容兜底
                    logger.warning(
                        "确定性路由图整体异常,使用旧链路兼容兜底(非多步 Agent fallback): {}",
                        exc,
                    )
            return await self._chat_impl(user_message)

    async def resume(
        self, thread_id: str, resume_value: Any
    ) -> dict[str, Any]:
        """继续一个因订单选择而暂停的多步图。"""
        if self.multi_step_agent is None:
            raise RuntimeError("多步 Agent 不可用,无法 resume")
        with trace_scope(
            self.session_id,
            self.user_id,
            "after_sales_resume",
            tags=["chat", "resume"],
            input_data={"thread_id": thread_id, "resume": resume_value},
        ):
            if settings.GRAPH_ORCHESTRATOR_ENABLED:
                from app.agents.graph.orchestrator import GraphOrchestrator

                return await GraphOrchestrator(self).resume(
                    thread_id, resume_value
                )
            result = await self.multi_step_agent.resume(
                thread_id, resume_value, db=self.db
            )
        return {
            "response": result.response,
            "tool_calls": list(result.tool_calls),
            "citations": list(result.citations),
            "pending_approval": result.pending_approval,
            "run_steps": list(result.steps),
            "agent_mode": AgentMode.MULTI_STEP.value,
            "thread_id": result.thread_id,
            "interrupt": result.interrupt,
            "need_transfer": any(
                call.get("tool") == "transfer_human" and call.get("success")
                for call in result.tool_calls
            ),
            "evidence_status": None,
        }

    async def _chat_impl(self, user_message: str) -> dict[str, Any]:
        """处理一条用户消息,返回结构化结果。"""
        message = self._preprocess(user_message)
        run_steps: list[dict[str, Any]] = []

        # 指代消解:把「那物流呢」「帮我退了」补成完整问法
        coref_started = time.perf_counter()
        resolved_message = await self.coref_service.resolve(
            message, self.get_history(6)
        )
        if resolved_message != message:
            run_steps.append(
                {
                    "step_type": "model",
                    "name": "coref_resolve",
                    "input": {"query": message[:200]},
                    "output": {"resolved": resolved_message[:300]},
                    "success": True,
                    "latency_ms": int((time.perf_counter() - coref_started) * 1000),
                }
            )

        sentiment, sentiment_score = await self.sentiment_service.analyze(message)
        intent = await self.intent_service.recognize(
            resolved_message,
            self.user_id,
            context=self.context_text(),
        )
        tag_current_trace(
            metadata={
                "intent": intent.intent_code,
                "intent_confidence": f"{intent.confidence:.2f}",
            },
            tags=[f"intent:{intent.intent_code}"],
        )
        if settings.MCP_ENABLED and intent.handler_type in ("tool", "transfer"):
            await self._refresh_mcp_tools()
        skill_text = self.skill_service.get(intent.intent_code)

        tool_calls: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        pending_approval: dict[str, Any] | None = None
        evidence_status: str | None = None
        need_transfer = False
        agent_mode = AgentMode.SINGLE_STEP
        response: str | None = None
        thread_id: str | None = None
        interrupt: dict[str, Any] | None = None

        # 订单相关意图优先走 LangGraph 多步图。
        # 无模型时保留单步离线模式;有模型但失败/超步/空结果时只做强停兜底,
        # 不再回退单步 Agent(MewHelp 风格)。
        if self._should_try_multi_step(intent):
            if self.multi_step_agent is None:
                # 离线演示模式:没有 ChatModel 时才走单步工具路径,不是失败 fallback
                agent_mode = AgentMode.SINGLE_STEP
            else:
                try:
                    multi_result = await self.multi_step_agent.run(
                        user_message=resolved_message,
                        history=self.get_history(6),
                        db=self.db,
                        user_id=self.user_id,
                        session_id=self.session_id,
                        skill=skill_text,
                        thread_id=self.thread_id,
                    )
                except MultiStepError as exc:
                    logger.warning("多步 Agent 强停,返回兜底话术: {}", exc)
                    response = self.MULTI_STEP_FALLBACK_TEXT
                    agent_mode = AgentMode.MULTI_STEP
                except Exception as exc:  # noqa: BLE001 - 图异常也强停,不再回退单步
                    logger.exception("多步 Agent 异常,返回兜底话术: {}", exc)
                    response = self.MULTI_STEP_FALLBACK_TEXT
                    agent_mode = AgentMode.MULTI_STEP
                else:
                    response = multi_result.response
                    tool_calls = list(multi_result.tool_calls)
                    citations = list(multi_result.citations)
                    pending_approval = multi_result.pending_approval
                    run_steps = list(multi_result.steps)
                    agent_mode = AgentMode.MULTI_STEP
                    thread_id = multi_result.thread_id
                    interrupt = multi_result.interrupt
                    need_transfer = any(
                        call.get("tool") == "transfer_human"
                        and call.get("success")
                        for call in tool_calls
                    )

        if response is None:
            try:
                if intent.handler_type == "transfer":
                    started = time.perf_counter()
                    result = await self.tools["transfer_human"].execute(
                        self._tool_params(resolved_message)
                    )
                    response = result.get("response", "已为您转接人工客服")
                    need_transfer = bool(result.get("success"))
                    transfer_record = {
                        "tool": "transfer_human",
                        "success": result.get("success", False),
                    }
                    if result.get("transport"):
                        transfer_record["transport"] = result["transport"]
                    tool_calls.append(transfer_record)
                    transfer_output = {
                        "success": bool(result.get("success")),
                        "response": str(result.get("response", ""))[:300],
                    }
                    if result.get("transport"):
                        transfer_output["transport"] = result["transport"]
                    run_steps.append(
                        {
                            "step_type": "tool",
                            "name": "transfer_human",
                            "input": {"reason": resolved_message[:100]},
                            "output": transfer_output,
                            "success": bool(result.get("success")),
                            "latency_ms": int((time.perf_counter() - started) * 1000),
                        }
                    )
                elif intent.handler_type == "tool":
                    response, tool_calls, pending_approval, step = (
                        await self._handle_with_tools(
                            intent, resolved_message, skill_text
                        )
                    )
                    if step is not None:
                        run_steps.append(step)
                elif intent.handler_type == "rag":
                    started = time.perf_counter()
                    response, citations, evidence_status = await self._handle_with_rag(
                        resolved_message, skill_text
                    )
                    run_steps.append(
                        {
                            "step_type": "tool",
                            "name": "rag_retrieve",
                            "input": {"query": resolved_message[:200]},
                            "output": {
                                "citations": len(citations),
                                "evidence_status": evidence_status,
                            },
                            "success": evidence_status == "sufficient",
                            "tokens": (
                                max(1, (len(resolved_message) + len(response)) // 4)
                                if evidence_status == "sufficient"
                                else 0
                            ),
                            "latency_ms": int((time.perf_counter() - started) * 1000),
                        }
                    )
                else:
                    started = time.perf_counter()
                    if intent.intent_code in ("greeting", "chitchat"):
                        response = self._script_reply(intent)
                        step_name = "script_reply"
                    else:
                        response = await self._handle_with_llm(
                            resolved_message, skill_text
                        )
                        step_name = "llm_reply"
                    run_steps.append(
                        {
                            "step_type": "model",
                            "name": step_name,
                            "input": {"message": resolved_message[:200]},
                            "output": {"response": response[:300]},
                            "success": True,
                            "tokens": (
                                max(1, (len(resolved_message) + len(response)) // 4)
                                if step_name == "llm_reply"
                                else 0
                            ),
                            "latency_ms": int((time.perf_counter() - started) * 1000),
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - 单条消息失败不能拖垮接口
                logger.exception("Agent 处理消息失败: {}", exc)
                response = "抱歉,系统繁忙,请稍后再试,或回复「转人工」联系客服。"
                run_steps.append(
                    {
                        "step_type": "model",
                        "name": "agent_error",
                        "input": {},
                        "output": {"error": str(exc)[:300]},
                        "success": False,
                        "latency_ms": 0,
                    }
                )

        response = self._add_sentiment_prefix(response, sentiment)

        self.conversation_history.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": response},
            ]
        )

        return {
            "response": response,
            "intent": intent.model_dump(),
            "sentiment": sentiment.value,
            "sentiment_score": sentiment_score,
            "quick_replies": self._quick_replies(intent),
            "need_transfer": need_transfer,
            "tool_calls": tool_calls,
            "citations": citations,
            "pending_approval": pending_approval,
            "evidence_status": evidence_status,
            "run_steps": run_steps,
            "agent_mode": agent_mode.value,
            "thread_id": thread_id,
            "interrupt": interrupt,
        }

    async def stream_chat(self, user_message: str) -> AsyncIterator[dict[str, Any]]:
        """SSE 事件流;启用 Langfuse 时流式链路也归入同一 trace。"""
        with trace_scope(
            self.session_id,
            self.user_id,
            "after_sales_stream_chat",
            tags=["chat", "stream", "customer_service"],
            input_data={"message": user_message[:500]},
        ):
            async for event in self._stream_chat_impl(user_message):
                yield event

    async def _stream_chat_impl(
        self, user_message: str
    ) -> AsyncIterator[dict[str, Any]]:
        """SSE 事件流:RAG 路径逐 token 输出,工具/转人工路径输出事件 + 完整回复。"""
        message = self._preprocess(user_message)
        run_steps: list[dict[str, Any]] = []

        coref_started = time.perf_counter()
        resolved_message = await self.coref_service.resolve(
            message, self.get_history(6)
        )
        if resolved_message != message:
            run_steps.append(
                {
                    "step_type": "model",
                    "name": "coref_resolve",
                    "input": {"query": message[:200]},
                    "output": {"resolved": resolved_message[:300]},
                    "success": True,
                    "latency_ms": int((time.perf_counter() - coref_started) * 1000),
                }
            )

        sentiment, sentiment_score = await self.sentiment_service.analyze(message)
        intent = await self.intent_service.recognize(
            resolved_message,
            self.user_id,
            context=self.context_text(),
        )
        tag_current_trace(
            metadata={
                "intent": intent.intent_code,
                "intent_confidence": f"{intent.confidence:.2f}",
            },
            tags=[f"intent:{intent.intent_code}"],
        )
        yield {
            "event": "meta",
            "intent": intent.model_dump(),
            "sentiment": sentiment.value,
            "sentiment_score": sentiment_score,
        }

        skill_text = self.skill_service.get(intent.intent_code)
        if intent.handler_type == "rag":
            started = time.perf_counter()
            result = await self.rag_service.retrieve_with_evidence(
                resolved_message, top_k=3
            )
            evidence_status = "sufficient"
            citations = result.citations
            response = ""
            prefix = self._sentiment_prefix(sentiment)

            if not result.hits or not result.evidence.strong:
                evidence_status = "insufficient"
                await record_low_confidence(
                    self.db,
                    self.session_id,
                    resolved_message,
                    "retrieval_low_conf",
                    f"evidence={result.evidence.score} mode={result.mode}",
                    evidence_snapshot(result.hits),
                )
                response = f"{prefix}{self.RAG_FALLBACK_TEXT}"
                yield {"event": "delta", "text": response}
            else:
                check = {"useful": True, "reason": "self_check disabled"}
                if settings.RAG_SELF_CHECK:
                    check = await check_sufficient(
                        resolved_message,
                        [
                            f"{hit.get('question', '')}: {hit.get('answer', '')}"
                            for hit in result.hits
                        ],
                        llm=self.llm_service,
                    )
                if not check["useful"]:
                    evidence_status = "insufficient"
                    await record_low_confidence(
                        self.db,
                        self.session_id,
                        resolved_message,
                        "self_check",
                        check.get("reason") or "self_check 未通过",
                        evidence_snapshot(result.hits),
                    )
                    response = f"{prefix}{self.RAG_FALLBACK_TEXT}"
                    yield {"event": "delta", "text": response}
                else:
                    if prefix:
                        response += prefix
                        yield {"event": "delta", "text": prefix}
                    yield {"event": "citations", "items": citations}
                    prompt = self.rag_service.build_prompt(
                        resolved_message, result.context, skill=skill_text
                    )
                    generate_started = time.perf_counter()
                    try:
                        async for chunk in self.llm_service.stream_chat(
                            [{"role": "user", "content": prompt}]
                        ):
                            response += chunk
                            yield {"event": "delta", "text": chunk}
                    except Exception as exc:  # noqa: BLE001 - 流式中断时退回知识原文
                        logger.warning("流式生成失败,退回知识原文: {}", exc)
                        response = f"根据知识库:\n\n{result.context}"
                        yield {"event": "delta", "text": response}
                    run_steps.append(
                        {
                            "step_type": "model",
                            "name": "rag_generate",
                            "input": {"query": resolved_message[:200]},
                            "output": {"chars": len(response)},
                            "success": True,
                            "latency_ms": int(
                                (time.perf_counter() - generate_started) * 1000
                            ),
                        }
                    )

            # 流式回答的机械校验:已输出的文本不回滚,但明确提示并落池
            evidence_text = "\n".join(
                f"{hit.get('question', '')} {hit.get('answer', '')}"
                for hit in result.hits
            )
            if response:
                bad = unsupported_entities(response, evidence_text)
                if bad:
                    await record_low_confidence(
                        self.db,
                        self.session_id,
                        resolved_message,
                        "answer_guard",
                        "unsupported: " + "、".join(bad),
                        evidence_snapshot(result.hits),
                    )
                    warning = "\n\n⚠️ 以上内容包含知识库未覆盖的信息,建议转人工确认。"
                    response += warning
                    yield {"event": "delta", "text": warning}
                    evidence_status = "insufficient"

            run_steps.append(
                {
                    "step_type": "tool",
                    "name": "rag_retrieve",
                    "input": {"query": resolved_message[:200]},
                    "output": {
                        "citations": len(citations),
                        "evidence_status": evidence_status,
                    },
                    "success": evidence_status == "sufficient",
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
            )
            quick_replies = self._quick_replies(intent)
            yield {
                "event": "actions",
                "quick_replies": quick_replies,
                "pending_approval": None,
            }
            yield {
                "event": "done",
                "result": {
                    "response": response,
                    "intent": intent.model_dump(),
                    "sentiment": sentiment.value,
                    "sentiment_score": sentiment_score,
                    "quick_replies": quick_replies,
                    "need_transfer": False,
                    "tool_calls": [],
                    "citations": citations,
                    "pending_approval": None,
                    "evidence_status": evidence_status,
                    "run_steps": run_steps,
                    "agent_mode": AgentMode.SINGLE_STEP.value,
                },
            }
            return

        # 工具/转人工/多步路径:复用非流式结果(含确定性图),按事件输出
        result = await self.chat(user_message)
        for call in result.get("tool_calls", []):
            yield {
                "event": "tool",
                "name": call.get("tool"),
                "success": call.get("success"),
            }
        response = result["response"]
        yield {"event": "delta", "text": response}
        if result.get("citations"):
            yield {"event": "citations", "items": result["citations"]}
        yield {
            "event": "actions",
            "quick_replies": result.get("quick_replies", []),
            "pending_approval": result.get("pending_approval"),
        }
        yield {"event": "done", "result": result}

    def _should_try_multi_step(self, intent: IntentResult) -> bool:
        return (
            intent.handler_type == "tool"
            and intent.intent_code in self.MULTI_STEP_INTENTS
        )

    def _tool_params(self, message: str, **extra: Any) -> dict[str, Any]:
        """单步工具调用的公共参数,避免在每个分支重复拼装。"""
        return {
            "db": self.db,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "user_message": message,
            **extra,
        }

    async def _refresh_mcp_tools(self) -> None:
        """按 MCP Server 动态清单刷新工具 Schema(带 TTL 缓存)。"""
        if not settings.MCP_ENABLED:
            return
        from app.agents.mcp.client import refresh_mcp_tools

        try:
            # 用原始本地工具做回退实现,避免在代理外面再套一层代理
            local_tools = build_default_tools(use_mcp=False)
            tools = await refresh_mcp_tools(local_tools)
        except Exception as exc:  # noqa: BLE001 - 刷新失败沿用当前工具
            logger.warning("MCP 工具刷新失败,继续使用现有工具: {}", exc)
            return

        self.tools = tools
        if self.multi_step_agent is not None:
            # 图内默认只暴露只读 + 申请 + 转人工;
            # create_ticket 仅在 checkpointer 存在时由 confirm_ticket gate 把关
            allow_ticket = self.multi_step_agent.checkpointer is not None
            self.multi_step_agent.tools = {
                name: tool
                for name, tool in tools.items()
                if permission_for(name) != "write"
                or (allow_ticket and name == "create_ticket")
            }

    # ---------------- 路由处理 ----------------
    async def _handle_with_tools(
        self, intent: IntentResult, message: str, skill: str = ""
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
        mapping: dict[str, tuple[str, dict[str, Any]]] = {
            "order_query": ("query_order", {}),
            # 售后写操作先走申请:模型/单步 Agent 都不直接改订单
            "cancel_order": ("propose_after_sales_action", {"action": "cancel"}),
            "refund_request": ("propose_after_sales_action", {"action": "refund"}),
            "order_modify": (
                "create_ticket",
                {"type": "consult", "title": "订单修改申请", "content": message},
            ),
        }
        tool_name, extra = mapping.get(intent.intent_code, ("", {}))
        if not tool_name:
            started = time.perf_counter()
            response = await self._handle_with_llm(message, skill)
            return (
                response,
                [],
                None,
                {
                    "step_type": "model",
                    "name": "llm_reply",
                    "input": {"message": message[:200]},
                    "output": {"response": response[:300]},
                    "success": True,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                },
            )

        order_no = next(
            (entity.value for entity in intent.entities if entity.type == "order_no"), None
        )
        started = time.perf_counter()
        result = await self.tools[tool_name].execute(
            self._tool_params(message, order_no=order_no, **extra)
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        success = bool(result.get("success"))
        pending = result.get("proposal")
        step_output = {
            "success": success,
            "decision": result.get("decision"),
            "error_code": result.get("error_code"),
            "response": str(result.get("response", ""))[:300],
        }
        call_record = {"tool": tool_name, "success": success}
        if result.get("transport"):
            step_output["transport"] = result["transport"]
            call_record["transport"] = result["transport"]
        step = {
            "step_type": "tool",
            "name": tool_name,
            "input": {**extra, **({"order_no": order_no} if order_no else {})},
            "output": step_output,
            "success": success,
            "latency_ms": latency_ms,
        }
        logger.info("工具调用: {} success={}", tool_name, result.get("success"))
        return (
            result.get("response", "处理完成"),
            [call_record],
            pending,
            step,
        )

    async def _handle_with_rag(
        self, message: str, skill: str = ""
    ) -> tuple[str, list[dict[str, Any]], str]:
        result = await self.rag_service.retrieve_with_evidence(message, top_k=3)

        # 证据闸:检索为空或置信度低,不生成,落低置信度池等人工补知识
        if not result.hits or not result.evidence.strong:
            await record_low_confidence(
                self.db,
                self.session_id,
                message,
                "retrieval_low_conf",
                f"evidence={result.evidence.score} mode={result.mode}",
                evidence_snapshot(result.hits),
            )
            return self.RAG_FALLBACK_TEXT, [], "insufficient"

        # 生成前自检:LLM 判断证据是否足以回答;失败/不足按不足处理
        if settings.RAG_SELF_CHECK:
            check = await check_sufficient(
                message,
                [
                    f"{hit.get('question', '')}: {hit.get('answer', '')}"
                    for hit in result.hits
                ],
                llm=self.llm_service,
            )
            if not check["useful"]:
                await record_low_confidence(
                    self.db,
                    self.session_id,
                    message,
                    "self_check",
                    check.get("reason") or "self_check 未通过",
                    evidence_snapshot(result.hits),
                )
                return self.RAG_FALLBACK_TEXT, [], "insufficient"

        evidence_text = "\n".join(
            f"{hit.get('question', '')} {hit.get('answer', '')}"
            for hit in result.hits
        )
        try:
            answer = await self.rag_service.generate(
                message, result.context, skill=skill
            )
            bad = unsupported_entities(answer, evidence_text)
            if bad:
                answer = await self.rag_service.generate(
                    f"{message}\n\n{repair_hint(bad)}",
                    result.context,
                    skill=skill,
                )
                bad = unsupported_entities(answer, evidence_text)
            if bad:
                await record_low_confidence(
                    self.db,
                    self.session_id,
                    message,
                    "answer_guard",
                    "unsupported: " + "、".join(bad),
                    evidence_snapshot(result.hits),
                )
                return self.RAG_FALLBACK_TEXT, [], "insufficient"
            return answer, result.citations, "sufficient"
        except LLMError:
            # LLM 不可用时直接返回检索到的知识,保证有答案
            return f"根据知识库:\n\n{result.context}", result.citations, "sufficient"

    async def _handle_with_llm(self, message: str, skill: str = "") -> str:
        messages = [{"role": "system", "content": get_system_prompt(skill)}]
        messages.extend(
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in self.get_history(6)
        )
        messages.append({"role": "user", "content": message})
        try:
            return await self.llm_service.chat(messages)
        except LLMError:
            return "抱歉,我暂时无法回答这个问题。您可以回复「转人工」联系客服。"

    # ---------------- 预处理 / 后处理 ----------------
    def _preprocess(self, text: str) -> str:
        cleaned = " ".join((text or "").split())
        for word in self.SENSITIVE_WORDS:
            if word in cleaned.lower():
                logger.warning("检测到敏感词: {}", word)
                cleaned = cleaned.replace(word, "***")
        return cleaned.strip()

    @staticmethod
    def _sentiment_prefix(sentiment: SentimentType) -> str:
        if sentiment == SentimentType.NEGATIVE:
            return "😔 很抱歉给您带来不愉快的体验。\n\n"
        return ""

    @classmethod
    def _add_sentiment_prefix(cls, response: str, sentiment: SentimentType) -> str:
        if sentiment == SentimentType.NEGATIVE and "抱歉" not in response[:20]:
            return f"{cls._sentiment_prefix(sentiment)}{response}"
        return response

    @staticmethod
    def _script_reply(intent: IntentResult) -> str:
        """问候/闲聊固定话术:零模型,避免无意义调用。"""
        if intent.intent_code == "greeting":
            return (
                "您好!我是智能客服小e,很高兴为您服务~\n\n"
                "我可以帮您查订单、了解商品、处理退款退货等。请问有什么可以帮到您的?"
            )
        return "不客气~如果还有售后问题,随时告诉我;需要人工也可以回复「转人工」。"

    @staticmethod
    def _quick_replies(intent: IntentResult) -> list[str]:
        mapping = {
            "order_query": ["查看全部订单", "物流到哪了", "转人工"],
            "cancel_order": ["退款进度", "转人工"],
            "refund_request": ["退款多久到账", "退货流程", "转人工"],
            "product_inquiry": ["热门商品", "优惠活动", "转人工"],
            "promotion": ["查看优惠券", "会员权益"],
            "human_agent": ["继续咨询"],
            "complaint": ["转人工"],
        }
        return mapping.get(intent.intent_code, ["查订单", "商品咨询", "退款退货", "转人工"])

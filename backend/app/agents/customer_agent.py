"""电商客服 Agent:情感 + 意图 + 工具/RAG 的完整决策链。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.prompts.system_prompt import get_system_prompt
from app.agents.tools import (
    CreateTicketTool,
    QueryOrderTool,
    QueryProductTool,
    RefundTool,
    SearchKnowledgeTool,
    TransferHumanTool,
)
from app.schemas.intent import IntentResult
from app.services.intent_service import IntentService
from app.services.llm_service import LLMError, LLMService
from app.services.rag_service import RAGService
from app.services.sentiment_service import SentimentService, SentimentType
from app.utils.logger import logger


class CustomerServiceAgent(BaseAgent):
    """售后智答 Agent。"""

    # 简单敏感词过滤(示例列表,可按业务扩充)
    SENSITIVE_WORDS = ("傻逼", "操你", "滚蛋", "fuck", "shit")

    def __init__(
        self,
        session_id: str,
        user_id: int | None = None,
        db: AsyncSession | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(session_id, user_id)
        self.db = db
        self.intent_service = IntentService()
        self.sentiment_service = SentimentService()
        self.rag_service = RAGService()
        self.llm_service = LLMService()
        self.tools = self._init_tools()
        self.conversation_history = history or []

    def _init_tools(self) -> dict[str, Any]:
        return {
            "search_knowledge": SearchKnowledgeTool(),
            "query_order": QueryOrderTool(),
            "query_product": QueryProductTool(),
            "refund": RefundTool(),
            "transfer_human": TransferHumanTool(),
            "create_ticket": CreateTicketTool(),
        }

    async def process(self, input_text: str) -> dict[str, Any]:
        return await self.chat(input_text)

    async def chat(self, user_message: str) -> dict[str, Any]:
        """处理一条用户消息,返回结构化结果。"""
        message = self._preprocess(user_message)
        sentiment, sentiment_score = await self.sentiment_service.analyze(message)
        intent = await self.intent_service.recognize(message, self.user_id)

        tool_calls: list[dict[str, Any]] = []
        need_transfer = False

        try:
            if intent.handler_type == "transfer":
                result = await self.tools["transfer_human"].execute(
                    {
                        "db": self.db,
                        "session_id": self.session_id,
                        "user_id": self.user_id,
                        "user_message": message,
                    }
                )
                response = result.get("response", "已为您转接人工客服")
                need_transfer = bool(result.get("success"))
                tool_calls.append({"tool": "transfer_human", "success": result.get("success", False)})
            elif intent.handler_type == "tool":
                response, tool_calls = await self._handle_with_tools(intent, message)
            elif intent.handler_type == "rag":
                response = await self._handle_with_rag(message)
            else:
                response = await self._handle_with_llm(message)
        except Exception as exc:  # noqa: BLE001 - 单条消息失败不能拖垮接口
            logger.exception("Agent 处理消息失败: {}", exc)
            response = "抱歉,系统繁忙,请稍后再试,或回复「转人工」联系客服。"

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
        }

    # ---------------- 路由处理 ----------------
    async def _handle_with_tools(
        self, intent: IntentResult, message: str
    ) -> tuple[str, list[dict[str, Any]]]:
        mapping: dict[str, tuple[str, dict[str, Any]]] = {
            "order_query": ("query_order", {}),
            "cancel_order": ("refund", {"action": "cancel"}),
            "refund_request": ("refund", {"action": "refund"}),
            "order_modify": (
                "create_ticket",
                {"type": "consult", "title": "订单修改申请", "content": message},
            ),
        }
        tool_name, extra = mapping.get(intent.intent_code, ("", {}))
        if not tool_name:
            return await self._handle_with_llm(message), []

        order_no = next(
            (entity.value for entity in intent.entities if entity.type == "order_no"), None
        )
        params: dict[str, Any] = {
            "db": self.db,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "user_message": message,
            "order_no": order_no,
            **extra,
        }

        result = await self.tools[tool_name].execute(params)
        logger.info("工具调用: {} success={}", tool_name, result.get("success"))
        return result.get("response", "处理完成"), [
            {"tool": tool_name, "success": bool(result.get("success"))}
        ]

    async def _handle_with_rag(self, message: str) -> str:
        context = await self.rag_service.retrieve(message, top_k=3)
        if not context:
            return await self._handle_with_llm(message)
        try:
            return await self.rag_service.generate(message, context)
        except LLMError:
            # LLM 不可用时直接返回检索到的知识,保证有答案
            return f"根据知识库:\n\n{context}"

    async def _handle_with_llm(self, message: str) -> str:
        messages = [{"role": "system", "content": get_system_prompt()}]
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
    def _add_sentiment_prefix(response: str, sentiment: SentimentType) -> str:
        if sentiment == SentimentType.NEGATIVE and "抱歉" not in response[:20]:
            return f"😔 很抱歉给您带来不愉快的体验。\n\n{response}"
        return response

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

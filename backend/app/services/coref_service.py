"""指代消解:把「帮我退了」「那物流呢」这类追问补全成可检索/可路由的完整问法。

只在出现指代词或明显追问时触发,避免每条消息多一次 LLM 调用。
LLM 不可用时用规则兜底(补上最近出现的订单号)。
"""
from __future__ import annotations

import re

from app.services.llm_service import LLMError, LLMService
from app.utils.logger import logger

_ORDER_RE = re.compile(r"\b(?:ORDER|DD)[A-Za-z0-9]{8,20}\b", re.IGNORECASE)
_CONTEXT_CUES = (
    "它",
    "那",
    "这个",
    "那个",
    "刚才",
    "上面",
    "前面",
    "退了",
    "也要",
    "还要",
    "顺便",
)
# 纯社交短语不参与指代消解,否则短句会被补上历史订单号,误判成订单查询
_SOCIAL_RE = re.compile(
    r"^(谢谢|谢了|好的|好|收到|再见|晚安|早上好|你好|您好|哈哈|嗯|ok|OK)[。!！?？~～\s]*$",
    re.IGNORECASE,
)

COREF_PROMPT = """你是电商售后客服的指代消解模块。

根据最近对话,把用户当前这句话改写成不依赖上下文也能独立理解的完整问法。
规则:
- 补全「它/那个/这个/刚才那个」指代的订单号、商品或诉求;
- 保留用户原意,不要回答问题,不要编造订单号;
- 只输出改写后的一句话,不要解释。

最近对话:
{history}

当前用户消息:{query}
"""


class CorefService:
    def __init__(self, llm: LLMService | None = None) -> None:
        self.llm = llm or LLMService()

    @staticmethod
    def _last_order_no(history: list[dict[str, str]], query: str) -> str | None:
        for item in reversed(history):
            match = _ORDER_RE.search(str(item.get("content") or ""))
            if match:
                return match.group(0).upper()
        match = _ORDER_RE.search(query)
        return match.group(0).upper() if match else None

    @staticmethod
    def _needs_resolution(query: str, history: list[dict[str, str]]) -> bool:
        if not history:
            return False
        if _SOCIAL_RE.match(query.strip()):
            return False
        if any(cue in query for cue in _CONTEXT_CUES):
            return True
        return len(query) <= 5

    async def resolve(self, query: str, history: list[dict[str, str]]) -> str:
        query = (query or "").strip()
        if not query or not self._needs_resolution(query, history):
            return query

        order_no = self._last_order_no(history, query)
        if self.llm.is_mock:
            if order_no and order_no not in query.upper():
                return f"{query}(订单 {order_no})"
            return query

        lines = []
        for item in history[-6:]:
            role = "用户" if item.get("role") == "user" else "客服"
            lines.append(f"{role}:{item.get('content', '')}")
        prompt = COREF_PROMPT.format(
            history="\n".join(lines) or "(无)", query=query
        )

        try:
            resolved = (await self.llm.generate(prompt, temperature=0.0)).strip()
        except LLMError as exc:
            logger.warning("指代消解失败,使用原问题: {}", exc)
            resolved = ""

        if not resolved or len(resolved) > 500:
            if order_no and order_no not in query.upper():
                return f"{query}(订单 {order_no})"
            return query
        return resolved

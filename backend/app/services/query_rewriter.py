"""Query 扩写:把用户问法改写成 2-3 个适合知识库检索的问法。

只作用于检索,不改变最终回答;mock 模式或解析失败时原样返回。
"""
from __future__ import annotations

import json
import re

from app.services.llm_service import LLMError, LLMService
from app.utils.logger import logger

EXPAND_PROMPT = """你是电商售后知识库的检索助手。请把用户问题改写成 2 条更适合检索的问法。

要求:
- 保留订单/商品/政策等关键实体;
- 换用知识库里可能出现的表达(如「退款多久到账」「退货流程」);
- 不要回答问题,不要编造政策;
- 只返回 JSON:{{"queries": ["问法1", "问法2"]}}

用户问题:{query}
"""


def _parse(raw: str) -> list[str]:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    queries = data.get("queries")
    if not isinstance(queries, list):
        return []
    return [str(item).strip() for item in queries if str(item).strip()]


class QueryRewriter:
    def __init__(self, llm: LLMService | None = None) -> None:
        self.llm = llm or LLMService()

    async def expand(self, query: str, max_queries: int = 3) -> list[str]:
        if self.llm.is_mock:
            return [query]
        try:
            raw = await self.llm.generate(
                EXPAND_PROMPT.format(query=query),
                temperature=0.2,
                json_mode=True,
            )
        except LLMError as exc:
            logger.warning("Query 扩写失败,使用原问题: {}", exc)
            return [query]

        expanded = _parse(raw)
        if not expanded:
            return [query]

        result: list[str] = [query]
        for item in expanded:
            if item and item not in result:
                result.append(item)
        return result[:max_queries]

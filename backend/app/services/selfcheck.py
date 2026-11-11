"""生成前证据充分性自检:LLM 判断证据是否足以回答。

失败或无法解析时按「证据不足」处理——宁可兜底/转人工,也不要生成一段
证据撑不住的政策回答。
"""
from __future__ import annotations

import json
import re

from app.services.llm_service import LLMError, LLMService
from app.utils.logger import logger

SELF_CHECK_PROMPT = """你是电商售后客服的质检员。请判断下面的知识库证据是否足以回答用户问题。

判断标准:
- 证据必须直接支持回答,而不是仅仅主题相关;
- 证据缺少关键条件(时间、金额、状态、地区、具体支付方式/商品/对象)时视为不足;
- 只覆盖同类主题但没有明确提到用户问的具体对象或方式,视为不足。
  例如用户问「支持比特币吗」,证据只列出支付宝/微信/银行卡,则视为不足;
- 只能依据给出的证据,不要用你自己的常识补全。

只返回 JSON:{{"useful": true 或 false, "reason": "一句话依据"}}

用户问题:{query}

证据:
{evidence}
"""


def _parse(raw: str) -> dict | None:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def check_sufficient(
    query: str, evidence_texts: list[str], llm: LLMService | None = None
) -> dict:
    """返回 {useful: bool, reason: str};模型不可用时按不足处理。"""
    llm = llm or LLMService()
    if llm.is_mock:
        return {"useful": True, "reason": "mock 模式跳过自检"}

    evidence = "\n".join(
        f"[{index + 1}] {text}" for index, text in enumerate(evidence_texts)
    ) or "(无证据)"
    prompt = SELF_CHECK_PROMPT.format(query=query, evidence=evidence)

    try:
        raw = await llm.generate(prompt, temperature=0.0, json_mode=True)
    except LLMError as exc:
        logger.warning("证据自检失败,按证据不足处理: {}", exc)
        return {"useful": False, "reason": "证据自检失败"}

    data = _parse(raw)
    if data is None:
        logger.warning("证据自检返回无法解析: {}", raw[:120])
        return {"useful": False, "reason": "证据自检返回无法解析"}

    return {
        "useful": bool(data.get("useful")),
        "reason": str(data.get("reason") or ""),
    }

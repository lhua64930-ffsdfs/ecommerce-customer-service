"""回答机械校验:答案里的订单号/金额/日期必须逐字来自本轮证据。

这类实体是封闭集合,正则就能判,不需要再调一次 LLM 裁判:
- 订单号:ORDER/DD + 字母数字;
- 金额:¥/￥ + 数字;
- 完整日期:YYYY-MM-DD / YYYY年M月D日。

证据里没有、答案里出现的实体,视为无依据,交给上层重写或兜底。
"""
from __future__ import annotations

import re

ORDER_RE = re.compile(r"\b(?:ORDER|DD)[A-Za-z0-9]{8,20}\b", re.IGNORECASE)
MONEY_RE = re.compile(r"[¥￥]\s*\d+(?:\.\d{1,2})?")
DATE_RE = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?")
ENTITY_PATTERNS = (ORDER_RE, MONEY_RE, DATE_RE)


def extract_entities(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for pattern in ENTITY_PATTERNS:
        for match in pattern.findall(text or ""):
            seen.setdefault(match, None)
    return list(seen)


def unsupported_entities(answer: str, evidence: str) -> list[str]:
    allowed = set(extract_entities(evidence))
    return [item for item in extract_entities(answer) if item not in allowed]


def repair_hint(bad: list[str]) -> str:
    return (
        "上一版回答里这些信息在知识库证据中找不到:"
        + "、".join(bad)
        + "。请重写回答:订单号、金额、日期必须逐字来自证据,证据里没有的不要写;"
        "拿不准就省略这些信息。"
    )

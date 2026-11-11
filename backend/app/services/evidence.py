"""生成前证据置信度:用检索/重排结果判断「这批证据够不够回答」。

四个信号全部来自检索结果,零额外模型调用:
- top1_score:最相关证据的强度;
- valid_count:强证据条数(0.3 以上,3 条封顶);
- margin:Top1 与 Top2 的分差(证据聚焦度);
- key_clause_hit:Top3 是否命中售后关键条款词。

低置信度不应硬生成,交给上层拒答/转人工并落低置信度池。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_SCORE_FLOOR = 0.3
VALID_COUNT_CAP = 3
WEIGHT_TOP1 = 0.5
WEIGHT_VALID_COUNT = 0.2
WEIGHT_MARGIN = 0.2
WEIGHT_KEY_CLAUSE = 0.1

# 与售后知识库主题对齐;用于判断证据是否命中「关键条款」而非泛泛相关
KEY_TERMS = (
    "退款",
    "退货",
    "退换",
    "运费",
    "保修",
    "质保",
    "发票",
    "优惠券",
    "会员",
    "配送",
    "物流",
    "支付",
    "客服",
    "订单",
    "地址",
)


@dataclass(frozen=True)
class EvidenceConfidence:
    score: float
    signals: dict[str, Any]

    @property
    def strong(self) -> bool:
        from app.core.config import settings

        return self.score >= settings.RAG_EVIDENCE_THRESHOLD


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_evidence_confidence(hits: list[dict[str, Any]]) -> EvidenceConfidence:
    if not hits:
        return EvidenceConfidence(
            0.0,
            {
                "top1_score": 0.0,
                "valid_count": 0,
                "margin": 0.0,
                "key_clause_hit": False,
            },
        )

    scores = [
        _clip(float(item.get("rerank_score") or item.get("score") or 0.0))
        for item in hits
    ]
    top1 = scores[0]
    margin = top1 - scores[1] if len(scores) > 1 else top1
    valid_count = sum(1 for score in scores if score >= VALID_SCORE_FLOOR)
    key_clause_hit = any(
        any(
            term in f"{item.get('question', '')}{item.get('answer', '')}"
            for term in KEY_TERMS
        )
        for item in hits[:3]
    )

    score = (
        WEIGHT_TOP1 * top1
        + WEIGHT_VALID_COUNT * min(valid_count, VALID_COUNT_CAP) / VALID_COUNT_CAP
        + WEIGHT_MARGIN * _clip(margin)
        + WEIGHT_KEY_CLAUSE * (1.0 if key_clause_hit else 0.0)
    )
    return EvidenceConfidence(
        round(_clip(score), 4),
        {
            "top1_score": round(top1, 4),
            "valid_count": valid_count,
            "margin": round(margin, 4),
            "key_clause_hit": key_clause_hit,
        },
    )


def evidence_snapshot(hits: list[dict[str, Any]], top_n: int = 3) -> list[dict[str, Any]]:
    """写低置信度池时保存的证据快照(Top N 原文与分数)。"""
    return [
        {
            "id": item.get("id"),
            "question": item.get("question", ""),
            "answer": item.get("answer", "")[:500],
            "score": item.get("score", 0.0),
            "rerank_score": item.get("rerank_score"),
        }
        for item in hits[:top_n]
    ]

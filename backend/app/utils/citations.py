"""RAG 引用构建:把检索结果转成对外稳定的引用结构。"""
from __future__ import annotations

from typing import Any


def build_citations(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从检索结果提取引用,按知识条目 id 去重。

    只保留回答生成时真正依赖的字段,避免把整段知识内容暴露给前端。
    """
    citations: list[dict[str, Any]] = []
    seen: set[int] = set()

    for item in results:
        raw_id = item.get("id")
        if raw_id is None:
            continue
        try:
            knowledge_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if knowledge_id in seen:
            continue
        seen.add(knowledge_id)

        try:
            score = round(float(item.get("score") or 0.0), 4)
        except (TypeError, ValueError):
            score = 0.0

        citations.append(
            {
                "id": knowledge_id,
                "category": str(item.get("category") or ""),
                "question": str(item.get("question") or ""),
                "score": score,
            }
        )

    return citations

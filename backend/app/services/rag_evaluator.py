"""RAG 检索离线评测:Recall@1/3/5、MRR@5 与分类别统计。

评测集是固定的「问题 → 期望知识条目 id」样本,见
``knowledge_base/eval_set.json``。评测只衡量检索排序质量,不评估生成答案。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.rag_service import RAGService

RECALL_KS = (1, 3, 5)


@dataclass(frozen=True)
class EvalSample:
    """一条评测样本。"""

    query: str
    expected_id: int
    category: str = ""
    # 知识条目的标准问题文本;数据库 id 漂移时用它做兜底匹配
    expected_question: str = ""


@dataclass
class EvalReport:
    """评测结果。"""

    total: int
    top_k: int
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    mrr_at_5: float
    vector_queries: int
    keyword_queries: int
    per_category: dict[str, dict[str, Any]] = field(default_factory=dict)
    misses: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "top_k": self.top_k,
            "recall_at_1": self.recall_at_1,
            "recall_at_3": self.recall_at_3,
            "recall_at_5": self.recall_at_5,
            "mrr_at_5": self.mrr_at_5,
            "retrieval_modes": {
                "vector": self.vector_queries,
                "keyword": self.keyword_queries,
            },
            "per_category": self.per_category,
            "misses": self.misses,
        }


def load_eval_set(path: Path) -> list[EvalSample]:
    """读取并校验评测集;若同目录存在 faqs.json,同时补全标准问题文本。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("samples") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        raise ValueError(f"评测集为空或格式错误: {path}")

    knowledge_file = path.parent / "faqs.json"
    id_to_question: dict[int, str] = {}
    if knowledge_file.exists():
        knowledge = json.loads(knowledge_file.read_text(encoding="utf-8"))
        id_to_question = {
            int(item["id"]): str(item.get("question") or "")
            for item in knowledge
            if isinstance(item, dict) and "id" in item
        }

    samples: list[EvalSample] = []
    seen_queries: set[str] = set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 条评测样本不是对象")
        query = str(item.get("query") or "").strip()
        expected_id = item.get("expected_id")
        if not query:
            raise ValueError(f"第 {index} 条评测样本缺少 query")
        if not isinstance(expected_id, int):
            raise ValueError(f"第 {index} 条评测样本 expected_id 必须是整数")
        if query in seen_queries:
            raise ValueError(f"评测集存在重复问题: {query}")
        seen_queries.add(query)
        samples.append(
            EvalSample(
                query=query,
                expected_id=expected_id,
                category=str(item.get("category") or ""),
                expected_question=id_to_question.get(expected_id, ""),
            )
        )
    return samples


def compute_report(
    records: list[tuple[EvalSample, list[int], list[str], str]], top_k: int = 5
) -> EvalReport:
    """根据每条样本的排序结果计算 Recall@k 与 MRR。

    命中判定优先比较知识 id;若数据库 id 与评测集参考 id 不一致,
    则用标准问题文本做兜底匹配,保证评测可跨环境复现。
    """
    if top_k < max(RECALL_KS):
        raise ValueError(f"top_k 至少为 {max(RECALL_KS)}")
    if not records:
        raise ValueError("没有可评测的记录")

    hits = {k: 0 for k in RECALL_KS}
    reciprocal_sum = 0.0
    vector_queries = 0
    keyword_queries = 0
    misses: list[dict[str, Any]] = []

    category_stats: dict[str, dict[str, int]] = {}
    for sample, ranked_ids, ranked_questions, mode in records:
        category = sample.category or "未分类"
        stats = category_stats.setdefault(
            category, {"total": 0, "hit@1": 0, "hit@3": 0, "hit@5": 0}
        )
        stats["total"] += 1

        if mode == "vector":
            vector_queries += 1
        elif mode == "keyword":
            keyword_queries += 1

        rank: int | None = None
        for index in range(max(len(ranked_ids), len(ranked_questions))):
            item_id = ranked_ids[index] if index < len(ranked_ids) else None
            item_question = (
                ranked_questions[index] if index < len(ranked_questions) else ""
            )
            id_match = item_id == sample.expected_id
            question_match = bool(
                sample.expected_question and item_question == sample.expected_question
            )
            if id_match or question_match:
                rank = index + 1
                break
        if rank is not None:
            reciprocal_sum += 1.0 / rank
            for k in RECALL_KS:
                if rank <= k:
                    hits[k] += 1
                    stats[f"hit@{k}"] += 1

        if rank is None or rank > 3:
            misses.append(
                {
                    "query": sample.query,
                    "expected_id": sample.expected_id,
                    "rank": rank,
                    "top_ids": ranked_ids[:top_k],
                    "top_questions": ranked_questions[:top_k],
                    "mode": mode,
                }
            )

    total = len(records)
    per_category = {
        name: {
            "total": stats["total"],
            "recall_at_1": round(stats["hit@1"] / stats["total"], 4),
            "recall_at_3": round(stats["hit@3"] / stats["total"], 4),
            "recall_at_5": round(stats["hit@5"] / stats["total"], 4),
        }
        for name, stats in sorted(category_stats.items())
    }

    return EvalReport(
        total=total,
        top_k=top_k,
        recall_at_1=round(hits[1] / total, 4),
        recall_at_3=round(hits[3] / total, 4),
        recall_at_5=round(hits[5] / total, 4),
        mrr_at_5=round(reciprocal_sum / total, 4),
        vector_queries=vector_queries,
        keyword_queries=keyword_queries,
        per_category=per_category,
        misses=misses,
    )


async def evaluate(
    rag_service: RAGService, samples: list[EvalSample], top_k: int = 5
) -> EvalReport:
    """逐条检索并汇总指标。"""
    records: list[tuple[EvalSample, list[int], list[str], str]] = []
    for sample in samples:
        results = await rag_service.search(sample.query, top_k=top_k)
        ranked_ids: list[int] = []
        ranked_questions: list[str] = []
        for item in results:
            try:
                ranked_ids.append(int(item["id"]))
            except (KeyError, TypeError, ValueError):
                continue
            ranked_questions.append(str(item.get("question") or ""))
        records.append(
            (
                sample,
                ranked_ids,
                ranked_questions,
                rag_service.last_search_mode or "unknown",
            )
        )
    return compute_report(records, top_k=top_k)

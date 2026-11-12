"""混合检索:向量 + BM25 + RRF 融合 + 本地重排。

策略:
- vector:仅向量检索(失败降级关键词);
- bm25:仅 BM25(失败降级关键词);
- hybrid:向量 + BM25 并行召回,RRF 融合;
- hybrid_rerank:hybrid 后用 bge-reranker 精排。

Query 扩写/子句拆分只在调用方显式开启时生效(聊天开启,评测关闭,保证口径稳定)。
"""
from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.services.knowledge_constants import CHUNK_ID_OFFSET
from app.services.query_rewriter import QueryRewriter
from app.services.reranker_service import RerankerService
from app.utils.logger import logger

if TYPE_CHECKING:
    from app.services.rag_service import RAGService

_CLAUSE_RE = re.compile(r"[,，;；?？。]")
_MIN_CLAUSE_LENGTH = 4


def split_clauses(query: str) -> list[str]:
    """把一问多意图按标点拆成子句;拆不出两条就原样返回。"""
    parts = [
        part.strip()
        for part in _CLAUSE_RE.split(query or "")
        if len(part.strip()) >= _MIN_CLAUSE_LENGTH
    ]
    return parts if len(parts) >= 2 else [query]


def rrf_fuse(result_lists: list[list[dict[str, Any]]], k: int = 60) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion;score 归一到 0-1 方便展示与证据闸。"""
    merged: dict[Any, dict[str, Any]] = {}
    for hits in result_lists:
        for rank, hit in enumerate(hits, 1):
            key = hit.get("id")
            if key is None:
                continue
            entry = merged.get(key)
            if entry is None:
                entry = dict(hit)
                entry["rrf_score"] = 0.0
                merged[key] = entry
            entry["rrf_score"] += 1.0 / (k + rank)

    if not merged:
        return []
    max_score = max(float(item["rrf_score"]) for item in merged.values()) or 1.0
    for item in merged.values():
        item["score"] = round(float(item["rrf_score"]) / max_score, 4)
    return sorted(merged.values(), key=lambda item: item["rrf_score"], reverse=True)


def arrange_head_tail(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """最相关放首、次相关放尾,缓解 lost-in-the-middle。"""
    if len(items) <= 2:
        return items
    return [items[0], *items[2:], items[1]]


def _merge_by_id(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[Any, dict[str, Any]] = {}
    for hit in hits:
        key = hit.get("id")
        if key is None:
            continue
        current = merged.get(key)
        if current is None or float(hit.get("score") or 0) > float(current.get("score") or 0):
            merged[key] = hit
    return sorted(merged.values(), key=lambda item: float(item.get("score") or 0), reverse=True)


def _merge_round_robin(result_lists: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """各子句轮流出一条,按 chunk id 去重;同一小节只留最靠前的一条。

    一问多意图时,如果直接拼接再按分数排序,一个意图可能占满前排;
    轮转合并让每个子句的第一名都进入候选,重复小节挪到尾部。
    """
    out: list[dict[str, Any]] = []
    seen_id: set[Any] = set()
    seen_section: set[str] = set()
    tail: list[dict[str, Any]] = []
    max_len = max((len(hits) for hits in result_lists), default=0)
    for index in range(max_len):
        for hits in result_lists:
            if index >= len(hits):
                continue
            hit = hits[index]
            key = hit.get("id")
            if key is None:
                key = (
                    hit.get("section_path", ""),
                    hit.get("question", ""),
                    hit.get("answer", ""),
                )
            if key in seen_id:
                continue
            seen_id.add(key)
            section = str(hit.get("section_path") or "")
            if section and section in seen_section:
                tail.append(hit)
            else:
                if section:
                    seen_section.add(section)
                out.append(hit)
    return out + tail


class RetrievalService:
    """混合检索入口。"""

    def __init__(
        self,
        rag: "RAGService | None" = None,
        reranker: RerankerService | None = None,
        rewriter: QueryRewriter | None = None,
    ) -> None:
        if rag is None:
            from app.services.rag_service import RAGService

            rag = RAGService()
        self.rag = rag
        self.reranker = reranker or RerankerService()
        self.rewriter = rewriter or QueryRewriter()
        self.last_mode = "unknown"

    async def search(
        self,
        query: str,
        strategy: str | None = None,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
        expand: bool = False,
        split: bool | None = None,
        exclude_chunks: bool = False,
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        strategy = strategy or settings.RAG_RETRIEVAL_STRATEGY
        top_k = top_k or settings.RAG_RERANK_TOP_K
        split = settings.RAG_SUBQUERY_SPLIT if split is None else split
        recall_k = max(settings.RAG_RECALL_TOP_K, top_k)

        queries = [query]
        if expand and settings.RAG_QUERY_EXPANSION:
            queries = await self.rewriter.expand(query)
        if split:
            clauses = split_clauses(query)
            if len(clauses) > 1:
                queries = clauses + [item for item in queries if item not in clauses]

        query_results: list[list[dict[str, Any]]] = []
        modes: list[str] = []
        for item in queries:
            hits, mode = await self._search_once(
                item,
                strategy,
                recall_k,
                filters,
                exclude_chunks=exclude_chunks,
            )
            modes.append(mode)
            query_results.append(hits)

        if len(query_results) > 1:
            candidates = _merge_round_robin(query_results)
        else:
            candidates = _merge_by_id(query_results[0]) if query_results else []
        if not candidates:
            self.last_mode = "keyword"
            self.rag.last_search_mode = "keyword"
            return []

        if strategy == "hybrid_rerank":
            documents = [
                f"{hit.get('question', '')} {hit.get('answer', '')}".strip()
                for hit in candidates
            ]
            ranked = await self.reranker.rerank(query, documents, top_n=top_k)
            if ranked is not None:
                results = []
                for index, score in ranked:
                    hit = dict(candidates[index])
                    hit["rerank_score"] = round(score, 4)
                    hit["score"] = round(score, 4)
                    results.append(hit)
                self.last_mode = "hybrid_rerank"
                self.rag.last_search_mode = "hybrid_rerank"
                return results

        self.last_mode = _dominant_mode(modes, strategy)
        self.rag.last_search_mode = self.last_mode
        return candidates[:top_k]

    async def _search_once(
        self,
        query: str,
        strategy: str,
        top_k: int,
        filters: dict[str, Any] | None,
        exclude_chunks: bool = False,
    ) -> tuple[list[dict[str, Any]], str]:
        def _filter(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if not exclude_chunks:
                return hits
            return [
                hit
                for hit in hits
                if int(hit.get("id") or 0) < CHUNK_ID_OFFSET
            ]

        if strategy == "vector":
            try:
                return (
                    _filter(await self.rag.search_dense(query, top_k, filters)),
                    "vector",
                )
            except Exception as exc:  # noqa: BLE001 - 检索降级是预期路径
                logger.warning("向量检索失败,降级关键词: {}", exc)
                return self.rag.keyword_search(query, top_k, filters), "keyword"

        if strategy == "bm25":
            try:
                return (
                    _filter(await self.rag.search_bm25(query, top_k, filters)),
                    "bm25",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("BM25 检索失败,降级关键词: {}", exc)
                return self.rag.keyword_search(query, top_k, filters), "keyword"

        dense_result, bm25_result = await asyncio.gather(
            self.rag.search_dense(query, top_k, filters),
            self.rag.search_bm25(query, top_k, filters),
            return_exceptions=True,
        )
        dense = _filter(dense_result) if isinstance(dense_result, list) else []
        bm25 = _filter(bm25_result) if isinstance(bm25_result, list) else []

        if not dense and not bm25:
            return self.rag.keyword_search(query, top_k, filters), "keyword"
        if not bm25:
            return dense, "vector"
        if not dense:
            return bm25, "bm25"

        return rrf_fuse([dense, bm25]), "hybrid"


def _dominant_mode(modes: list[str], strategy: str) -> str:
    if not modes:
        return strategy
    if all(mode == modes[0] for mode in modes):
        return modes[0]
    if "keyword" in modes and all(mode == "keyword" for mode in modes):
        return "keyword"
    if strategy == "hybrid_rerank":
        return "hybrid"
    return strategy

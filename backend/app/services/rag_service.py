"""RAG 服务:Milvus 向量检索 + 生成回答。

相比文档的 mock 实现:
- 真实连接 Milvus 做向量检索;
- Milvus / Embedding 不可用时自动降级为本地关键词检索,保证开发期可用;
- 文档入库与向量入库由调用方保证一致(Milvus 以知识库主键 id 作为向量主键)。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.embedding_service import EmbeddingService
from app.services.evidence import EvidenceConfidence, compute_evidence_confidence
from app.services.knowledge_constants import CHUNK_ID_OFFSET
from app.services.llm_service import LLMService
from app.services.retrieval import RetrievalService
from app.utils.citations import build_citations as build_citation_list
from app.utils.logger import logger

KNOWLEDGE_FILE = Path(__file__).resolve().parents[3] / "knowledge_base" / "faqs.json"


@dataclass(frozen=True)
class RetrievalResult:
    """一次 RAG 检索的完整结果:命中、上下文、引用、证据置信度与检索模式。"""

    hits: list[dict[str, Any]]
    context: str
    citations: list[dict[str, Any]]
    evidence: EvidenceConfidence
    mode: str


class RAGService:
    """检索增强生成服务(单例)。"""

    _instance: "RAGService | None" = None

    def __new__(cls) -> "RAGService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self.embedding_service = EmbeddingService()
        self.llm_service = LLMService()
        self.collection = settings.MILVUS_COLLECTION

        self._client: Any = None
        self._collection_ready = False
        self._client_lock: asyncio.Lock | None = None
        self._fallback_docs: list[dict[str, Any]] | None = None
        # 最近一次检索实际走的路径(vector / keyword),用于评测与诊断
        self.last_search_mode: str | None = None
        # 向量 / BM25 检索失败后的冷却截止时间(monotonic),避免持续重试宕机服务
        self._vector_retry_after = 0.0
        self._bm25_retry_after = 0.0

    def _lock(self) -> asyncio.Lock:
        if self._client_lock is None:
            self._client_lock = asyncio.Lock()
        return self._client_lock

    # ---------------- Milvus 初始化 ----------------
    def _get_client_sync(self):
        from pymilvus import MilvusClient

        if self._client is None:
            self._client = MilvusClient(uri=settings.MILVUS_URI)
        return self._client

    def _ensure_collection_sync(self, client) -> None:
        if client.has_collection(self.collection):
            try:
                description = client.describe_collection(self.collection)
                fields = {
                    field.get("name")
                    for field in description.get("fields", [])
                    if isinstance(field, dict)
                }
                if "sparse" not in fields:
                    logger.warning(
                        "Milvus collection 缺少 BM25 sparse 字段,混合检索会降级;"
                        "请运行 python scripts/init_vector_db.py --rebuild"
                    )
            except Exception as exc:  # noqa: BLE001 - 仅诊断,不阻断启动
                logger.warning("检查 Milvus collection schema 失败: {}", exc)
            client.load_collection(self.collection)
            return

        from pymilvus import DataType, Function, FunctionType, MilvusClient

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field(
            "vector", DataType.FLOAT_VECTOR, dim=self.embedding_service.dimension
        )
        schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field("category", DataType.VARCHAR, max_length=100)
        # BM25 函数只接受 1 个输入字段,用 text 汇总「问题 + 答案」;中文分词
        schema.add_field(
            "text",
            DataType.VARCHAR,
            max_length=10000,
            enable_analyzer=True,
            analyzer_params={"type": "chinese"},
        )
        schema.add_field("question", DataType.VARCHAR, max_length=2000)
        schema.add_field("answer", DataType.VARCHAR, max_length=8000)
        schema.add_function(
            Function(
                name="bm25",
                function_type=FunctionType.BM25,
                input_field_names=["text"],
                output_field_names=["sparse"],
            )
        )
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="vector", index_type="AUTOINDEX", metric_type="COSINE"
        )
        index_params.add_index(
            field_name="sparse",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
        )
        client.create_collection(
            collection_name=self.collection,
            schema=schema,
            index_params=index_params,
        )
        client.load_collection(self.collection)
        logger.info("Milvus collection 已创建(含 BM25): {}", self.collection)

    async def drop_collection(self) -> None:
        """删除当前 collection,供脚本重建 BM25 schema。"""
        client = await asyncio.to_thread(self._get_client_sync)
        has_collection = await asyncio.to_thread(
            client.has_collection, self.collection
        )
        if has_collection:
            await asyncio.to_thread(client.drop_collection, self.collection)
            logger.info("Milvus collection 已删除: {}", self.collection)
        self._collection_ready = False

    async def _ensure_ready(self):
        if self._collection_ready:
            return self._get_client_sync()

        async with self._lock():
            if not self._collection_ready:
                client = await asyncio.to_thread(self._get_client_sync)
                await asyncio.to_thread(self._ensure_collection_sync, client)
                self._collection_ready = True
        return self._get_client_sync()

    # ---------------- 写入 ----------------
    async def add_documents(self, documents: list[dict[str, Any]]) -> int:
        """批量写入知识向量(以文档 id 作为主键,重复写入即更新)。"""
        if not documents:
            return 0

        texts = [
            f"{doc.get('question', '')} {doc.get('answer', '')}".strip()
            for doc in documents
        ]
        vectors = await self.embedding_service.encode(texts)

        rows = []
        for doc, vector in zip(documents, vectors):
            rows.append(
                {
                    "id": int(doc["id"]),
                    "vector": vector,
                    "category": doc.get("category", ""),
                    "text": f"{doc.get('question', '')} {doc.get('answer', '')}".strip(),
                    "question": doc.get("question", ""),
                    "answer": doc.get("answer", ""),
                }
            )

        client = await self._ensure_ready()
        await asyncio.to_thread(
            client.upsert, collection_name=self.collection, data=rows
        )
        # BM25 索引在 flush 后才保证可检索
        await asyncio.to_thread(client.flush, self.collection)
        logger.info("已写入 {} 条知识向量到 Milvus", len(rows))
        return len(rows)

    async def add_document(self, document: dict[str, Any]) -> str:
        """单条写入,返回向量 id。"""
        await self.add_documents([document])
        return str(document["id"])

    async def add_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """写入文档片段向量;主键使用 CHUNK_ID_OFFSET + chunk.id。"""
        if not chunks:
            return 0
        texts = [str(chunk.get("content") or "") for chunk in chunks]
        vectors = await self.embedding_service.encode(texts)
        rows = [
            {
                "id": CHUNK_ID_OFFSET + int(chunk["id"]),
                "vector": vector,
                "category": str(chunk.get("document_title") or "文档片段"),
                "text": str(chunk.get("content") or ""),
                "question": str(chunk.get("section_path") or "正文"),
                "answer": str(chunk.get("content") or ""),
            }
            for chunk, vector in zip(chunks, vectors)
        ]
        client = await self._ensure_ready()
        await asyncio.to_thread(
            client.upsert, collection_name=self.collection, data=rows
        )
        await asyncio.to_thread(client.flush, self.collection)
        logger.info("已写入 {} 条文档片段向量到 Milvus", len(rows))
        return len(rows)

    async def delete_documents(self, ids: list[int]) -> None:
        if not ids:
            return
        client = await self._ensure_ready()
        await asyncio.to_thread(client.delete, collection_name=self.collection, ids=ids)
        logger.info("已从 Milvus 删除 {} 条向量", len(ids))

    # ---------------- 检索 ----------------
    async def search_dense(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """向量检索;失败抛异常,由检索层决定降级。"""
        query = (query or "").strip()
        if not query:
            return []
        if time.monotonic() < self._vector_retry_after:
            raise RuntimeError("向量检索处于降级冷却期")

        # 向量化失败由 embed circuit 自己恢复,不能误伤 Milvus 冷却
        vector = await self.embedding_service.encode_one(query)

        try:
            client = await self._ensure_ready()
            results = await asyncio.to_thread(
                client.search,
                collection_name=self.collection,
                data=[vector],
                anns_field="vector",
                search_params={"metric_type": "COSINE"},
                limit=top_k,
                output_fields=["category", "question", "answer"],
                filter=self._build_filter(filters),
            )
            return self._parse_hits(results)
        except Exception:
            self._vector_retry_after = (
                time.monotonic() + settings.RAG_VECTOR_RETRY_SECONDS
            )
            raise

    async def search_bm25(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Milvus 原生 BM25 检索;collection 无 sparse 字段时抛异常。"""
        query = (query or "").strip()
        if not query:
            return []
        if time.monotonic() < self._bm25_retry_after:
            raise RuntimeError("BM25 检索处于降级冷却期")

        try:
            client = await self._ensure_ready()
            results = await asyncio.to_thread(
                client.search,
                collection_name=self.collection,
                data=[query],
                anns_field="sparse",
                search_params={"metric_type": "BM25"},
                limit=top_k,
                output_fields=["category", "question", "answer"],
                filter=self._build_filter(filters),
            )
            return self._parse_hits(results)
        except Exception:
            self._bm25_retry_after = (
                time.monotonic() + settings.RAG_VECTOR_RETRY_SECONDS
            )
            raise

    def keyword_search(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """关键词 + bigram 降级检索。"""
        return self._keyword_search(query, top_k, filters)

    @staticmethod
    def _parse_hits(results: list) -> list[dict[str, Any]]:
        hits = results[0] if results else []
        return [
            {
                "id": hit.get("id"),
                "score": round(float(hit.get("distance", 0.0)), 4),
                "category": (hit.get("entity") or {}).get("category", ""),
                "question": (hit.get("entity") or {}).get("question", ""),
                "answer": (hit.get("entity") or {}).get("answer", ""),
            }
            for hit in hits
        ]

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """兼容旧调用:向量检索,失败降级关键词。"""
        query = (query or "").strip()
        if not query:
            return []
        try:
            results = await self.search_dense(query, top_k, filters)
            self.last_search_mode = "vector"
            return results
        except Exception as exc:  # noqa: BLE001
            logger.warning("向量检索不可用,降级关键词检索: {}", exc)
            self.last_search_mode = "keyword"
            return self.keyword_search(query, top_k, filters)

    async def retrieve_with_evidence(
        self,
        query: str,
        top_k: int = 3,
        filters: dict[str, Any] | None = None,
        expand: bool | None = None,
        split: bool | None = None,
    ) -> RetrievalResult:
        """混合检索 + 重排 + 证据置信度。"""
        from app.services.retrieval import arrange_head_tail

        retrieval = RetrievalService(self)
        hits = await retrieval.search(
            query,
            top_k=top_k,
            filters=filters,
            expand=settings.RAG_QUERY_EXPANSION if expand is None else expand,
            split=split,
        )
        # 证据置信度按原始排序计算;给 LLM 的上下文做首尾重排
        evidence = compute_evidence_confidence(hits)
        ordered = arrange_head_tail(hits)
        return RetrievalResult(
            hits=ordered,
            context=self._format_context(ordered),
            citations=build_citation_list(ordered),
            evidence=evidence,
            mode=retrieval.last_mode,
        )

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> str:
        """检索并格式化为 LLM 上下文。"""
        result = await self.retrieve_with_evidence(
            query, top_k=top_k, filters=filters, expand=False, split=False
        )
        return result.context

    async def retrieve_with_citations(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """检索并同时返回 LLM 上下文与结构化引用。"""
        result = await self.retrieve_with_evidence(
            query, top_k=top_k, filters=filters, expand=False, split=False
        )
        return result.context, result.citations

    @staticmethod
    def build_citations(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把检索结果转换为引用(保留给调用方与测试使用)。"""
        return build_citation_list(results)

    @staticmethod
    def build_prompt(query: str, context: str, skill: str = "") -> str:
        prompt = (
            "你是电商平台智能客服。请严格基于以下知识库内容回答用户问题,"
            "不要编造知识库中没有的信息;若知识库无相关内容,请如实说明。\n\n"
            f"{context}\n\n用户问题:{query}\n\n要求:直接回答,简洁专业。"
        )
        text = (skill or "").strip()
        if text:
            prompt += f"\n\n## 当前场景操作说明(运营维护,优先遵守)\n{text}"
        return prompt

    async def generate(
        self, query: str, context: str, skill: str = ""
    ) -> str:
        """基于检索结果生成回答。"""
        return await self.llm_service.generate(
            self.build_prompt(query, context, skill), temperature=0.3
        )

    # ---------------- 内部工具 ----------------
    @staticmethod
    def _build_filter(filters: dict[str, Any] | None) -> str:
        if not filters:
            return ""
        conditions = []
        for key, value in filters.items():
            if isinstance(value, str):
                escaped = value.replace('"', '\\"')
                conditions.append(f'{key} == "{escaped}"')
        return " and ".join(conditions)

    @staticmethod
    def _format_context(results: list[dict[str, Any]]) -> str:
        if not results:
            return ""
        parts = []
        for index, item in enumerate(results, 1):
            parts.append(
                f"【文档 {index}】相似度:{item.get('score', 0):.2f}\n"
                f"分类:{item.get('category', '')}\n"
                f"问题:{item.get('question', '')}\n"
                f"答案:{item.get('answer', '')}"
            )
        return "\n\n".join(parts)

    def _load_fallback_docs(self) -> list[dict[str, Any]]:
        if self._fallback_docs is not None:
            return self._fallback_docs
        try:
            with KNOWLEDGE_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
            self._fallback_docs = data if isinstance(data, list) else []
        except FileNotFoundError:
            logger.warning("知识库文件不存在: {}", KNOWLEDGE_FILE)
            self._fallback_docs = []
        except json.JSONDecodeError as exc:
            logger.error("知识库文件格式错误: {}", exc)
            self._fallback_docs = []
        return self._fallback_docs

    def _keyword_search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        category = (filters or {}).get("category")

        scored: list[dict[str, Any]] = []
        for doc in self._load_fallback_docs():
            if category and doc.get("category") != category:
                continue

            text = (
                f"{doc.get('question', '')} {doc.get('answer', '')} "
                f"{doc.get('category', '')} {doc.get('keywords', '')}"
            ).lower()

            score = 0.0
            for keyword in str(doc.get("keywords", "")).split():
                if keyword and keyword.lower() in query_lower:
                    score += 0.35
            score += 0.5 * self._bigram_overlap(query_lower, str(doc.get("question", "")).lower())
            score += 0.2 * self._bigram_overlap(query_lower, text)

            if score <= 0.05:
                continue

            scored.append(
                {
                    "id": doc.get("id"),
                    "score": round(min(score, 0.99), 4),
                    "category": doc.get("category", ""),
                    "question": doc.get("question", ""),
                    "answer": doc.get("answer", ""),
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    @staticmethod
    def _bigram_overlap(source: str, target: str) -> float:
        source_bigrams = {source[i:i + 2] for i in range(len(source) - 1)}
        if not source_bigrams:
            return 0.0
        target_bigrams = {target[i:i + 2] for i in range(len(target) - 1)}
        return len(source_bigrams & target_bigrams) / len(source_bigrams)

    async def health(self) -> bool:
        """Milvus 连通性检查。"""
        try:
            client = await asyncio.to_thread(self._get_client_sync)
            await asyncio.to_thread(client.list_collections)
            # 健康检查通过时立即解除降级冷却,便于恢复后马上走回向量/BM25 检索
            self._vector_retry_after = 0.0
            self._bm25_retry_after = 0.0
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Milvus 健康检查失败: {}", exc)
            return False

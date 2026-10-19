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
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService
from app.utils.logger import logger

KNOWLEDGE_FILE = Path(__file__).resolve().parents[3] / "knowledge_base" / "faqs.json"


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
            client.load_collection(self.collection)
            return

        client.create_collection(
            collection_name=self.collection,
            dimension=self.embedding_service.dimension,
            primary_field_name="id",
            id_type="int",
            vector_field_name="vector",
            metric_type="COSINE",
            auto_id=False,
            enable_dynamic_field=True,
        )
        client.load_collection(self.collection)
        logger.info("Milvus collection 已创建: {}", self.collection)

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
                    "question": doc.get("question", ""),
                    "answer": doc.get("answer", ""),
                }
            )

        client = await self._ensure_ready()
        await asyncio.to_thread(
            client.upsert, collection_name=self.collection, data=rows
        )
        logger.info("已写入 {} 条知识向量到 Milvus", len(rows))
        return len(rows)

    async def add_document(self, document: dict[str, Any]) -> str:
        """单条写入,返回向量 id。"""
        await self.add_documents([document])
        return str(document["id"])

    async def delete_documents(self, ids: list[int]) -> None:
        if not ids:
            return
        client = await self._ensure_ready()
        await asyncio.to_thread(client.delete, collection_name=self.collection, ids=ids)
        logger.info("已从 Milvus 删除 {} 条向量", len(ids))

    # ---------------- 检索 ----------------
    async def search(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """向量检索,失败时降级关键词检索。"""
        query = (query or "").strip()
        if not query:
            return []

        try:
            vector = await self.embedding_service.encode_one(query)
            client = await self._ensure_ready()
            expression = self._build_filter(filters)

            results = await asyncio.to_thread(
                client.search,
                collection_name=self.collection,
                data=[vector],
                limit=top_k,
                output_fields=["category", "question", "answer"],
                filter=expression,
            )

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
        except Exception as exc:  # noqa: BLE001 - 基础设施异常统一降级
            logger.warning("Milvus 检索不可用,降级为关键词检索: {}", exc)
            return self._keyword_search(query, top_k, filters)

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> str:
        """检索并格式化为 LLM 上下文。"""
        results = await self.search(query, top_k=top_k, filters=filters)
        return self._format_context(results)

    async def generate(self, query: str, context: str) -> str:
        """基于检索结果生成回答。"""
        prompt = (
            "你是电商平台智能客服。请严格基于以下知识库内容回答用户问题,"
            "不要编造知识库中没有的信息;若知识库无相关内容,请如实说明。\n\n"
            f"{context}\n\n用户问题:{query}\n\n要求:直接回答,简洁专业。"
        )
        return await self.llm_service.generate(prompt, temperature=0.3)

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
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Milvus 健康检查失败: {}", exc)
            return False

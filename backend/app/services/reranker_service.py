"""本地 BGE 重排服务:CrossEncoder 精排检索候选。

模型懒加载、单例复用;重排不可用时返回 None,由检索层退回混合检索顺序。
"""
from __future__ import annotations

import asyncio
import math
import os

import httpx

from app.core import circuit
from app.core.config import settings
from app.utils.logger import logger


def sigmoid(value: float) -> float:
    """把 CrossEncoder 的 logit 归一到 0-1,供证据置信度与前端展示。"""
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


class RerankerService:
    """BGE reranker 单例。"""

    _instance: RerankerService | None = None

    def __new__(cls) -> RerankerService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.model_name = settings.RAG_RERANK_MODEL
        self._model = None
        self._load_lock: asyncio.Lock | None = None

    def _lock(self) -> asyncio.Lock:
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()
        return self._load_lock

    def _load_sync(self):
        os.environ.setdefault("HF_ENDPOINT", settings.HF_ENDPOINT)
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        from sentence_transformers import CrossEncoder

        logger.info("正在加载 Reranker 模型: {} (首次使用需下载)", self.model_name)
        model = CrossEncoder(self.model_name, max_length=512)
        logger.info("Reranker 模型加载完成: {}", self.model_name)
        return model

    async def _ensure_model(self):
        if self._model is not None:
            return self._model
        async with self._lock():
            if self._model is None:
                self._model = await asyncio.to_thread(self._load_sync)
        return self._model

    @staticmethod
    def _remote_enabled() -> bool:
        return (
            (settings.RERANK_PROVIDER or "local").lower()
            in {"openai", "siliconflow", "remote"}
            and bool(settings.RERANK_API_BASE)
            and bool(settings.RERANK_API_KEY)
        )

    async def _rerank_remote(
        self, query: str, documents: list[str], top_n: int | None
    ) -> list[tuple[int, float]] | None:
        async def _call() -> list[tuple[int, float]]:
            url = settings.RERANK_API_BASE.rstrip("/") + "/rerank"
            payload = {
                "model": settings.RAG_RERANK_MODEL,
                "query": query,
                "documents": documents,
                "top_n": top_n or len(documents),
            }
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {settings.RERANK_API_KEY}"
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            ranked = [
                (
                    int(item.get("index", 0)),
                    float(item.get("relevance_score", item.get("score", 0))),
                )
                for item in (data.get("results") or [])
            ]
            ranked.sort(key=lambda item: item[1], reverse=True)
            return ranked[:top_n] if top_n else ranked

        try:
            return await circuit.rerank_breaker.call(_call)
        except circuit.CircuitOpenError as exc:
            logger.warning("远程 Reranker 熔断: {}", exc)
            return None
        except Exception as exc:  # noqa: BLE001 - 远程失败退回混合检索顺序
            logger.warning("远程 Reranker 失败: {}", exc)
            return None

    async def rerank(
        self, query: str, documents: list[str], top_n: int | None = None
    ) -> list[tuple[int, float]] | None:
        """返回 [(原始下标, 归一化分数)],失败返回 None(调用方保持原顺序)。"""
        if not documents:
            return []
        if not settings.RAG_RERANK_ENABLED:
            return None
        if self._remote_enabled():
            return await self._rerank_remote(query, documents, top_n)

        async def _run():
            # 模型加载与推理都纳入熔断;恢复后由 half-open 自动重新探测
            model = await self._ensure_model()
            pairs = [(query, document) for document in documents]
            return await asyncio.to_thread(model.predict, pairs)

        try:
            scores = await circuit.rerank_breaker.call(_run)
        except circuit.CircuitOpenError as exc:
            logger.warning("Reranker 熔断中,保持混合检索顺序: {}", exc)
            return None
        except Exception as exc:  # noqa: BLE001 - 重排是增强,失败退回混合检索
            logger.warning("Reranker 不可用,保持混合检索顺序: {}", exc)
            return None

        ranked = sorted(
            ((index, float(score)) for index, score in enumerate(scores)),
            key=lambda item: item[1],
            reverse=True,
        )
        if top_n is not None:
            ranked = ranked[:top_n]
        return [(index, sigmoid(score)) for index, score in ranked]

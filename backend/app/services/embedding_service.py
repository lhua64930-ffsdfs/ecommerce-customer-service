"""Embedding 服务:本地 BGE 中文向量模型。

为什么用本地模型:
- DeepSeek 没有 embedding 接口;
- BGE 中文小模型免费、可离线、512 维,足够电商 FAQ 检索。

性能要点:模型单例 + 懒加载,整个进程只加载一次(加载需数秒、数百 MB)。
"""
from __future__ import annotations

import asyncio
import math
import os

from app.core import circuit
from app.core.config import settings
from app.utils.logger import logger

# 必须在 sentence_transformers / huggingface_hub 导入前设置镜像
os.environ.setdefault("HF_ENDPOINT", settings.HF_ENDPOINT)
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


class EmbeddingError(RuntimeError):
    """向量化失败(模型不可用等)。"""


class EmbeddingService:
    """Embedding 服务(单例)。"""

    _instance: EmbeddingService | None = None

    def __new__(cls) -> EmbeddingService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.provider = (settings.EMBEDDING_PROVIDER or "local").lower()
        self.model_name = settings.EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIM
        self._model = None
        self._remote_client = None
        self._load_lock: asyncio.Lock | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _lock(self) -> asyncio.Lock:
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()
        return self._load_lock

    def _load_sync(self):
        """同步加载模型(在线程池中执行,避免阻塞事件循环)。"""
        from sentence_transformers import SentenceTransformer

        logger.info("正在加载 Embedding 模型: {} (首次使用需下载)", self.model_name)
        model = SentenceTransformer(self.model_name)
        logger.info("Embedding 模型加载完成: {}", self.model_name)
        return model

    async def _ensure_model(self):
        if self._model is not None:
            return self._model

        async with self._lock():
            if self._model is None:
                try:
                    self._model = await asyncio.to_thread(self._load_sync)
                except Exception as exc:
                    logger.error("Embedding 模型加载失败: {}", exc)
                    raise EmbeddingError(f"Embedding 模型不可用: {exc}") from exc
        return self._model

    def _remote_enabled(self) -> bool:
        return (
            self.provider in {"openai", "siliconflow", "remote"}
            and bool(settings.EMBEDDING_API_BASE)
            and bool(settings.EMBEDDING_API_KEY)
        )

    def _get_remote_client(self):
        if self._remote_client is None:
            from openai import AsyncOpenAI

            self._remote_client = AsyncOpenAI(
                api_key=settings.EMBEDDING_API_KEY,
                base_url=settings.EMBEDDING_API_BASE,
                timeout=30,
                max_retries=0,
            )
        return self._remote_client

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    async def _encode_remote(self, texts: list[str]) -> list[list[float]]:
        async def _call() -> list[list[float]]:
            client = self._get_remote_client()
            response = await client.embeddings.create(
                model=self.model_name, input=texts
            )
            return [
                self._normalize(list(item.embedding))
                for item in sorted(response.data, key=lambda item: item.index)
            ]

        return await circuit.embed_breaker.call(_call)

    async def encode(self, texts: list[str]) -> list[list[float]]:
        """批量向量化,返回归一化后的向量。"""
        if not texts:
            return []

        remote_failed = False
        if self._remote_enabled():
            try:
                return await self._encode_remote(texts)
            except circuit.CircuitOpenError as exc:
                remote_failed = True
                logger.warning("远程 Embedding 熔断,回退本地: {}", exc)
            except Exception as exc:  # noqa: BLE001 - 远程失败回退本地
                remote_failed = True
                logger.warning("远程 Embedding 失败,回退本地: {}", exc)

        async def _run() -> list[list[float]]:
            # 模型加载与推理都放进熔断保护,首次下载失败也计入失败次数
            model = await self._ensure_model()

            def _encode() -> list[list[float]]:
                vectors = model.encode(
                    texts,
                    normalize_embeddings=True,
                    batch_size=32,
                    show_progress_bar=False,
                )
                return [vector.tolist() for vector in vectors]

            return await asyncio.to_thread(_encode)

        # 远程失败/熔断时本地是最后兜底,不再受远程熔断器阻挡
        if remote_failed:
            return await _run()
        try:
            return await circuit.embed_breaker.call(_run)
        except circuit.CircuitOpenError as exc:
            raise EmbeddingError("Embedding 上游熔断中") from exc

    async def encode_one(self, text: str) -> list[float]:
        vectors = await self.encode([text])
        return vectors[0]

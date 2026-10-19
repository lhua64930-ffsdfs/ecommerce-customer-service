"""Embedding 服务:本地 BGE 中文向量模型。

为什么用本地模型:
- DeepSeek 没有 embedding 接口;
- BGE 中文小模型免费、可离线、512 维,足够电商 FAQ 检索。

性能要点:模型单例 + 懒加载,整个进程只加载一次(加载需数秒、数百 MB)。
"""
from __future__ import annotations

import asyncio
import os

from app.core.config import settings
from app.utils.logger import logger

# 必须在 sentence_transformers / huggingface_hub 导入前设置镜像
os.environ.setdefault("HF_ENDPOINT", settings.HF_ENDPOINT)
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


class EmbeddingError(RuntimeError):
    """向量化失败(模型不可用等)。"""


class EmbeddingService:
    """Embedding 服务(单例)。"""

    _instance: "EmbeddingService | None" = None

    def __new__(cls) -> "EmbeddingService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.model_name = settings.EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIM
        self._model = None
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
                except Exception as exc:  # noqa: BLE001
                    logger.error("Embedding 模型加载失败: {}", exc)
                    raise EmbeddingError(f"Embedding 模型不可用: {exc}") from exc
        return self._model

    async def encode(self, texts: list[str]) -> list[list[float]]:
        """批量向量化,返回归一化后的向量。"""
        if not texts:
            return []

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

    async def encode_one(self, text: str) -> list[float]:
        vectors = await self.encode([text])
        return vectors[0]

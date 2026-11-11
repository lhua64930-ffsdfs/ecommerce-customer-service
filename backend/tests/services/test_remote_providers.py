"""远程 Embedding / Rerank 分支。"""
from __future__ import annotations

from types import SimpleNamespace

from app.core.config import settings
from app.services import reranker_service
from app.services.embedding_service import EmbeddingService
from app.services.reranker_service import RerankerService


async def test_remote_embedding_normalizes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "EMBEDDING_API_BASE", "http://embed.test/v1")
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "key")
    service = EmbeddingService()
    service.provider = "openai"
    service.model_name = "BAAI/bge-m3"

    class FakeEmbeddings:
        async def create(self, model, input):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=0, embedding=[3.0, 4.0]),
                    SimpleNamespace(index=1, embedding=[0.0, 2.0]),
                ]
            )

    service._remote_client = SimpleNamespace(embeddings=FakeEmbeddings())

    vectors = await service.encode(["a", "b"])

    assert vectors == [[0.6, 0.8], [0.0, 1.0]]


async def test_remote_rerank_sorts_results(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "siliconflow")
    monkeypatch.setattr(settings, "RERANK_API_BASE", "http://rerank.test/v1")
    monkeypatch.setattr(settings, "RERANK_API_KEY", "key")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ]
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr(
        reranker_service.httpx, "AsyncClient", lambda **kwargs: FakeClient()
    )

    ranked = await RerankerService().rerank("q", ["doc-a", "doc-b"])

    assert ranked == [(1, 0.9), (0, 0.2)]

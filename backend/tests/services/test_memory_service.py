"""会话上下文:摘要边界滑窗与语义历史排序。"""
from __future__ import annotations

from app.services import memory_service


def test_build_window_respects_summary_boundary() -> None:
    messages = [
        {"id": 1, "content": "old-1"},
        {"id": 2, "content": "old-2"},
        {"id": 3, "content": "new-1"},
    ]

    assert [item["id"] for item in memory_service.build_window(messages)] == [1, 2, 3]
    assert [
        item["id"]
        for item in memory_service.build_window(messages, after_id=2)
    ] == [3]


async def test_search_history_ranks_by_cosine(monkeypatch) -> None:
    class FakeEmbedding:
        async def encode(self, texts: list[str]) -> list[list[float]]:
            vectors = {
                "query": [1.0, 0.0],
                "relevant": [1.0, 0.0],
                "partial": [0.8, 0.6],
                "unrelated": [0.0, 1.0],
            }
            return [vectors[text] for text in texts]

    monkeypatch.setattr(memory_service, "EmbeddingService", FakeEmbedding)

    indices = await memory_service.search_history(
        "query",
        ["relevant", "unrelated", "partial"],
        top_k=2,
        min_score=0.5,
    )

    assert indices == [0, 2]

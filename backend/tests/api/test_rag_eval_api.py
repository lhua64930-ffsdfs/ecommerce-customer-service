"""RAG 评测看板接口测试。"""
import httpx


async def test_rag_eval_overview_returns_report(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/rag-eval/overview")

    assert response.status_code == 200
    data = response.json()
    assert "present" in data
    assert "commands" in data
    if data["present"]:
        assert data["best_strategy"]["name"] in {
            "vector",
            "bm25",
            "hybrid",
            "hybrid_rerank",
        }

"""用户反馈接口测试。"""
import httpx


async def test_down_feedback_enters_low_confidence_pool(
    client: httpx.AsyncClient,
) -> None:
    session_response = await client.post("/api/v1/chat/session", json={})
    session_id = session_response.json()["session"]["session_id"]

    response = await client.post(
        "/api/v1/feedback",
        json={
            "session_id": session_id,
            "question": "质量问题怎么退换",
            "rating": "down",
            "comment": "没解决",
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["pooled"] is True

    queue = await client.get("/api/v1/review/queue")
    assert queue.status_code == 200
    assert queue.json()["pending_low_confidence"] >= 1


async def test_up_feedback_is_not_pooled(client: httpx.AsyncClient) -> None:
    session_response = await client.post("/api/v1/chat/session", json={})
    session_id = session_response.json()["session"]["session_id"]

    response = await client.post(
        "/api/v1/feedback",
        json={
            "session_id": session_id,
            "question": "商品可以退换吗",
            "rating": "up",
        },
    )

    assert response.status_code == 200
    assert response.json()["pooled"] is False

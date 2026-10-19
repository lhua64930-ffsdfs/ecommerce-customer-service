"""对话接口集成测试(需要本地容器运行)。"""
import httpx


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["database"] is True
    assert data["redis"] is True


async def test_chat_flow(client: httpx.AsyncClient) -> None:
    session_response = await client.post("/api/v1/chat/session", json={})
    assert session_response.status_code == 200
    session_id = session_response.json()["session"]["session_id"]

    rag_response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "商品可以退换吗"},
    )
    assert rag_response.status_code == 200
    rag_data = rag_response.json()
    assert rag_data["intent"]["handler_type"] == "rag"
    assert "退换" in rag_data["response"]

    order_response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "查订单 ORDER20260315001"},
    )
    assert order_response.status_code == 200
    order_data = order_response.json()
    assert order_data["intent"]["intent_code"] == "order_query"
    assert order_data["tool_calls"][0]["success"] is True
    assert "ORDER20260315001" in order_data["response"]

    transfer_response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "太差了我要投诉"},
    )
    transfer_data = transfer_response.json()
    assert transfer_data["sentiment"] == "negative"
    assert transfer_data["need_transfer"] is True

    history_response = await client.get(
        "/api/v1/chat/history", params={"session_id": session_id}
    )
    assert history_response.status_code == 200
    assert history_response.json()["total"] == 6


async def test_order_ownership_is_enforced(client: httpx.AsyncClient) -> None:
    """订单号存在但不属于当前会话用户时,不应泄露订单内容。"""
    session_response = await client.post("/api/v1/chat/session", json={})
    session_id = session_response.json()["session"]["session_id"]

    response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "查订单 ORDER99999999999"},
    )
    data = response.json()

    assert "未找到订单号" in data["response"]

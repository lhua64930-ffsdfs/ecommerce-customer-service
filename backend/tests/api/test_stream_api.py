"""SSE 聊天接口测试。"""
import httpx


async def test_chat_stream_returns_events_and_persists_messages(
    client: httpx.AsyncClient,
) -> None:
    session_response = await client.post("/api/v1/chat/session", json={})
    session_id = session_response.json()["session"]["session_id"]

    response = await client.post(
        "/api/v1/chat/send-stream",
        json={"session_id": session_id, "content": "商品可以退换吗"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert '"event": "meta"' in text
    assert '"event": "delta"' in text
    assert '"event": "done"' in text
    assert '"event": "error"' not in text

    history = await client.get(
        "/api/v1/chat/history", params={"session_id": session_id}
    )
    assert history.status_code == 200
    assert history.json()["total"] == 2

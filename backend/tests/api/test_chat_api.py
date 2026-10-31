"""对话接口集成测试(需要本地容器运行)。"""
import httpx
from langchain_core.messages import AIMessage

from app.api.deps import get_chat_model
from app.main import app
from tests.support.fake_chat_model import ScriptedChatModel


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
    assert rag_data["agent_mode"] == "single_step"
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
    # 测试默认不注入 ChatModel,订单查询走单步 fallback
    assert order_data["agent_mode"] == "single_step_fallback"

    transfer_response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "太差了我要投诉"},
    )
    transfer_data = transfer_response.json()
    assert transfer_data["sentiment"] == "negative"
    assert transfer_data["need_transfer"] is True
    assert transfer_data["agent_mode"] == "single_step"

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


async def test_order_query_uses_multi_step_agent(client: httpx.AsyncClient) -> None:
    """注入脚本化 ChatModel:订单查询走图,响应标记 multi_step。"""
    app.dependency_overrides[get_chat_model] = lambda: ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_order",
                        "args": {"order_no": "ORDER20260401001"},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="您的订单 ORDER20260401001 已支付,待发货。"),
        ]
    )

    session_response = await client.post("/api/v1/chat/session", json={})
    session_id = session_response.json()["session"]["session_id"]

    response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "查订单 ORDER20260401001"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_mode"] == "multi_step"
    assert data["tool_calls"] == [{"tool": "query_order", "success": True}]
    assert "ORDER20260401001" in data["response"]


async def test_multi_step_transfer_propagates_need_transfer(
    client: httpx.AsyncClient,
) -> None:
    """图内调用 transfer_human 时,响应 need_transfer 必须为真。"""
    app.dependency_overrides[get_chat_model] = lambda: ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "transfer_human",
                        "args": {"reason": "用户主动请求"},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="已为您转接人工客服,请稍候。"),
        ]
    )

    session_response = await client.post("/api/v1/chat/session", json={})
    session_id = session_response.json()["session"]["session_id"]

    response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "查订单 ORDER20260401001"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_mode"] == "multi_step"
    assert data["need_transfer"] is True
    assert data["tool_calls"] == [{"tool": "transfer_human", "success": True}]


async def test_order_query_falls_back_when_graph_fails(
    client: httpx.AsyncClient,
) -> None:
    """图执行失败时,同一请求回退单步 Agent,仍返回有用回复。"""
    app.dependency_overrides[get_chat_model] = lambda: ScriptedChatModel(
        fail_with="forced graph failure"
    )

    session_response = await client.post("/api/v1/chat/session", json={})
    session_id = session_response.json()["session"]["session_id"]

    response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "查订单 ORDER20260401001"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_mode"] == "single_step_fallback"
    assert data["tool_calls"] == [{"tool": "query_order", "success": True}]
    assert "ORDER20260401001" in data["response"]

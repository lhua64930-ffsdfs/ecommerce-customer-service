"""售后审批接口集成测试:申请、核验、审批、拒绝与幂等。"""
from __future__ import annotations

import httpx
from langchain_core.messages import AIMessage

from app.api.deps import get_chat_model
from app.main import app
from tests.support.fake_chat_model import ScriptedChatModel


def _use_scripted_agent(order_no: str, action: str) -> None:
    app.dependency_overrides[get_chat_model] = lambda: ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_order",
                        "args": {"order_no": order_no},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "propose_after_sales_action",
                        "args": {"action": action, "order_no": order_no},
                        "id": "call_2",
                    }
                ],
            ),
            AIMessage(content="已生成售后申请,请按提示确认或等待人工审核。"),
        ]
    )


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/api/v1/chat/session", json={})
    return response.json()["session"]["session_id"]


async def test_cancel_shipped_order_is_denied_by_policy(
    client: httpx.AsyncClient, demo_orders: dict[str, str]
) -> None:
    order_no = "ORDER20260315001"
    _use_scripted_agent(order_no, "cancel")
    session_id = await _create_session(client)

    response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": f"取消订单 {order_no}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["pending_approval"] is None
    assert data["tool_calls"][-1] == {
        "tool": "propose_after_sales_action",
        "success": True,
    }

    order = await client.get(f"/api/v1/order/{order_no}")
    assert order.json()["status"] == "shipped"


async def test_high_value_return_requires_human_review(
    client: httpx.AsyncClient, demo_orders: dict[str, str]
) -> None:
    order_no = "ORDER20260315001"
    _use_scripted_agent(order_no, "return")
    session_id = await _create_session(client)

    response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": f"查订单 {order_no} 然后退货"},
    )
    data = response.json()
    pending = data["pending_approval"]
    assert pending is not None
    assert pending["action"] == "return"
    assert pending["requires_human"] is True
    assert pending["risk_level"] == "high"

    verified = await client.post(
        "/api/v1/chat/verify-order",
        json={
            "session_id": session_id,
            "order_no": order_no,
            "phone_last4": "6789",
        },
    )
    assert verified.json()["success"] is True

    blocked = await client.post(
        f"/api/v1/chat/approvals/{pending['approval_id']}/approve",
        json={"session_id": session_id},
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "require_human_review"

    approved = await client.post(
        f"/api/v1/chat/approvals/{pending['approval_id']}/approve",
        json={"session_id": session_id, "reviewer": "A001"},
    )
    assert approved.status_code == 200
    assert approved.json()["success"] is True
    assert approved.json()["result"]["ticket_no"].startswith("TKT")


async def test_reject_approval_keeps_order_unchanged(
    client: httpx.AsyncClient, demo_orders: dict[str, str]
) -> None:
    order_no = "ORDER20260401001"
    _use_scripted_agent(order_no, "cancel")
    session_id = await _create_session(client)

    response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": f"取消订单 {order_no}"},
    )
    pending = response.json()["pending_approval"]
    assert pending is not None

    await client.post(
        "/api/v1/chat/verify-order",
        json={"session_id": session_id, "order_no": order_no, "phone_last4": "1234"},
    )
    rejected = await client.post(
        f"/api/v1/chat/approvals/{pending['approval_id']}/reject",
        json={"session_id": session_id, "reason": "用户改变主意"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    order = await client.get(f"/api/v1/order/{order_no}")
    assert order.json()["status"] == "paid"


async def test_approval_cannot_be_used_from_another_session(
    client: httpx.AsyncClient, demo_orders: dict[str, str]
) -> None:
    order_no = "ORDER20260401001"
    _use_scripted_agent(order_no, "cancel")
    owner_session = await _create_session(client)
    response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": owner_session, "content": f"取消订单 {order_no}"},
    )
    approval_id = response.json()["pending_approval"]["approval_id"]

    other_session = await _create_session(client)
    forbidden = await client.post(
        f"/api/v1/chat/approvals/{approval_id}/approve",
        json={"session_id": other_session},
    )
    assert forbidden.status_code == 404
    assert forbidden.json()["detail"]["code"] == "approval_not_found"


async def test_mock_offline_low_value_cancel_auto_executes_after_verification(
    client: httpx.AsyncClient, demo_orders: dict[str, str]
) -> None:
    """无 Key 时走单步离线模式,低风险取消核验后由策略自动执行。"""
    order_no = "ORDER20260320001"
    session_id = await _create_session(client)

    response = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": f"取消订单 {order_no}"},
    )
    data = response.json()
    assert data["agent_mode"] == "single_step"
    pending = data["pending_approval"]
    assert pending is not None
    assert pending["requires_verification"] is True

    await client.post(
        "/api/v1/chat/verify-order",
        json={"session_id": session_id, "order_no": order_no, "phone_last4": "1234"},
    )
    approved = await client.post(
        f"/api/v1/chat/approvals/{pending['approval_id']}/approve",
        json={"session_id": session_id},
    )
    assert approved.status_code == 200
    assert approved.json()["success"] is True

    order = await client.get(f"/api/v1/order/{order_no}")
    assert order.json()["status"] == "cancelled"

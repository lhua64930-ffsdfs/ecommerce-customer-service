"""MCP Server 拆分:知识/商品、订单/售后工具注册与委托。"""
from __future__ import annotations

from typing import Any

from app.mcp import aftersales_server, common, knowledge_server


async def test_servers_expose_split_tools() -> None:
    knowledge = await knowledge_server.mcp.list_tools()
    aftersales = await aftersales_server.mcp.list_tools()

    assert {tool.name for tool in knowledge} == {
        "search_knowledge",
        "query_product",
    }
    assert {tool.name for tool in aftersales} == {
        "query_order",
        "propose_after_sales_action",
        "transfer_human",
        "create_ticket",
    }


async def test_search_knowledge_delegates(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeSearchTool:
        async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
            captured.update(params)
            return {"success": True, "response": "ok", "results": []}

    monkeypatch.setattr(knowledge_server, "SearchKnowledgeTool", FakeSearchTool)

    result = await knowledge_server.search_knowledge(
        query="退货政策",
        category="政策",
        top_k=2,
        user_id=7,
        session_id="session-1",
        user_message="退货政策",
    )

    assert result["success"] is True
    assert captured["query"] == "退货政策"
    assert captured["category"] == "政策"
    assert captured["top_k"] == 2


async def test_aftersales_tool_injects_context(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_with_db(tool, params):
        captured.update(params)
        return {"success": True, "response": "ok"}

    monkeypatch.setattr(aftersales_server, "run_with_db", fake_run_with_db)

    result = await aftersales_server.query_order(
        order_no="ORDER20260401001",
        user_id=7,
        session_id="session-1",
        user_message="查订单",
    )

    assert result["success"] is True
    assert captured["user_id"] == 7
    assert captured["session_id"] == "session-1"
    assert captured["user_message"] == "查订单"


async def test_run_with_db_injects_session(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeSession:
        async def rollback(self) -> None:
            captured["rolled_back"] = True

    class FakeSessionFactory:
        async def __aenter__(self) -> FakeSession:
            return FakeSession()

        async def __aexit__(self, *args: object) -> bool:
            return False

    class FakeTool:
        async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
            captured.update(params)
            return {"success": True}

    monkeypatch.setattr(common, "AsyncSessionLocal", lambda: FakeSessionFactory())

    result = await common.run_with_db(FakeTool(), {"x": 1})

    assert result["success"] is True
    assert isinstance(captured["db"], FakeSession)
    assert captured["x"] == 1


async def test_health_routes() -> None:
    knowledge = await knowledge_server.health(None)  # type: ignore[arg-type]
    aftersales = await aftersales_server.health(None)  # type: ignore[arg-type]

    assert knowledge.status_code == 200
    assert b"after-sales-knowledge" in knowledge.body
    assert aftersales.status_code == 200
    assert b"after-sales-aftersales" in aftersales.body

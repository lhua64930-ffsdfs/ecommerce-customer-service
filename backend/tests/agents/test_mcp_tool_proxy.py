"""MCP 工具代理:Schema 隔离、上下文注入与传输失败回退。"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.agents.mcp import client as mcp_client
from app.agents.mcp.client import (
    McpToolProxy,
    _parse_tool_result,
    clear_tool_cache,
    refresh_mcp_tools,
)
from app.agents.tools.factory import build_default_tools, build_graph_tools
from app.agents.tools.registry import spec_from_tool
from tests.support.fake_chat_model import FakeOrderTool, FakeProposeTool


class ContextSchemaTool(FakeOrderTool):
    """模拟一个把上下文字段写进 Schema 的工具,验证代理会隐藏它们。"""

    def get_schema(self) -> dict[str, Any]:
        schema = super().get_schema()
        properties = schema["parameters"]["properties"]
        properties["user_id"] = {"type": "integer"}
        properties["session_id"] = {"type": "string"}
        schema["parameters"]["required"].append("user_id")
        return schema


def test_proxy_schema_hides_context_parameters() -> None:
    proxy = McpToolProxy(ContextSchemaTool(), server_url="http://mcp-test/mcp")

    properties = proxy.get_schema()["parameters"]["properties"]
    assert "order_no" in properties
    assert "user_id" not in properties
    assert "session_id" not in properties
    assert proxy.get_schema()["parameters"]["required"] == []


async def test_proxy_injects_context_and_parses_remote_result(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_call(server_url, tool_name, arguments, timeout):
        captured.update(
            {
                "server_url": server_url,
                "tool_name": tool_name,
                "arguments": arguments,
                "timeout": timeout,
            }
        )
        return {"success": True, "response": "远程查询成功"}

    monkeypatch.setattr(mcp_client, "call_remote_tool", fake_call)
    proxy = McpToolProxy(FakeOrderTool(), server_url="http://mcp-test/mcp")

    result = await proxy.execute(
        {
            "order_no": "ORDER20260401001",
            "user_id": 7,
            "session_id": "session-1",
            "user_message": "查订单",
            "db": object(),  # 本地 Session 不应跨进程序列化
        }
    )

    assert result == {
        "success": True,
        "response": "远程查询成功",
        "transport": "mcp",
    }
    assert captured["arguments"] == {
        "order_no": "ORDER20260401001",
        "user_id": 7,
        "session_id": "session-1",
        "user_message": "查订单",
    }
    assert captured["tool_name"] == "query_order"


async def test_transport_failure_falls_back_to_local(monkeypatch) -> None:
    async def boom(*args, **kwargs):
        raise ConnectionError("mcp server down")

    monkeypatch.setattr(mcp_client, "call_remote_tool", boom)
    tool = FakeOrderTool()
    proxy = McpToolProxy(tool, fallback_to_local=True)

    result = await proxy.execute({"order_no": "ORDER1", "user_id": 1})

    assert result["success"] is True
    assert result["transport"] == "local_fallback"
    assert tool.calls[0]["order_no"] == "ORDER1"


async def test_transport_failure_without_fallback_returns_error(monkeypatch) -> None:
    async def boom(*args, **kwargs):
        raise TimeoutError("timeout")

    monkeypatch.setattr(mcp_client, "call_remote_tool", boom)
    proxy = McpToolProxy(FakeOrderTool(), fallback_to_local=False)

    result = await proxy.execute({"order_no": "ORDER1", "user_id": 1})

    assert result["success"] is False
    assert result["error_code"] == "MCP_UNAVAILABLE"


def test_factory_wraps_tools_only_when_mcp_enabled() -> None:
    local_tools = build_graph_tools(use_mcp=False)
    mcp_tools = build_graph_tools(use_mcp=True)

    assert set(mcp_tools) == set(local_tools)
    assert not any(isinstance(tool, McpToolProxy) for tool in local_tools.values())
    assert all(isinstance(tool, McpToolProxy) for tool in mcp_tools.values())


def test_proxy_timeout_is_used_by_tool_spec_and_side_effects_do_not_retry() -> None:
    order_spec = spec_from_tool(McpToolProxy(FakeOrderTool(), timeout=33))
    assert order_spec.timeout == 33
    assert order_spec.max_retries == 1

    propose_spec = spec_from_tool(
        McpToolProxy(FakeProposeTool(), timeout=33)
    )
    assert propose_spec.timeout == 33
    assert propose_spec.max_retries == 0


async def test_side_effect_tool_does_not_fall_back_on_transport_error(
    monkeypatch,
) -> None:
    async def boom(*args, **kwargs):
        raise TimeoutError("ambiguous result")

    monkeypatch.setattr(mcp_client, "call_remote_tool", boom)
    tool = FakeProposeTool()
    proxy = McpToolProxy(tool, fallback_to_local=True)

    result = await proxy.execute({"action": "cancel", "user_id": 1})

    assert result["success"] is False
    assert result["error_code"] == "MCP_RESULT_UNKNOWN"
    assert tool.calls == []


async def test_refresh_uses_remote_schema_and_discovers_new_tool(
    monkeypatch,
) -> None:
    remote_schema = {
        "type": "object",
        "properties": {
            "order_no": {"type": "string", "description": "远程订单号"},
            "user_id": {"type": "integer"},
            "session_id": {"type": "string"},
        },
        "required": ["order_no", "user_id"],
    }

    async def fake_list(server_url, timeout):
        return [
            {
                "name": "query_order",
                "description": "远程订单工具",
                "input_schema": remote_schema,
            },
            {
                "name": "query_logistics",
                "description": "查物流",
                "input_schema": {
                    "type": "object",
                    "properties": {"tracking_no": {"type": "string"}},
                    "required": ["tracking_no"],
                },
            },
        ]

    monkeypatch.setattr(mcp_client, "list_remote_tools", fake_list)
    clear_tool_cache()

    tools = await refresh_mcp_tools(
        build_default_tools(use_mcp=False), timeout=1, cache_ttl=0
    )

    order_schema = tools["query_order"].get_schema()
    assert order_schema["description"] == "远程订单工具"
    assert set(order_schema["parameters"]["properties"]) == {"order_no"}
    assert order_schema["parameters"]["required"] == ["order_no"]
    assert "query_logistics" in tools

    calls: dict[str, Any] = {}

    async def fake_call(server_url, tool_name, arguments, timeout):
        calls.update({"tool": tool_name, "arguments": arguments})
        return {"success": True, "response": "远程物流"}

    monkeypatch.setattr(mcp_client, "call_remote_tool", fake_call)
    result = await tools["query_logistics"].execute(
        {"tracking_no": "SF1", "user_id": 7, "session_id": "s1"}
    )

    assert result["transport"] == "mcp"
    assert calls["tool"] == "query_logistics"
    assert calls["arguments"]["tracking_no"] == "SF1"


async def test_refresh_falls_back_to_local_schema_when_catalog_fails(
    monkeypatch,
) -> None:
    async def broken_list(server_url, timeout):
        raise ConnectionError("catalog down")

    monkeypatch.setattr(mcp_client, "list_remote_tools", broken_list)
    clear_tool_cache()

    tools = await refresh_mcp_tools(
        build_default_tools(use_mcp=False), timeout=1, cache_ttl=0
    )

    schema = tools["query_order"].get_schema()
    assert "order_no" in schema["parameters"]["properties"]
    assert "user_id" not in schema["parameters"]["properties"]


async def test_tool_catalog_is_cached(monkeypatch) -> None:
    calls = {"count": 0}

    async def fake_list(server_url, timeout):
        calls["count"] += 1
        return []

    monkeypatch.setattr(mcp_client, "list_remote_tools", fake_list)
    clear_tool_cache()
    local_tools = build_default_tools(use_mcp=False)

    await refresh_mcp_tools(local_tools, timeout=1, cache_ttl=60)
    await refresh_mcp_tools(local_tools, timeout=1, cache_ttl=60)
    assert calls["count"] == 2  # knowledge + aftersales 各一次

    clear_tool_cache()
    await refresh_mcp_tools(local_tools, timeout=1, cache_ttl=60)
    assert calls["count"] == 4


def test_parse_tool_result_reads_json_text() -> None:
    result = SimpleNamespace(
        is_error=False,
        content=[SimpleNamespace(text='{"success": true, "response": "ok"}')],
        structured_content=None,
    )

    assert _parse_tool_result(result) == {"success": True, "response": "ok"}


def test_parse_tool_result_marks_error() -> None:
    result = SimpleNamespace(
        is_error=True,
        content=[SimpleNamespace(text='{"response": "bad request"}')],
        structured_content=None,
    )

    payload = _parse_tool_result(result)
    assert payload["success"] is False
    assert payload["response"] == "bad request"

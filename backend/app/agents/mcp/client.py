"""MCP 工具代理:把远程 MCP 工具伪装成本地工具对象。

设计要点(参考工具系统设计):
- 模型侧 Schema 优先用 Server 动态清单,本地 Schema 只是兜底;
- 执行时由 ``ToolContext`` 注入请求身份,上下文参数不暴露给模型;
- 只有幂等只读工具允许在传输失败时回退本地;写/申请/转人工可能已执行,
  超时回退会制造重复工单/审批,因此一律返回「结果未知」。
"""
from __future__ import annotations

import asyncio
import copy
import json
import time
from typing import Any

from app.core.config import settings
from app.utils.logger import logger

# 由后端注入、不来自模型参数的上下文字段
MCP_CONTEXT_KEYS = frozenset({"user_id", "session_id", "user_message"})
# AsyncSession 不能序列化,只留在本地进程
_MCP_LOCAL_ONLY_KEYS = frozenset({"db"})
# 只有这些幂等只读工具允许「远程失败 → 本地重跑」
_SAFE_FALLBACK_TOOLS = frozenset(
    {"search_knowledge", "query_order", "query_product"}
)
# 多 Server:知识/商品、订单/售后
_KNOWLEDGE_TOOLS = frozenset({"search_knowledge", "query_product"})
_DEFAULT_SERVER_BY_TOOL: dict[str, str] = {
    name: ("knowledge" if name in _KNOWLEDGE_TOOLS else "aftersales")
    for name in (
        "search_knowledge",
        "query_product",
        "query_order",
        "propose_after_sales_action",
        "transfer_human",
        "create_ticket",
    )
}

# server_url -> (expires_at, tools)
_tool_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _parse_tool_result(result: Any) -> dict[str, Any]:
    """解析 CallToolResult:MCP 2.x 把 dict 返回值序列化在 text content 里。"""
    is_error = bool(getattr(result, "is_error", False))
    texts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            texts.append(str(text))

    for text in texts:
        try:
            parsed = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            if is_error:
                parsed.setdefault("success", False)
            return parsed

    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        if is_error:
            structured.setdefault("success", False)
        return structured

    if texts:
        return {
            "success": not is_error,
            "response": "\n".join(texts),
        }
    return {
        "success": False,
        "response": "MCP 工具返回空结果",
        "error_code": "MCP_EMPTY_RESULT",
    }


def _tool_input_schema(tool: Any) -> dict[str, Any]:
    """兼容 MCP 2.x 的 input_schema 与旧版 inputSchema。"""
    schema = getattr(tool, "input_schema", None)
    if schema is None:
        schema = getattr(tool, "inputSchema", None)
    return schema if isinstance(schema, dict) else {}


async def call_remote_tool(
    server_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """通过 Streamable HTTP 调用一次远程工具;每次调用独立会话。"""

    async def _call() -> dict[str, Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(server_url) as (
            read_stream,
            write_stream,
        ), ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
        return _parse_tool_result(result)

    return await asyncio.wait_for(_call(), timeout=timeout)


async def list_remote_tools(
    server_url: str, timeout: float = 5.0
) -> list[dict[str, Any]]:
    """拉取 Server 工具清单:名称、描述、参数 Schema。"""

    async def _list() -> list[dict[str, Any]]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(server_url) as (
            read_stream,
            write_stream,
        ), ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()

        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": _tool_input_schema(tool),
            }
            for tool in getattr(result, "tools", None) or []
        ]

    return await asyncio.wait_for(_list(), timeout=timeout)


def clear_tool_cache() -> None:
    """清空动态清单缓存(测试或 Server 热更新后手动刷新)。"""
    _tool_cache.clear()


async def _get_remote_tools(
    server_url: str, timeout: float, cache_ttl: float
) -> list[dict[str, Any]]:
    now = time.monotonic()
    cached = _tool_cache.get(server_url)
    if cache_ttl > 0 and cached is not None and now < cached[0]:
        return cached[1]

    tools = await list_remote_tools(server_url, timeout=timeout)
    if cache_ttl > 0:
        _tool_cache[server_url] = (time.monotonic() + cache_ttl, tools)
    return tools


def mcp_connections() -> dict[str, str]:
    """当前配置的 MCP Server 名称 -> URL。"""
    return {
        "knowledge": settings.MCP_KNOWLEDGE_URL,
        "aftersales": settings.MCP_AFTERSALES_URL,
    }


class McpToolProxy:
    """本地工具对象的远程代理:执行远程、Schema 可动态刷新、失败按风险回退。"""

    def __init__(
        self,
        local_tool: Any | None = None,
        *,
        name: str | None = None,
        description: str = "",
        remote_schema: dict[str, Any] | None = None,
        server_url: str | None = None,
        server_name: str = "",
        timeout: float | None = None,
        fallback_to_local: bool | None = None,
    ) -> None:
        local_schema = local_tool.get_schema() if local_tool is not None else {}
        self.name = (
            name
            or local_schema.get("name")
            or getattr(local_tool, "name", "unknown")
        )
        self.description = (
            description
            or local_schema.get("description", "")
            or getattr(local_tool, "description", "")
        )
        self._local_tool = local_tool
        self._remote_schema = remote_schema
        self.server_name = server_name
        self._server_url = server_url or settings.MCP_AFTERSALES_URL
        self._timeout = settings.MCP_TIMEOUT if timeout is None else timeout
        # 供 tool_adapters 读取:执行引擎的外层超时不能短于 MCP 代理超时
        self.timeout = self._timeout
        self._fallback_to_local = (
            settings.MCP_FALLBACK_TO_LOCAL
            if fallback_to_local is None
            else fallback_to_local
        )

    def get_schema(self) -> dict[str, Any]:
        """返回模型可见 Schema;上下文参数永远隐藏在代理内部。"""
        if self._remote_schema:
            schema: dict[str, Any] = {
                "name": self.name,
                "description": self.description,
                "parameters": copy.deepcopy(self._remote_schema),
            }
        elif self._local_tool is not None:
            schema = copy.deepcopy(self._local_tool.get_schema())
        else:
            schema = {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}},
            }

        parameters = schema.setdefault("parameters", {})
        properties = parameters.get("properties")
        if isinstance(properties, dict):
            for key in MCP_CONTEXT_KEYS:
                properties.pop(key, None)
        required = parameters.get("required")
        if isinstance(required, list):
            parameters["required"] = [
                key for key in required if key not in MCP_CONTEXT_KEYS
            ]
        return schema

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """调用远程 MCP 工具;仅幂等只读工具允许回退本地。"""
        arguments = {
            key: value
            for key, value in params.items()
            if key not in _MCP_LOCAL_ONLY_KEYS and value is not None
        }
        try:
            payload = await call_remote_tool(
                self._server_url,
                self.name,
                arguments,
                self._timeout,
            )
        except Exception as exc:  # noqa: BLE001 - 传输/协议错误统一分诊
            logger.warning(
                "MCP 工具 {} 调用失败({}): {}",
                self.name,
                self._server_url,
                exc,
            )
            safe_to_fallback = (
                self._local_tool is not None
                and self.name in _SAFE_FALLBACK_TOOLS
            )
            if not safe_to_fallback:
                return {
                    "success": False,
                    "response": (
                        f"MCP 工具 {self.name} 调用结果未知。"
                        "为避免重复创建工单/审批,未回退本地执行;"
                        "请稍后查询确认后再决定是否重试。"
                    ),
                    "error_code": "MCP_RESULT_UNKNOWN",
                }
            if not self._fallback_to_local:
                return {
                    "success": False,
                    "response": f"MCP 工具 {self.name} 暂时不可用,请稍后重试",
                    "error_code": "MCP_UNAVAILABLE",
                }
            result = dict(await self._local_tool.execute(params))
            result["transport"] = "local_fallback"
            return result

        if isinstance(payload, dict):
            payload = dict(payload)
            payload["transport"] = "mcp"
            return payload
        return {
            "success": False,
            "response": f"MCP 工具 {self.name} 返回了无法解析的结果",
            "error_code": "MCP_INVALID_RESULT",
        }


def build_mcp_proxies(
    local_tools: dict[str, Any],
    remote_specs: dict[str, dict[str, Any]] | None = None,
    servers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """把本地工具与多 Server 清单合并成代理;失败在调用时分诊。"""
    remote_specs = remote_specs or {}
    servers = servers or mcp_connections()
    proxies: dict[str, Any] = {}

    for name, tool in local_tools.items():
        spec = remote_specs.get(name) or {}
        server_name = spec.get("server_name") or _DEFAULT_SERVER_BY_TOOL.get(
            name, "aftersales"
        )
        proxies[name] = McpToolProxy(
            tool,
            remote_schema=spec.get("input_schema"),
            description=spec.get("description") or "",
            server_url=spec.get("server_url") or servers.get(server_name),
            server_name=server_name,
        )

    # Server 新增、本地还没有实现的工具:注册成纯远程代理
    for name, spec in remote_specs.items():
        if name in proxies:
            continue
        server_name = spec.get("server_name", "")
        proxies[name] = McpToolProxy(
            None,
            name=name,
            description=spec.get("description") or "",
            remote_schema=spec.get("input_schema"),
            server_url=spec.get("server_url")
            or servers.get(server_name)
            or settings.MCP_AFTERSALES_URL,
            server_name=server_name,
        )
    return proxies


async def refresh_mcp_tools(
    local_tools: dict[str, Any],
    servers: dict[str, str] | None = None,
    timeout: float | None = None,
    cache_ttl: float | None = None,
) -> dict[str, Any]:
    """按多 Server 动态清单重建代理;单台失败只跳过该台。"""
    servers = servers or mcp_connections()
    if not settings.MCP_DYNAMIC_TOOLS:
        return build_mcp_proxies(local_tools, servers=servers)

    remote_specs: dict[str, dict[str, Any]] = {}
    for server_name, server_url in servers.items():
        try:
            remote_tools = await _get_remote_tools(
                server_url,
                timeout=(
                    settings.MCP_DISCOVERY_TIMEOUT
                    if timeout is None
                    else timeout
                ),
                cache_ttl=(
                    settings.MCP_TOOL_CACHE_TTL
                    if cache_ttl is None
                    else cache_ttl
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 单台不可达不阻断对话
            logger.warning(
                "MCP Server「{}」清单拉取失败,本轮跳过: {}",
                server_name,
                exc,
            )
            continue
        for item in remote_tools:
            if not item.get("name"):
                continue
            spec = dict(item)
            spec["server_name"] = server_name
            spec["server_url"] = server_url
            remote_specs[item["name"]] = spec

    return build_mcp_proxies(
        local_tools, remote_specs=remote_specs, servers=servers
    )

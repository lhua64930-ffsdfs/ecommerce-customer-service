"""MCP 工具客户端适配层。"""
from app.agents.mcp.client import McpToolProxy, build_mcp_proxies

__all__ = ["McpToolProxy", "build_mcp_proxies"]

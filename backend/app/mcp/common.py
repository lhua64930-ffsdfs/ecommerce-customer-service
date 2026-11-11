"""MCP Server 公共构造:健康检查、DB 会话与启动参数。"""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.database import AsyncSessionLocal


def create_server(name: str, instructions: str) -> MCPServer:
    return MCPServer(
        name=name,
        version=settings.VERSION,
        instructions=instructions,
    )


def add_health_route(mcp: MCPServer, service: str) -> Any:
    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {"status": "ok", "service": service, "version": settings.VERSION}
        )

    return health


async def run_with_db(tool: Any, params: dict[str, Any]) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        try:
            return await tool.execute({**params, "db": db})
        except Exception:
            await db.rollback()
            raise


def run_server(mcp: MCPServer, port: int) -> None:
    mcp.run(
        transport="streamable-http",
        host=settings.MCP_SERVER_HOST,
        port=port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )

"""知识 / 商品 MCP Server。"""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

import app.models  # noqa: F401 - 注册全部 ORM 模型
from app.agents.tools.query_product import QueryProductTool
from app.agents.tools.search_knowledge import SearchKnowledgeTool
from app.core.config import settings
from app.mcp.common import (
    add_health_route,
    create_server,
    run_server,
    run_with_db,
)
from app.utils.logger import logger

UserId = Annotated[int | None, Field(description="内部上下文:用户 ID")]
SessionId = Annotated[str, Field(description="内部上下文:会话 ID")]
UserMessage = Annotated[str, Field(description="内部上下文:原始用户消息")]

mcp = create_server(
    "after-sales-knowledge",
    "售后智答知识/商品工具服务;调用方注入 user_id / session_id。",
)


@mcp.tool(name="search_knowledge")
async def search_knowledge(
    query: Annotated[str, Field(description="用户的查询问题")],
    category: Annotated[str | None, Field(description="知识库分类(可选)")] = None,
    top_k: Annotated[int, Field(description="返回结果数量,默认 3")] = 3,
    user_id: UserId = None,
    session_id: SessionId = "",
    user_message: UserMessage = "",
) -> dict[str, Any]:
    """从知识库检索答案、来源与相似度。"""
    logger.info("MCP knowledge.search user={} session={}", user_id, session_id)
    return await SearchKnowledgeTool().execute(
        {
            "query": query,
            "category": category,
            "top_k": top_k,
            "user_message": user_message,
        }
    )


@mcp.tool(name="query_product")
async def query_product(
    keywords: Annotated[str, Field(description="商品关键词")],
    category: Annotated[str | None, Field(description="商品分类(可选)")] = None,
    user_id: UserId = None,
    session_id: SessionId = "",
    user_message: UserMessage = "",
) -> dict[str, Any]:
    """按关键词查询商品价格、库存与详情。"""
    logger.info("MCP knowledge.product user={} session={}", user_id, session_id)
    return await run_with_db(
        QueryProductTool(),
        {
            "keywords": keywords,
            "category": category,
            "user_id": user_id,
            "session_id": session_id,
            "user_message": user_message,
        },
    )


health = add_health_route(mcp, "after-sales-knowledge")


def main() -> None:
    logger.info("Knowledge MCP Server 启动: {}", settings.MCP_KNOWLEDGE_PORT)
    run_server(mcp, settings.MCP_KNOWLEDGE_PORT)


if __name__ == "__main__":
    main()

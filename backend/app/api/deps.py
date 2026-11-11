"""FastAPI 依赖注入。"""
from fastapi import Depends, HTTPException, Request
from langchain_core.language_models import BaseChatModel

from app.agents.graph.chat_model import create_chat_model
from app.agents.graph.checkpointer import get_checkpointer
from app.agents.graph.multi_step_agent import MultiStepAgent
from app.agents.tools.factory import build_graph_tools
from app.core import circuit
from app.core.config import settings
from app.core.database import get_db


def get_chat_model() -> BaseChatModel | None:
    """多步 Agent 使用的 ChatModel;未配置 Key 时返回 None。"""
    return create_chat_model()


def get_multi_step_agent(
    chat_model: BaseChatModel | None = Depends(get_chat_model),  # noqa: B008
) -> MultiStepAgent | None:
    """构造多步 Agent;测试可覆盖 get_chat_model 注入脚本化模型。"""
    if chat_model is None:
        return None
    saver = get_checkpointer()
    tools = build_graph_tools()
    if saver is not None:
        # 有 checkpointer 才暴露工单写工具,由 confirm_ticket gate 把关
        from app.agents.tools.create_ticket import CreateTicketTool

        tools["create_ticket"] = CreateTicketTool()
    return MultiStepAgent(
        chat_model=chat_model,
        tools=tools,
        breaker=circuit.chat_breaker,
        checkpointer=saver,
    )


def require_roles(*roles: str):
    """RBAC 依赖:鉴权关闭时按本地管理员放行,开启后必须命中角色。"""

    async def dependency(request: Request) -> dict:
        if not settings.AUTH_ENABLED:
            return {"user_id": None, "username": "local", "roles": ["admin"]}
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="未登录")
        if roles and not set(roles) & set(user.get("roles", [])):
            raise HTTPException(status_code=403, detail="权限不足")
        return user

    return dependency


async def require_admin(request: Request) -> dict:
    return await require_roles("admin")(request)


__all__ = [
    "get_chat_model",
    "get_db",
    "get_multi_step_agent",
    "require_admin",
    "require_roles",
]

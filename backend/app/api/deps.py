"""FastAPI 依赖注入。"""
from fastapi import Depends
from langchain_core.language_models import BaseChatModel

from app.agents.graph.chat_model import create_chat_model
from app.agents.graph.multi_step_agent import MultiStepAgent
from app.agents.tools.factory import build_default_tools
from app.core.database import get_db


def get_chat_model() -> BaseChatModel | None:
    """多步 Agent 使用的 ChatModel;未配置 Key 时返回 None。"""
    return create_chat_model()


def get_multi_step_agent(
    chat_model: BaseChatModel | None = Depends(get_chat_model),
) -> MultiStepAgent | None:
    """构造多步 Agent;测试可覆盖 get_chat_model 注入脚本化模型。"""
    if chat_model is None:
        return None
    return MultiStepAgent(chat_model=chat_model, tools=build_default_tools())


__all__ = ["get_chat_model", "get_db", "get_multi_step_agent"]

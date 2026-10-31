"""多步 Agent 的 ChatModel 工厂(DeepSeek,OpenAI 兼容协议)。

API Key 只从配置(环境变量 / backend/.env)读取;未配置时返回 ``None``,
调用方据此走单步 fallback,不会发起任何外部请求。
"""
from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from app.core.config import settings
from app.utils.logger import logger


@lru_cache(maxsize=1)
def create_chat_model() -> BaseChatModel | None:
    """创建 LangChain ChatModel;未配置 Key 或 mock 模式返回 None。"""
    api_key = (settings.LLM_API_KEY or "").strip()
    if settings.LLM_PROVIDER.lower() == "mock" or not api_key:
        logger.debug("LLM API Key 未配置,多步 Agent 将回退单步 Agent")
        return None

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=api_key,
        base_url=settings.LLM_API_BASE,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
        timeout=settings.LLM_TIMEOUT,
        max_retries=0,
    )

"""LLM 服务:对接 DeepSeek(OpenAI 兼容协议)。

设计要点:
1. 单例:整个进程复用一个 AsyncOpenAI 客户端(连接池复用)。
2. mock 降级:未配置 API Key 时返回可预测的演示文本,保证其他链路可开发。
3. 并发限制 + 指数退避重试:避免瞬时打爆上游。
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from app.core.config import settings
from app.utils.logger import logger


class LLMError(RuntimeError):
    """LLM 调用失败。"""


class LLMService:
    """大语言模型服务(单例)。"""

    _instance: "LLMService | None" = None

    def __new__(cls) -> "LLMService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self.provider = settings.LLM_PROVIDER.lower()
        self.api_key = (settings.LLM_API_KEY or "").strip()
        self.model = settings.LLM_MODEL
        self.is_mock = self.provider == "mock" or not self.api_key
        self._client: Any = None
        self._semaphore: asyncio.Semaphore | None = None

        if self.is_mock:
            logger.warning("LLM API Key 未配置,已启用 mock 模式(可继续开发与测试)")
        else:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=settings.LLM_API_BASE,
                timeout=settings.LLM_TIMEOUT,
                max_retries=0,  # 重试由本类控制
            )
            logger.info("LLM 初始化完成: provider={} model={}", self.provider, self.model)

    def _get_semaphore(self) -> asyncio.Semaphore:
        # 延迟创建,确保绑定到当前事件循环
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)
        return self._semaphore

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """对话补全,返回文本内容。

        Raises:
            LLMError: 重试后仍失败
        """
        if self.is_mock:
            return self._mock_reply(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
            "max_tokens": settings.LLM_MAX_TOKENS if max_tokens is None else max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with self._get_semaphore():
                    response = await self._client.chat.completions.create(**kwargs)
                content = (response.choices[0].message.content or "").strip()
                if content:
                    return content
                raise LLMError("LLM 返回内容为空")
            except Exception as exc:  # noqa: BLE001 - 上游异常类型较多
                last_error = exc
                wait = min(2**attempt, 8)
                logger.warning("LLM 调用失败(第 {} 次): {}, {}s 后重试", attempt + 1, exc, wait)
                await asyncio.sleep(wait)

        raise LLMError(f"LLM 调用失败: {last_error}")

    async def generate(
        self,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """单轮文本生成。"""
        return await self.chat(
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """流式对话(供 WebSocket / SSE 使用)。"""
        if self.is_mock:
            for chunk in self._mock_reply(messages):
                yield chunk
            return

        async with self._get_semaphore():
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
                stream=True,
            )
            async for event in stream:
                delta = event.choices[0].delta.content if event.choices else None
                if delta:
                    yield delta

    # ---------------- mock 模式 ----------------
    def _mock_reply(self, messages: list[dict[str, str]]) -> str:
        """无 API Key 时的确定性回复,便于开发联调。"""
        prompt = messages[-1].get("content", "") if messages else ""

        # 意图识别请求 → 返回合法 JSON
        if "intent_code" in prompt:
            return '{"intent_code": "fallback", "confidence": 0.5}'

        # RAG 回答 → 尽量复用知识库中的答案
        if "知识库" in prompt and "答案" in prompt:
            for line in prompt.splitlines():
                stripped = line.strip()
                if stripped.startswith("答案"):
                    value = stripped.split(":", 1)[-1].split("：", 1)[-1].strip()
                    if value:
                        return value
            return "根据平台规则:7天内可无理由退换货,15天内可申请质量问题退换货。"

        return (
            "您好,我是智能客服小e(当前为离线演示模式)。"
            "已收到您的问题,我会尽力为您解答;如需真实大模型回复,请在 .env 中配置 LLM_API_KEY。"
        )


def get_llm_service() -> LLMService:
    """获取 LLM 服务单例(供依赖注入使用)。"""
    return LLMService()

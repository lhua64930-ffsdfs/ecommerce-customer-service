"""上游调用熔断:失败达阈值断路,冷却后放一个试探(半开)。

只保护「上游不可用」这类连续失败;业务异常由调用方自己处理。
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings
from app.utils.logger import logger


class CircuitOpenError(RuntimeError):
    """熔断器打开,本次调用未发往上游。"""

    def __init__(self, name: str) -> None:
        super().__init__(f"upstream circuit open: {name}")
        self.name = name


class CircuitBreaker:
    """closed → open → half_open → closed 的轻量熔断器。"""

    def __init__(
        self,
        name: str,
        threshold: int | None = None,
        recovery: float | None = None,
    ) -> None:
        self.name = name
        self.threshold = (
            settings.CIRCUIT_FAILURE_THRESHOLD
            if threshold is None
            else threshold
        )
        self.recovery = (
            settings.CIRCUIT_RECOVERY_SECONDS
            if recovery is None
            else recovery
        )
        self._failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False
        self.state = "closed"

    def reset(self) -> None:
        self._failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False
        self.state = "closed"

    async def call(
        self,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if not settings.CIRCUIT_BREAKER_ENABLED:
            return await fn(*args, **kwargs)

        if self.state == "open":
            if time.monotonic() - self._opened_at >= self.recovery:
                self.state = "half_open"
            else:
                raise CircuitOpenError(self.name)

        if self.state == "half_open":
            # 半开只放一个探针,避免并发请求同时打向未恢复的上游
            if self._probe_in_flight:
                raise CircuitOpenError(self.name)
            self._probe_in_flight = True

        try:
            result = await fn(*args, **kwargs)
        except Exception:
            self._failures += 1
            if self.state == "half_open" or self._failures >= self.threshold:
                self.state = "open"
                self._opened_at = time.monotonic()
                logger.warning(
                    "上游熔断打开: {} failures={}", self.name, self._failures
                )
            raise
        else:
            self._failures = 0
            self.state = "closed"
            return result
        finally:
            self._probe_in_flight = False


chat_breaker = CircuitBreaker("chat")
embed_breaker = CircuitBreaker("embed")
rerank_breaker = CircuitBreaker("rerank")

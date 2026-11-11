"""熔断器:失败开断、冷却半开、关闭时透传。"""
from __future__ import annotations

import pytest

from app.core.circuit import CircuitBreaker, CircuitOpenError
from app.core.config import settings


async def test_breaker_opens_then_half_open_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CIRCUIT_BREAKER_ENABLED", True)
    breaker = CircuitBreaker("test-recover", threshold=2, recovery=0)

    async def fail() -> None:
        raise RuntimeError("upstream down")

    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    assert breaker.state == "open"

    async def ok() -> str:
        return "ok"

    # recovery=0:下一次调用进入 half_open,成功即恢复
    assert await breaker.call(ok) == "ok"
    assert breaker.state == "closed"


async def test_breaker_rejects_while_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CIRCUIT_BREAKER_ENABLED", True)
    breaker = CircuitBreaker("test-open", threshold=1, recovery=3600)

    async def fail() -> None:
        raise RuntimeError("upstream down")

    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    with pytest.raises(CircuitOpenError):
        await breaker.call(fail)


async def test_breaker_disabled_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CIRCUIT_BREAKER_ENABLED", False)
    breaker = CircuitBreaker("test-disabled", threshold=1)

    async def fail() -> None:
        raise RuntimeError("expected")

    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    assert breaker.state == "closed"

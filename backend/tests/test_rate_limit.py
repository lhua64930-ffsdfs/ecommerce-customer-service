"""限流实现单测:验证滑动窗口会自然过期,不会永久 429。"""
from __future__ import annotations

import uuid

import pytest

from app.core.config import settings
from app.utils.cache import (
    clear_memory_rate_limit,
    get_redis,
    record_rate_hit,
)


async def _redis_available() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:  # noqa: BLE001 - 没有 Redis 时跳过
        return False


async def test_sliding_window_counts_and_rejects_over_limit() -> None:
    if not await _redis_available():
        pytest.skip("Redis 不可用")

    key = f"test:rate:{uuid.uuid4().hex}"
    try:
        assert await record_rate_hit(key, limit=2, now=1000.0) == 1
        assert await record_rate_hit(key, limit=2, now=1000.1) == 2
        # 超限后不再写入,计数保持在 limit + 1
        assert await record_rate_hit(key, limit=2, now=1000.2) == 3
        assert await record_rate_hit(key, limit=2, now=1000.3) == 3
    finally:
        await get_redis().delete(key)


async def test_sliding_window_expires_old_requests() -> None:
    if not await _redis_available():
        pytest.skip("Redis 不可用")

    key = f"test:rate:{uuid.uuid4().hex}"
    try:
        await record_rate_hit(key, limit=2, now=1000.0)
        await record_rate_hit(key, limit=2, now=1000.0)
        assert await record_rate_hit(key, limit=2, now=1000.0) == 3

        # 窗口滚动后旧记录被清理,不会因为持续请求永久 429
        assert await record_rate_hit(key, limit=2, now=1061.0) == 1
        assert await record_rate_hit(key, limit=2, now=1061.1) == 2

        ttl = await get_redis().pttl(key)
        assert ttl > 0
    finally:
        await get_redis().delete(key)


async def test_rate_limit_fails_open_without_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomClient:
        async def eval(self, *args: object, **kwargs: object) -> None:
            raise ConnectionError("redis down")

    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr("app.utils.cache.get_redis", lambda: _BoomClient())

    assert await record_rate_hit("test:rate:down", limit=1) is None


async def test_memory_backend_counts_and_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "memory")
    clear_memory_rate_limit()
    key = f"test:rate:memory:{uuid.uuid4().hex}"

    assert await record_rate_hit(key, limit=2, now=1000.0) == 1
    assert await record_rate_hit(key, limit=2, now=1000.1) == 2
    assert await record_rate_hit(key, limit=2, now=1000.2) == 3
    assert await record_rate_hit(key, limit=2, now=1000.3) == 3
    # 窗口滚动后旧记录被清理
    assert await record_rate_hit(key, limit=2, now=1061.0) == 1


async def test_auto_backend_falls_back_to_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BoomClient:
        async def eval(self, *args: object, **kwargs: object) -> None:
            raise ConnectionError("redis down")

    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "auto")
    monkeypatch.setattr("app.utils.cache.get_redis", lambda: _BoomClient())
    clear_memory_rate_limit()
    key = f"test:rate:auto:{uuid.uuid4().hex}"

    assert await record_rate_hit(key, limit=1, now=1000.0) == 1
    assert await record_rate_hit(key, limit=1, now=1000.1) == 2

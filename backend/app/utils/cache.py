"""Redis 缓存工具。

所有方法在 Redis 不可用时静默降级(返回 None / 不抛异常),
避免缓存故障拖垮主流程。
"""
from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from app.core.config import settings
from app.utils.logger import logger

_client: Any = None
_redis_unavailable_until = 0.0
_redis_warned = False
# 进程内滑动窗口:Redis 未配置(auto + 空 URL)或 Redis 故障时降级使用
_memory_hits: dict[str, deque[float]] = defaultdict(deque)


def redis_configured() -> bool:
    return bool(settings.REDIS_URL)


def reset_redis_state() -> None:
    """重置冷却/告警状态(测试或运维手动恢复)。"""
    global _redis_unavailable_until, _redis_warned
    _redis_unavailable_until = 0.0
    _redis_warned = False


def _mark_redis_unavailable(exc: Exception) -> None:
    global _redis_unavailable_until, _redis_warned
    if time.monotonic() < _redis_unavailable_until:
        return
    _redis_unavailable_until = (
        time.monotonic() + settings.REDIS_RETRY_COOLDOWN_SECONDS
    )
    if not _redis_warned:
        logger.warning(
            "Redis 不可用,{}s 内降级: {}",
            settings.REDIS_RETRY_COOLDOWN_SECONDS,
            exc,
        )
        _redis_warned = True


def _mark_redis_available() -> None:
    global _redis_unavailable_until, _redis_warned
    _redis_unavailable_until = 0.0
    _redis_warned = False


def clear_memory_rate_limit() -> None:
    """清空进程内限流窗口(测试用)。"""
    _memory_hits.clear()


def get_redis() -> Any:
    """获取 Redis 异步客户端;未配置或冷却中直接抛错,由调用方降级。"""
    global _client
    if not settings.REDIS_URL:
        raise RuntimeError("Redis 未配置")
    if time.monotonic() < _redis_unavailable_until:
        raise ConnectionError("Redis 冷却中")

    if _client is None:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def cache_get(key: str) -> str | None:
    if not redis_configured():
        return None
    try:
        value = await get_redis().get(key)
        _mark_redis_available()
        return value
    except Exception as exc:  # noqa: BLE001
        _mark_redis_unavailable(exc)
        return None


async def cache_set(key: str, value: str, ttl: int = 3600) -> bool:
    if not redis_configured():
        return False
    try:
        await get_redis().set(key, value, ex=ttl)
        _mark_redis_available()
        return True
    except Exception as exc:  # noqa: BLE001
        _mark_redis_unavailable(exc)
        return False


async def cache_delete(key: str) -> None:
    if not redis_configured():
        return
    try:
        await get_redis().delete(key)
        _mark_redis_available()
    except Exception as exc:  # noqa: BLE001
        _mark_redis_unavailable(exc)


async def cache_get_json(key: str) -> Any | None:
    raw = await cache_get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def cache_set_json(key: str, value: Any, ttl: int = 3600) -> bool:
    return await cache_set(key, json.dumps(value, ensure_ascii=False), ttl)


# 原子滑动窗口限流:
# 1. 移除窗口外的旧记录;
# 2. 统计窗口内请求数;
# 3. 未超限则写入当前请求,并刷新整个 key 的 TTL。
# 使用 Lua 保证「清理 + 计数 + 写入」不被并发请求穿插。
# 与旧实现 INCR + EXPIRE 的区别:TTL 只随窗口滚动,不会因为持续请求
# 被无限刷新,因此不会出现计数永不过期、达到上限后永久 429 的问题。
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
    return count + 1
end

redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window * 1000 + 1000)
return count + 1
"""


def _memory_rate_hit(
    key: str,
    limit: int,
    window_seconds: int,
    burst: int,
    now: float | None = None,
) -> int:
    """进程内滑动窗口;多副本不共享,单机/降级场景使用。"""
    current = time.time() if now is None else now
    window = _memory_hits[key]
    while window and current - window[0] >= window_seconds:
        window.popleft()

    capacity = limit + max(0, burst)
    if len(window) >= capacity:
        return len(window) + 1
    window.append(current)

    # 防止任意 session_id / IP 无限增长:超阈值时清理过期 key
    if len(_memory_hits) > settings.RATE_LIMIT_MAX_KEYS:
        for existing_key in list(_memory_hits):
            bucket = _memory_hits[existing_key]
            while bucket and current - bucket[0] >= window_seconds:
                bucket.popleft()
            if not bucket:
                del _memory_hits[existing_key]
    return len(window)


async def record_rate_hit(
    key: str,
    limit: int,
    window_seconds: int = 60,
    now: float | None = None,
    burst: int = 0,
) -> int | None:
    """记录一次请求并返回当前窗口内的计数。

    - 返回值大于 ``limit + burst`` 表示本次请求应被限流;
    - ``auto``:配置了 REDIS_URL 走 Redis,Redis 故障降级内存;
    - ``memory``:强制进程内窗口;``redis``:强制 Redis,故障 fail-open 返回 None;
    - ``now`` 仅用于测试,生产环境使用当前时间。
    """
    if not settings.RATE_LIMIT_ENABLED or limit <= 0:
        return 0

    backend = settings.RATE_LIMIT_BACKEND.lower()
    if backend == "memory" or (backend == "auto" and not settings.REDIS_URL):
        return _memory_rate_hit(key, limit, window_seconds, burst, now)

    try:
        client = get_redis()
        current = time.time() if now is None else now
        member = f"{current}:{uuid.uuid4().hex}"
        result = await client.eval(
            _SLIDING_WINDOW_LUA,
            1,
            key,
            str(current),
            str(window_seconds),
            str(limit + max(0, burst)),
            member,
        )
        _mark_redis_available()
        return int(result)
    except Exception as exc:  # noqa: BLE001 - 限流故障不应阻断主流程
        _mark_redis_unavailable(exc)
        if backend == "auto":
            logger.warning(
                "Redis 限流失败,降级进程内窗口 [{}]: {}", key, exc
            )
            return _memory_rate_hit(key, limit, window_seconds, burst, now)
        logger.warning("Redis 限流失败,按 fail-open 放行 [{}]: {}", key, exc)
        return None

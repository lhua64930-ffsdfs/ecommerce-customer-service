"""Redis 缓存工具。

所有方法在 Redis 不可用时静默降级(返回 None / 不抛异常),
避免缓存故障拖垮主流程。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings
from app.utils.logger import logger

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """获取 Redis 异步客户端(单例)。"""
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def cache_get(key: str) -> str | None:
    try:
        return await get_redis().get(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 读取失败 [{}]: {}", key, exc)
        return None


async def cache_set(key: str, value: str, ttl: int = 3600) -> bool:
    try:
        await get_redis().set(key, value, ex=ttl)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 写入失败 [{}]: {}", key, exc)
        return False


async def cache_delete(key: str) -> None:
    try:
        await get_redis().delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 删除失败 [{}]: {}", key, exc)


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


async def record_rate_hit(
    key: str,
    limit: int,
    window_seconds: int = 60,
    now: float | None = None,
) -> int | None:
    """记录一次请求并返回当前窗口内的计数。

    - 返回值大于 ``limit`` 表示本次请求应被限流;
    - Redis 不可用时返回 ``None``(调用方按 fail-open 处理);
    - ``now`` 仅用于测试,生产环境使用当前时间。
    """
    if limit <= 0:
        return 0

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
            str(limit),
            member,
        )
        return int(result)
    except Exception as exc:  # noqa: BLE001 - 限流故障不应阻断主流程
        logger.warning("Redis 限流计数失败 [{}]: {}", key, exc)
        return None

"""Redis 缓存工具。

所有方法在 Redis 不可用时静默降级(返回 None / 不抛异常),
避免缓存故障拖垮主流程。
"""
from __future__ import annotations

import json
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


async def incr_with_ttl(key: str, ttl: int = 60) -> int | None:
    """计数 +1 并设置过期时间(用于滑动窗口限流)。"""
    try:
        client = get_redis()
        async with client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, ttl)
            result = await pipe.execute()
        return int(result[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 限流计数失败 [{}]: {}", key, exc)
        return None

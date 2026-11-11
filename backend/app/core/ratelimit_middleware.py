"""可选:按客户端 IP 的全局限流中间件。

纯 ASGI 实现,不包裹/缓冲响应,避免影响 SSE 流式输出。
聊天接口本身还有按会话的限流,这一层用于兜底单 IP 刷接口。
"""
from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.utils.cache import record_rate_hit

_SKIP_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json", "/static")


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http" or not settings.RATE_LIMIT_MIDDLEWARE_ENABLED:
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if any(path.startswith(prefix) for prefix in _SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        client = scope.get("client") or ("unknown", 0)
        ip = str(client[0])
        count = await record_rate_hit(
            f"rate:ip:{ip}",
            limit=settings.RATE_LIMIT_PER_MINUTE,
            window_seconds=60,
            burst=settings.RATE_LIMIT_BURST,
        )
        capacity = settings.RATE_LIMIT_PER_MINUTE + max(
            0, settings.RATE_LIMIT_BURST
        )
        if count is not None and count > capacity:
            response = JSONResponse(
                {"detail": "请求过于频繁,请稍后再试"},
                status_code=429,
                headers={"Retry-After": "60"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

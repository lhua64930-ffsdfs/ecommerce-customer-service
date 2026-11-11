"""鉴权中间件:AUTH_ENABLED=true 时保护 /api/v1/*,写入 request.state.user。

登录/注册接口放行;纯 ASGI 实现,不缓冲 SSE 响应。
"""
from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import decode_token
from app.models.user import User

_PUBLIC_PATHS = {
    "/api/v1/auth/config",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/sms/send",
    "/api/v1/auth/sms/login",
    "/api/v1/auth/qr/start",
    "/api/v1/auth/qr/status",
}


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        detail: str,
    ) -> None:
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        response = JSONResponse(
            {"detail": detail}, status_code=status, headers=headers
        )
        await response(scope, receive, send)

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http" or not settings.AUTH_ENABLED:
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "").upper()
        if (
            method == "OPTIONS"
            or not path.startswith("/api/v1/")
            or path in _PUBLIC_PATHS
        ):
            await self.app(scope, receive, send)
            return

        authorization = Headers(scope=scope).get("authorization", "")
        if not authorization.startswith("Bearer "):
            await self._reject(scope, receive, send, 401, "未登录")
            return

        payload = decode_token(authorization[7:].strip())
        if not payload:
            await self._reject(scope, receive, send, 401, "凭证无效或已过期")
            return

        try:
            user_id = int(payload["sub"])
        except (KeyError, TypeError, ValueError):
            await self._reject(scope, receive, send, 401, "凭证无效")
            return

        try:
            async with AsyncSessionLocal() as db:
                user = await db.get(User, user_id)
        except Exception:  # noqa: BLE001 - 数据库故障时认证服务不可用
            await self._reject(
                scope, receive, send, 503, "认证服务暂时不可用"
            )
            return
        if user is None:
            await self._reject(scope, receive, send, 401, "账号不存在")
            return
        if not user.is_active:
            await self._reject(scope, receive, send, 403, "账号已停用")
            return
        if int(payload.get("ver", 0)) != int(user.token_version or 0):
            await self._reject(
                scope, receive, send, 401, "凭证已失效,请重新登录"
            )
            return

        # 角色以数据库当前值为准,管理员改角色后立即生效
        payload["user_id"] = user.id
        payload["username"] = user.username
        payload["roles"] = [user.user_type]
        payload["display_name"] = user.display_name
        payload["last_login_at"] = (
            user.last_login_at.isoformat() if user.last_login_at else None
        )
        payload["is_active"] = user.is_active
        payload["tenant_id"] = user.tenant_id or "default"
        scope.setdefault("state", {})["user"] = payload
        await self.app(scope, receive, send)

"""会话/订单级访问控制。

鉴权关闭(identity=None)时保持本地演示兼容;开启后顾客只能访问自己的资源,
客服/管理员按角色放行。
"""
from __future__ import annotations

from typing import Any

from fastapi import Request


def identity(request: Request) -> dict[str, Any] | None:
    return getattr(request.state, "user", None)


def user_id(request: Request) -> str | None:
    me = identity(request)
    if not me:
        return None
    value = me.get("user_id", me.get("sub"))
    return str(value) if value is not None else None


def roles(request: Request) -> set[str]:
    me = identity(request)
    return set((me or {}).get("roles") or [])


def is_staff(request: Request) -> bool:
    return bool(roles(request) & {"admin", "agent"})


def can_access_session(request: Request, session: Any) -> bool:
    """鉴权关闭时放行;staff 放行;顾客只匹配自己的 user_id。"""
    me = identity(request)
    if me is None:
        return True
    if (me.get("tenant_id") or "default") != (
        getattr(session, "tenant_id", "default") or "default"
    ):
        return False
    if is_staff(request):
        return True
    return str(getattr(session, "user_id", "")) == (user_id(request) or "")

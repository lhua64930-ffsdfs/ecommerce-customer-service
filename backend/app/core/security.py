"""JWT 签发/校验与口令散列。

JWT 显式使用 PyJWT(HS256);口令复用项目已有的 bcrypt。
"""
from __future__ import annotations

import time

import jwt

from app.core.config import settings

ROLES = ("customer", "agent", "admin")


def hash_password(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, stored: str) -> bool:
    if not stored or stored == "!":
        return False
    try:
        import bcrypt

        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(
    user_id: int,
    username: str,
    roles: list[str],
    expire_minutes: int | None = None,
    token_version: int = 0,
    tenant_id: str = "default",
) -> str:
    now = int(time.time())
    exp = now + (expire_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES) * 60
    payload = {
        "sub": str(user_id),
        "username": username,
        "roles": roles,
        "tenant": tenant_id or "default",
        "ver": int(token_version),
        "iat": now,
        "exp": exp,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError:
        return None

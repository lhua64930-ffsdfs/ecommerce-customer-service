"""认证与 RBAC:登录、当前账号、受保护路由。"""
from __future__ import annotations

import uuid

from app.core.config import settings


async def _login(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


async def test_login_and_me(client) -> None:
    token = await _login(client, "demo_customer", "demo123")

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["username"] == "demo_customer"
    assert "customer" in response.json()["roles"]


async def test_login_rejects_wrong_password(client) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "demo_customer", "password": "wrong"},
    )
    assert response.status_code == 401


async def test_admin_route_requires_admin_role(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)

    # 未带 token
    response = await client.get("/api/v1/knowledge/list")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"

    # 顾客 token 不够
    customer_token = await _login(client, "demo_customer", "demo123")
    response = await client.get(
        "/api/v1/knowledge/list",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert response.status_code == 403

    # 管理员 token 放行
    admin_token = await _login(client, "demo_admin", "admin123")
    response = await client.get(
        "/api/v1/knowledge/list",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200


async def test_auth_config_is_public(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    response = await client.get("/api/v1/auth/config")
    assert response.status_code == 200
    assert response.json()["auth_enabled"] is True


async def test_register_and_change_password(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "REGISTRATION_ENABLED", True)
    username = f"user_{uuid.uuid4().hex[:8]}"

    response = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "initial123"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["token"]

    response = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "initial123", "new_password": "updated123"},
    )
    assert response.status_code == 200, response.text

    await _login(client, username, "updated123")


async def test_register_rejects_long_password(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "REGISTRATION_ENABLED", True)
    response = await client.post(
        "/api/v1/auth/register",
        json={"username": f"u{uuid.uuid4().hex[:8]}", "password": "a" * 80},
    )
    assert response.status_code == 422


async def test_auth_disabled_keeps_local_admin(client) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["roles"] == ["admin"]

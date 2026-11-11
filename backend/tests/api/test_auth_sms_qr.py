"""短信/扫码登录与租户隔离。"""
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


async def test_sms_login_creates_user(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "SMS_DEBUG_RETURN_CODE", True)
    phone = "139" + str(uuid.uuid4().int)[:8]

    sent = await client.post("/api/v1/auth/sms/send", json={"phone": phone})
    assert sent.status_code == 200, sent.text
    code = sent.json()["debug_code"]

    logged = await client.post(
        "/api/v1/auth/sms/login",
        json={"phone": phone, "code": code},
    )
    assert logged.status_code == 200, logged.text
    token = logged.json()["token"]

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["username"].startswith(f"phone_{phone}")


async def test_qr_login_flow(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    admin_token = await _login(client, "demo_admin", "admin123")

    started = await client.post("/api/v1/auth/qr/start")
    assert started.status_code == 200, started.text
    ticket = started.json()["ticket"]

    approved = await client.post(
        "/api/v1/auth/qr/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"ticket": ticket},
    )
    assert approved.status_code == 200, approved.text

    status = await client.get(
        "/api/v1/auth/qr/status", params={"ticket": ticket}
    )
    assert status.status_code == 200
    assert status.json()["status"] == "approved"
    assert status.json()["token"]


async def test_tenant_isolation(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    admin_token = await _login(client, "demo_admin", "admin123")

    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    suffix = uuid.uuid4().hex[:8]
    created = []
    for tenant in ("tenant-a", "tenant-b"):
        response = await client.post(
            "/api/v1/admin/users",
            headers=_headers(admin_token),
            json={
                "username": f"user_{tenant}_{suffix}",
                "password": "tenant123",
                "user_type": "customer",
                "tenant_id": tenant,
            },
        )
        assert response.status_code == 200, response.text
        created.append(tenant)

    token_a = await _login(
        client, f"user_tenant-a_{suffix}", "tenant123"
    )
    token_b = await _login(
        client, f"user_tenant-b_{suffix}", "tenant123"
    )

    session = await client.post(
        "/api/v1/chat/session",
        headers=_headers(token_a),
        json={},
    )
    assert session.status_code == 200
    session_id = session.json()["session"]["session_id"]

    denied = await client.get(
        "/api/v1/chat/history",
        headers=_headers(token_b),
        params={"session_id": session_id},
    )
    assert denied.status_code == 404

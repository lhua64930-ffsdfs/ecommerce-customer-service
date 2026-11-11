"""管理员用户管理 API。"""
from __future__ import annotations

import uuid


async def test_admin_user_crud_and_reset_password(client) -> None:
    username = f"managed_{uuid.uuid4().hex[:8]}"

    created = await client.post(
        "/api/v1/admin/users",
        json={
            "username": username,
            "password": "initial123",
            "user_type": "customer",
            "display_name": "受管用户",
        },
    )
    assert created.status_code == 200, created.text
    user = created.json()
    assert "password_hash" not in user
    assert user["display_name"] == "受管用户"
    user_id = user["id"]

    listed = await client.get("/api/v1/admin/users?page=1&page_size=100")
    assert listed.status_code == 200
    assert any(item["id"] == user_id for item in listed.json()["items"])

    patched = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"user_type": "agent", "display_name": "客服甲"},
    )
    assert patched.status_code == 200
    assert patched.json()["user_type"] == "agent"

    reset = await client.post(
        f"/api/v1/admin/users/{user_id}/reset-password",
        json={"new_password": "updated123"},
    )
    assert reset.status_code == 200

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "updated123"},
    )
    assert login.status_code == 200

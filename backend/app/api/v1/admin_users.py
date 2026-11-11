"""管理员用户管理:列表、创建、角色/状态调整、重置密码。"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.security import hash_password
from app.models.user import User

router = APIRouter()

UserType = Literal["customer", "agent", "admin"]


def _check_password(value: str) -> str:
    if len(value.encode("utf-8")) > 72:
        raise ValueError("密码过长(bcrypt 最多 72 字节)")
    return value


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=200)
    user_type: UserType = "customer"
    email: str | None = Field(default=None, max_length=100)
    display_name: str | None = Field(default=None, max_length=64)
    tenant_id: str = Field(default="default", min_length=1, max_length=64)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value: str) -> str:
        return _check_password(value)


class UpdateUserRequest(BaseModel):
    user_type: UserType | None = None
    is_active: bool | None = None
    display_name: str | None = Field(default=None, max_length=64)
    tenant_id: str | None = Field(default=None, min_length=1, max_length=64)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=200)

    @field_validator("new_password")
    @classmethod
    def password_bytes(cls, value: str) -> str:
        return _check_password(value)


def _public(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "display_name": user.display_name,
        "user_type": user.user_type,
        "tenant_id": user.tenant_id or "default",
        "is_active": user.is_active,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }


async def _active_admin_count(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.count(User.id)).where(
                User.user_type == "admin", User.is_active.is_(True)
            )
        )
        or 0
    )


@router.get("", summary="用户列表")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    total = int(await db.scalar(select(func.count(User.id))) or 0)
    rows = (
        (
            await db.execute(
                select(User)
                .order_by(User.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_public(user) for user in rows], "total": total}


@router.post("", summary="创建用户")
async def create_user(
    payload: CreateUserRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    existing = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    if payload.email:
        email_exists = (
            await db.execute(select(User).where(User.email == payload.email))
        ).scalar_one_or_none()
        if email_exists is not None:
            raise HTTPException(status_code=409, detail="邮箱已被使用")

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        user_type=payload.user_type,
        display_name=payload.display_name or payload.username,
        tenant_id=payload.tenant_id,
        is_active=True,
        token_version=0,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _public(user)


@router.patch("/{user_id}", summary="调整角色/状态/展示名")
async def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    demoting = (
        user.user_type == "admin"
        and user.is_active
        and (
            (payload.user_type is not None and payload.user_type != "admin")
            or payload.is_active is False
        )
    )
    if demoting and await _active_admin_count(db) <= 1:
        raise HTTPException(status_code=400, detail="不能移除最后一个启用的管理员")

    changed = False
    if payload.user_type is not None:
        user.user_type = payload.user_type
        changed = True
    if payload.is_active is not None:
        user.is_active = payload.is_active
        changed = True
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.tenant_id is not None:
        user.tenant_id = payload.tenant_id
        changed = True
    if changed:
        user.token_version = (user.token_version or 0) + 1
    await db.commit()
    await db.refresh(user)
    return _public(user)


@router.post("/{user_id}/reset-password", summary="管理员重置密码")
async def reset_password(
    user_id: int,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(payload.new_password)
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
    return {"ok": True, "user_id": user.id}

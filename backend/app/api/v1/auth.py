"""认证接口:登录、注册、当前账号。"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.auth_extra import LoginCode, QrLoginSession
from app.models.user import User
from app.services.sms_service import SmsError, send_login_code
from app.utils.cache import record_rate_hit
from app.utils.logger import logger

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=200)
    email: str | None = Field(default=None, max_length=100)
    tenant_id: str = Field(default="default", min_length=1, max_length=64)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码过长(bcrypt 最多 72 字节)")
        return value


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)

    @field_validator("new_password")
    @classmethod
    def password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码过长(bcrypt 最多 72 字节)")
        return value


class TokenResponse(BaseModel):
    token: str
    user_id: int
    username: str
    user_type: str


class SmsSendRequest(BaseModel):
    phone: str


class SmsLoginRequest(BaseModel):
    phone: str
    code: str = Field(min_length=6, max_length=6)


class QrApproveRequest(BaseModel):
    ticket: str = Field(min_length=8, max_length=128)


def _normalize_phone(phone: str) -> str:
    value = re.sub(r"[\s-]", "", phone or "")
    if not _PHONE_RE.fullmatch(value):
        raise HTTPException(status_code=422, detail="请输入有效的 11 位手机号")
    return value


def _code_hash(phone: str, code: str) -> str:
    key = (settings.JWT_SECRET_KEY or "after-sales-otp").encode()
    return hmac.new(
        key, f"{phone}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        token=create_token(
            user.id,
            user.username,
            [user.user_type],
            token_version=user.token_version or 0,
            tenant_id=user.tenant_id or "default",
        ),
        user_id=user.id,
        username=user.username,
        user_type=user.user_type,
    )


@router.get("/config", summary="认证开关")
async def auth_config() -> dict:
    return {
        "auth_enabled": settings.AUTH_ENABLED,
        "registration_enabled": settings.REGISTRATION_ENABLED,
    }


@router.post("/login", response_model=TokenResponse, summary="账号密码登录")
async def login(
    payload: LoginRequest, db: AsyncSession = Depends(get_db)  # noqa: B008
) -> TokenResponse:
    user = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    user.last_login_at = datetime.now()
    await db.commit()
    return _token_response(user)


@router.post("/register", response_model=TokenResponse, summary="注册顾客账号")
async def register(
    payload: RegisterRequest, db: AsyncSession = Depends(get_db)  # noqa: B008
) -> TokenResponse:
    if not settings.AUTH_ENABLED or not settings.REGISTRATION_ENABLED:
        raise HTTPException(status_code=400, detail="注册未启用")
    existing = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        user_type="customer",
        tenant_id=payload.tenant_id,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _token_response(user)


@router.get("/me", summary="当前账号")
async def me(
    request: Request, db: AsyncSession = Depends(get_db)  # noqa: B008
) -> dict:
    principal = getattr(request.state, "user", None)
    if principal is None:
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            payload = decode_token(authorization[7:].strip())
            if payload:
                try:
                    user = await db.get(User, int(payload["sub"]))
                except (KeyError, TypeError, ValueError):
                    user = None
                if user is not None and user.is_active:
                    principal = {
                        "user_id": user.id,
                        "username": user.username,
                        "roles": [user.user_type],
                        "display_name": user.display_name,
                        "tenant_id": user.tenant_id or "default",
                        "last_login_at": (
                            user.last_login_at.isoformat()
                            if user.last_login_at
                            else None
                        ),
                    }
    if principal:
        return {
            "user_id": principal.get("user_id"),
            "username": principal.get("username"),
            "display_name": principal.get("display_name"),
            "roles": principal.get("roles", []),
            "tenant_id": principal.get("tenant_id", "default"),
            "last_login_at": principal.get("last_login_at"),
        }
    if not settings.AUTH_ENABLED:
        return {"user_id": None, "username": "local", "roles": ["admin"]}
    raise HTTPException(status_code=401, detail="未登录")


@router.post("/change-password", summary="修改当前账号密码")
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    if not settings.AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="鉴权未启用")
    principal = getattr(request.state, "user", None)
    if not principal:
        raise HTTPException(status_code=401, detail="未登录")
    user = await db.get(User, int(principal["user_id"]))
    if user is None:
        raise HTTPException(status_code=401, detail="账号不存在")
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    user.password_hash = hash_password(payload.new_password)
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
    return {"ok": True, "relogin_required": True}


@router.post("/sms/send", summary="发送短信登录码")
async def sms_send(
    payload: SmsSendRequest, db: AsyncSession = Depends(get_db)  # noqa: B008
) -> dict:
    if not settings.AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="鉴权未启用")
    phone = _normalize_phone(payload.phone)
    count = await record_rate_hit(
        f"rate:sms:send:{phone}", limit=5, window_seconds=60
    )
    if count is not None and count > 5:
        raise HTTPException(status_code=429, detail="发送过于频繁,请稍后再试")

    latest = (
        await db.execute(
            select(LoginCode)
            .where(LoginCode.phone == phone)
            .order_by(LoginCode.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if (
        latest is not None
        and latest.created_at is not None
        and (datetime.now() - latest.created_at).total_seconds()
        < settings.SMS_RESEND_SECONDS
    ):
        raise HTTPException(status_code=429, detail="请稍后再获取验证码")

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        LoginCode(
            phone=phone,
            code_hash=_code_hash(phone, code),
            expires_at=datetime.now()
            + timedelta(seconds=settings.SMS_CODE_TTL_SECONDS),
        )
    )
    await db.commit()
    try:
        await send_login_code(phone, code)
    except SmsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result = {"ok": True, "expires_in": settings.SMS_CODE_TTL_SECONDS}
    if settings.SMS_DEBUG_RETURN_CODE:
        result["debug_code"] = code
    return result


@router.post(
    "/sms/login", response_model=TokenResponse, summary="短信验证码登录"
)
async def sms_login(
    payload: SmsLoginRequest, db: AsyncSession = Depends(get_db)  # noqa: B008
) -> TokenResponse:
    if not settings.AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="鉴权未启用")
    phone = _normalize_phone(payload.phone)
    row = (
        await db.execute(
            select(LoginCode)
            .where(LoginCode.phone == phone)
            .order_by(LoginCode.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if (
        row is None
        or row.used_at is not None
        or row.expires_at <= datetime.now()
    ):
        raise HTTPException(status_code=401, detail="验证码已失效")
    if row.attempts >= 5:
        raise HTTPException(status_code=429, detail="验证码尝试次数过多")
    if not hmac.compare_digest(row.code_hash, _code_hash(phone, payload.code)):
        row.attempts += 1
        await db.commit()
        raise HTTPException(status_code=401, detail="验证码错误")

    row.used_at = datetime.now()
    user = (
        await db.execute(select(User).where(User.phone == phone))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            username=f"phone_{phone}_{uuid.uuid4().hex[:4]}",
            phone=phone,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            user_type="customer",
            display_name=f"用户{phone[-4:]}",
            tenant_id="default",
            is_active=True,
        )
        db.add(user)
        await db.flush()
    user.last_login_at = datetime.now()
    await db.commit()
    await db.refresh(user)
    logger.info("短信登录成功: phone={} user={}", phone, user.id)
    return _token_response(user)


@router.post("/qr/start", summary="创建扫码登录票据")
async def qr_start(
    db: AsyncSession = Depends(get_db)  # noqa: B008
) -> dict:
    if not settings.AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="鉴权未启用")
    ticket = uuid.uuid4().hex
    db.add(
        QrLoginSession(
            ticket=ticket,
            status="pending",
            expires_at=datetime.now()
            + timedelta(seconds=settings.QR_LOGIN_TTL_SECONDS),
        )
    )
    await db.commit()
    return {
        "ticket": ticket,
        "expires_in": settings.QR_LOGIN_TTL_SECONDS,
        "url": f"/qr/approve?ticket={ticket}",
    }


@router.post("/qr/approve", summary="已登录用户确认扫码")
async def qr_approve(
    payload: QrApproveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    if not settings.AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="鉴权未启用")
    principal = getattr(request.state, "user", None)
    if not principal:
        raise HTTPException(status_code=401, detail="未登录")
    row = (
        await db.execute(
            select(QrLoginSession).where(
                QrLoginSession.ticket == payload.ticket
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="扫码票据不存在")
    if row.expires_at <= datetime.now() or row.status != "pending":
        raise HTTPException(status_code=409, detail="扫码票据已失效")
    row.status = "approved"
    row.user_id = int(principal["user_id"])
    row.approved_at = datetime.now()
    await db.commit()
    return {"ok": True, "status": "approved"}


@router.get("/qr/status", summary="轮询扫码登录状态")
async def qr_status(
    ticket: str = Query(..., min_length=8, max_length=128),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    row = (
        await db.execute(
            select(QrLoginSession).where(QrLoginSession.ticket == ticket)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="扫码票据不存在")
    if row.expires_at <= datetime.now() and row.status == "pending":
        return {"status": "expired"}
    if row.status == "approved" and row.user_id is not None:
        user = await db.get(User, row.user_id)
        if user is not None and user.is_active:
            row.status = "consumed"
            await db.commit()
            return {
                "status": "approved",
                **_token_response(user).model_dump(),
            }
    return {"status": row.status}

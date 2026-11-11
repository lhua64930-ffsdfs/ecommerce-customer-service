"""用户模型。"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="用户ID")
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="用户名")
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="default",
        comment="租户 ID",
    )
    email: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True, comment="邮箱")
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, comment="手机号")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    user_type: Mapped[str] = mapped_column(
        Enum("customer", "agent", "admin", name="user_type"),
        nullable=False,
        server_default="customer",
        comment="用户类型",
    )
    display_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="展示名"
    )
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="头像URL")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1"), comment="是否激活"
    )
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="JWT 版本,改密/禁用后+1"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最后登录时间"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_username", "username"),
        Index("idx_phone", "phone"),
        Index("idx_email", "email"),
        {"comment": "用户表"},
    )

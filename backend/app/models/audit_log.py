"""操作审计日志:谁在什么时候对什么做了什么。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="审计ID")
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="用户ID")
    session_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="会话ID")
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment="动作")
    target_type: Mapped[str | None] = mapped_column(String(30), nullable=True, comment="目标类型")
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="目标ID")
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="详情")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_audit_session", "session_id"),
        Index("idx_audit_action", "action"),
        Index("idx_audit_created", "created_at"),
        {"comment": "操作审计日志表"},
    )

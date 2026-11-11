"""工单模型。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="工单ID")
    ticket_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment="工单号")
    session_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="关联会话ID")
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="用户ID"
    )
    type: Mapped[str] = mapped_column(
        Enum("complaint", "refund", "consult", "suggestion", "other", name="ticket_type"),
        nullable=False,
        comment="工单类型",
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="工单标题")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="工单内容")
    status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "resolved", "closed", name="ticket_status"),
        nullable=False,
        server_default="pending",
        comment="处理状态",
    )
    priority: Mapped[str] = mapped_column(
        Enum("low", "normal", "high", "urgent", name="ticket_priority"),
        nullable=False,
        server_default="normal",
        comment="优先级",
    )
    assigned_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="处理人")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True, comment="处理结果")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解决时间")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_ticket_no", "ticket_no"),
        Index("idx_user_id", "user_id"),
        Index("idx_status", "status"),
        {"comment": "工单表"},
    )

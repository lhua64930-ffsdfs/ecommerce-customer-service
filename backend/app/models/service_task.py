"""售后事项(工单任务)模型:一次售后诉求的持久化进度。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ServiceTask(Base):
    __tablename__ = "service_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="事项ID")
    task_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment="事项编号")
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, comment="会话ID"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="用户ID"
    )
    intent_code: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="触发意图")
    task_type: Mapped[str] = mapped_column(
        Enum("cancel", "refund", "return", "modify", name="service_task_type"),
        nullable=False,
        comment="事项类型",
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "open",
            "pending_approval",
            "executing",
            "completed",
            "rejected",
            "expired",
            "transferred",
            name="service_task_status",
        ),
        nullable=False,
        server_default="open",
        comment="事项状态",
    )
    target_order_no: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="目标订单号")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="事项摘要")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", comment="版本号")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_service_task_no", "task_no"),
        Index("idx_service_task_session", "session_id"),
        Index("idx_service_task_status", "status"),
        Index("idx_service_task_order", "target_order_no"),
        {"comment": "售后事项表"},
    )

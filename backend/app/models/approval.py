"""售后审批单:模型只能提申请,确认/审批通过后才执行写操作。"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    JSON,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="审批ID")
    approval_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, comment="审批编号")
    task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_tasks.id", ondelete="SET NULL"), nullable=True, comment="事项ID"
    )
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, comment="会话ID"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="用户ID"
    )
    action: Mapped[str] = mapped_column(
        Enum("cancel", "refund", "return", "modify", name="approval_action"),
        nullable=False,
        comment="动作",
    )
    order_no: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="订单号")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="申请内容快照")
    policy_decision_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("policy_decisions.id", ondelete="SET NULL"),
        nullable=True,
        comment="策略决策ID",
    )
    risk_level: Mapped[str] = mapped_column(
        Enum("low", "medium", "high", name="approval_risk_level"),
        nullable=False,
        server_default="medium",
        comment="风险等级",
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "approved",
            "rejected",
            "executed",
            "expired",
            "cancelled",
            name="approval_status",
        ),
        nullable=False,
        server_default="pending",
        comment="审批状态",
    )
    requires_verification: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1"), comment="是否需要订单核验"
    )
    requires_human: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0"), comment="是否需要人工审核"
    )
    decided_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="处理人")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="处理时间")
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="执行时间")
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="执行结果")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_approval_no", "approval_no"),
        Index("idx_approval_session", "session_id"),
        Index("idx_approval_status", "status"),
        Index("idx_approval_order", "order_no"),
        {"comment": "售后审批单表"},
    )

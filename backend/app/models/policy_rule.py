"""售后策略规则:policy-as-code 的持久化定义。"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Index,
    Integer,
    JSON,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="规则ID")
    rule_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="规则编码")
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment="适用动作(cancel/return/refund)")
    description: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="规则说明")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="优先级(大者先)")
    conditions: Mapped[list] = mapped_column(JSON, nullable=False, comment="条件列表(AND)")
    decision: Mapped[str] = mapped_column(
        Enum(
            "allow_auto",
            "needs_confirm",
            "needs_human",
            "deny",
            name="policy_rule_decision",
        ),
        nullable=False,
        comment="决策",
    )
    risk_level: Mapped[str] = mapped_column(
        Enum("low", "medium", "high", name="policy_risk_level"),
        nullable=False,
        server_default="medium",
        comment="风险等级",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", comment="规则版本")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1"), comment="是否启用"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_policy_rule_id", "rule_id"),
        Index("idx_policy_action", "action"),
        {"comment": "售后策略规则表"},
    )

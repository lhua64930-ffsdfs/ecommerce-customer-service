"""策略决策审计:每次资格判断留存规则、输入与结论。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Index, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="决策ID")
    rule_id: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="命中的规则编码")
    rule_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="规则版本"
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False, comment="动作")
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="决策输入快照")
    decision: Mapped[str] = mapped_column(
        Enum(
            "allow_auto",
            "needs_confirm",
            "needs_human",
            "deny",
            name="policy_decision_result",
        ),
        nullable=False,
        comment="决策结果",
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="决策原因")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_policy_decision_rule", "rule_id"),
        Index("idx_policy_decision_created", "created_at"),
        {"comment": "策略决策审计表"},
    )

"""Agent 执行步骤:为轨迹回放与后续轨迹评测保留证据。"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Index, Integer, JSON, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="步骤ID")
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="运行唯一标识")
    seq: Mapped[int] = mapped_column(Integer, nullable=False, comment="步骤序号")
    step_type: Mapped[str] = mapped_column(
        Enum("model", "tool", "policy", "approval", name="agent_step_type"),
        nullable=False,
        comment="步骤类型",
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="步骤名称")
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="输入摘要")
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="输出摘要")
    success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1"), comment="是否成功"
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="耗时(毫秒)")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_agent_step_run", "run_id", "seq"),
        {"comment": "Agent 执行步骤表"},
    )

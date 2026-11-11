"""Agent 执行记录:一次用户请求对应的运行实例。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="运行ID")
    run_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="运行唯一标识")
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, comment="会话ID"
    )
    task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_tasks.id", ondelete="SET NULL"), nullable=True, comment="关联事项ID"
    )
    agent_mode: Mapped[str] = mapped_column(String(30), nullable=False, comment="Agent 模式")
    status: Mapped[str] = mapped_column(
        Enum("running", "succeeded", "failed", "awaiting_approval", name="agent_run_status"),
        nullable=False,
        server_default="running",
        comment="运行状态",
    )
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="步骤数")
    total_latency_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="总耗时(毫秒)"
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="总 Token 数(近似)"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="开始时间"
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="结束时间")

    __table_args__ = (
        Index("idx_agent_run_id", "run_id"),
        Index("idx_agent_run_session", "session_id"),
        Index("idx_agent_run_task", "task_id"),
        {"comment": "Agent 运行记录表"},
    )

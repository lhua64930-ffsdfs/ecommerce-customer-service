"""会话模型。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="会话ID")
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="会话唯一标识")
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="用户ID"
    )
    agent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="分配的Agent ID")
    status: Mapped[str] = mapped_column(
        Enum("active", "waiting", "transferred", "closed", name="session_status"),
        nullable=False,
        server_default="active",
        comment="会话状态",
    )
    channel: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="web", comment="来源渠道"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="开始时间"
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="结束时间")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="最后消息时间")
    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="消息数量"
    )
    satisfaction_score: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="满意度评分")

    __table_args__ = (
        Index("idx_session_id", "session_id"),
        Index("idx_user_id", "user_id"),
        Index("idx_status", "status"),
        {"comment": "会话表"},
    )

"""低置信度问题池:检索证据不足或自检不通过的问题,等待人工复核后补库。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Index, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LowConfidenceQuestion(Base):
    __tablename__ = "low_confidence_questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="ID")
    session_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="会话ID")
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="用户ID")
    query: Mapped[str] = mapped_column(Text, nullable=False, comment="用户问题")
    source: Mapped[str] = mapped_column(
        Enum(
            "retrieval_low_conf",
            "self_check",
            "answer_guard",
            "user_feedback",
            name="low_conf_source",
        ),
        nullable=False,
        comment="来源:检索置信度低 / 自检不通过 / 实体校验 / 用户反馈",
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="原因")
    retrieved_snapshot: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="Top N 证据快照"
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "discarded", name="low_conf_status"),
        nullable=False,
        server_default="pending",
        comment="处理状态",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_low_conf_status", "status"),
        Index("idx_low_conf_created", "created_at"),
        {"comment": "低置信度问题池"},
    )

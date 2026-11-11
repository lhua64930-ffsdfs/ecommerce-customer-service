"""消息模型。"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="消息ID")
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, comment="会话ID"
    )
    sender_type: Mapped[str] = mapped_column(
        Enum("user", "bot", "agent", name="sender_type"), nullable=False, comment="发送者类型"
    )
    sender_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="发送者ID")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息内容")
    content_type: Mapped[str] = mapped_column(
        Enum("text", "image", "voice", "file", "quick_reply", name="content_type"),
        nullable=False,
        server_default="text",
        comment="内容类型",
    )
    intent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("intents.id", ondelete="SET NULL"), nullable=True, comment="识别的意图ID"
    )
    intent_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), nullable=True, comment="意图置信度"
    )
    sentiment: Mapped[str | None] = mapped_column(
        Enum("positive", "neutral", "negative", name="sentiment_type"), nullable=True, comment="情感倾向"
    )
    sentiment_score: Mapped[Decimal | None] = mapped_column(
        Numeric(3, 2), nullable=True, comment="情感得分"
    )
    is_human_transfer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0"), comment="是否转人工"
    )
    is_generated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0"), comment="是否AI生成"
    )
    # 注意: metadata 是 SQLAlchemy 保留属性,Python 属性必须改名
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True, comment="元数据")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_session_id", "session_id"),
        Index("idx_created_at", "created_at"),
        Index("idx_sender_type", "sender_type"),
        {"comment": "消息表"},
    )

"""意图字典模型(意图定义,不是识别记录)。"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Index, Integer, JSON, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Intent(Base):
    __tablename__ = "intents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="意图ID")
    intent_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="意图名称")
    intent_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="意图编码")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="意图描述")
    handler_type: Mapped[str] = mapped_column(
        Enum("rag", "tool", "transfer", "fallback", "llm", name="handler_type"),
        nullable=False,
        comment="处理类型",
    )
    handler_config: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="处理配置")
    sample_utterances: Mapped[str | None] = mapped_column(Text, nullable=True, comment="示例语料")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="优先级")
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
        Index("idx_intent_code", "intent_code"),
        Index("idx_handler_type", "handler_type"),
        {"comment": "意图表"},
    )

"""知识库模型。"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Knowledge(Base):
    __tablename__ = "knowledge"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="知识ID")
    category: Mapped[str] = mapped_column(String(50), nullable=False, comment="知识分类")
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="问题")
    answer: Mapped[str] = mapped_column(Text, nullable=False, comment="答案")
    keywords: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="关键词")
    vector_id: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="向量数据库ID")
    embedding_model: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="bge-small-zh-v1.5", comment="向量化模型"
    )
    hit_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="命中次数"
    )
    satisfaction_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True, comment="满意度"
    )
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
        Index("idx_category", "category"),
        {"comment": "知识库表"},
    )

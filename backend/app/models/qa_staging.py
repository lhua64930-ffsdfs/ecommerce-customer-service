"""对话挖知识暂存表:LLM 抽取的问答对先停在这里,人工采纳后才入库。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QaExtractionStaging(Base):
    __tablename__ = "qa_extraction_staging"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="ID")
    batch_no: Mapped[str] = mapped_column(String(40), nullable=False, comment="批次号")
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="来源引用")
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="候选问题")
    answer: Mapped[str] = mapped_column(Text, nullable=False, comment="候选答案")
    status: Mapped[str] = mapped_column(
        Enum("extracted", "approved", "discarded", name="qa_staging_status"),
        nullable=False,
        server_default="extracted",
        comment="处理状态",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_qa_staging_status", "status"),
        Index("idx_qa_staging_batch", "batch_no"),
        {"comment": "对话挖知识暂存表"},
    )

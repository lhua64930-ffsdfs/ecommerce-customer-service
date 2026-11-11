"""文档知识:长文档切块后的原始文档与片段。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="文档ID")
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="文档标题")
    source: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="来源/文件名")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", comment="版本号")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active", comment="状态"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_knowledge_doc_title", "title"),
        {"comment": "知识文档表"},
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="片段ID")
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        comment="文档ID",
    )
    section_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="章节路径")
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="片段序号")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="片段内容")
    vector_id: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="向量ID")
    is_active: Mapped[bool] = mapped_column(
        nullable=False, server_default="1", comment="是否启用"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_knowledge_chunk_doc", "document_id"),
        {"comment": "知识文档片段表"},
    )

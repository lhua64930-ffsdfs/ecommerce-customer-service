"""文档知识导入:Markdown 切块 → MySQL → Milvus,按文档幂等替换。"""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_document import KnowledgeChunk, KnowledgeDocument
from app.services.document_chunking import split_markdown
from app.services.knowledge_constants import CHUNK_ID_OFFSET
from app.services.rag_service import RAGService
from app.utils.logger import logger


async def _delete_document_data(
    db: AsyncSession, document: KnowledgeDocument
) -> None:
    chunks = list(
        (
            await db.execute(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.document_id == document.id
                )
            )
        )
        .scalars()
        .all()
    )
    vector_ids = [
        int(item.vector_id) for item in chunks if item.vector_id is not None
    ]
    if vector_ids:
        try:
            await RAGService().delete_documents(vector_ids)
        except Exception as exc:  # noqa: BLE001 - 向量删除失败不阻塞文档替换
            logger.warning("删除文档片段向量失败: {}", exc)
    await db.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
    )


async def import_document(
    db: AsyncSession,
    title: str,
    content: str,
    source: str | None = None,
    chunk_size: int = 500,
    overlap: int = 80,
    table_max_rows: int = 10,
) -> dict:
    """导入/替换一份 Markdown 文档,返回片段数量与向量化状态。"""
    title = title.strip()
    if not title or not content.strip():
        raise ValueError("文档标题和内容不能为空")

    existing = (
        await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.title == title)
        )
    ).scalar_one_or_none()
    if existing is not None:
        await _delete_document_data(db, existing)
        await db.delete(existing)
        await db.flush()

    document = KnowledgeDocument(
        title=title,
        source=source,
        version=1,
        status="active",
    )
    db.add(document)
    await db.flush()

    pieces = split_markdown(
        content,
        chunk_size=chunk_size,
        overlap=overlap,
        table_max_rows=table_max_rows,
    )
    chunks = [
        KnowledgeChunk(
            document_id=document.id,
            section_path=piece.section_path,
            chunk_index=piece.chunk_index,
            content=piece.content,
            is_active=True,
        )
        for piece in pieces
    ]
    db.add_all(chunks)
    await db.flush()

    vectorized = True
    try:
        await RAGService().add_chunks(
            [
                {
                    "id": chunk.id,
                    "document_title": document.title,
                    "section_path": chunk.section_path,
                    "content": chunk.content,
                }
                for chunk in chunks
            ]
        )
        for chunk in chunks:
            chunk.vector_id = str(CHUNK_ID_OFFSET + chunk.id)
    except Exception as exc:  # noqa: BLE001 - 向量化失败不阻塞文档入库
        vectorized = False
        logger.warning("文档片段向量化失败(可稍后重建): {}", exc)

    await db.commit()
    return {
        "document_id": document.id,
        "title": document.title,
        "chunks": len(chunks),
        "vectorized": vectorized,
    }


async def list_documents(db: AsyncSession) -> list[dict]:
    documents = (
        (await db.execute(select(KnowledgeDocument).order_by(KnowledgeDocument.id.desc())))
        .scalars()
        .all()
    )
    counts = dict(
        (
            await db.execute(
                select(KnowledgeChunk.document_id, func.count()).group_by(
                    KnowledgeChunk.document_id
                )
            )
        ).all()
    )
    return [
        {
            "id": document.id,
            "title": document.title,
            "source": document.source,
            "version": document.version,
            "status": document.status,
            "chunks": int(counts.get(document.id, 0)),
            "created_at": document.created_at.isoformat()
            if document.created_at
            else None,
        }
        for document in documents
    ]


async def delete_document(db: AsyncSession, document_id: int) -> bool:
    document = await db.get(KnowledgeDocument, document_id)
    if document is None:
        return False
    await _delete_document_data(db, document)
    await db.delete(document)
    await db.commit()
    return True

"""知识库管理接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.models.knowledge import Knowledge
from app.services.rag_service import RAGService
from app.utils.logger import logger

router = APIRouter()


class KnowledgeCreate(BaseModel):
    category: str = Field(..., max_length=50)
    question: str
    answer: str
    keywords: str | None = Field(None, max_length=500)


class KnowledgeUpdate(BaseModel):
    category: str | None = Field(None, max_length=50)
    question: str | None = None
    answer: str | None = None
    keywords: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class KnowledgeSearch(BaseModel):
    query: str
    top_k: int = 5
    category: str | None = None


def _to_dict(item: Knowledge) -> dict:
    return {
        "id": item.id,
        "category": item.category,
        "question": item.question,
        "answer": item.answer,
        "keywords": item.keywords,
        "vector_id": item.vector_id,
        "hit_count": item.hit_count,
        "is_active": item.is_active,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@router.get("/list", summary="知识库列表")
async def list_knowledge(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    statement = select(Knowledge)
    count_statement = select(func.count()).select_from(Knowledge)
    if category:
        statement = statement.where(Knowledge.category == category)
        count_statement = count_statement.where(Knowledge.category == category)

    total = await db.scalar(count_statement)
    rows = (
        (
            await db.execute(
                statement.order_by(Knowledge.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [_to_dict(item) for item in rows],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


@router.post("/add", summary="新增知识")
async def add_knowledge(
    payload: KnowledgeCreate, db: AsyncSession = Depends(get_db)
) -> dict:
    item = Knowledge(
        category=payload.category,
        question=payload.question,
        answer=payload.answer,
        keywords=payload.keywords,
        embedding_model=settings.EMBEDDING_MODEL,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    # 向量化失败不影响知识入库(可后续重建索引)
    try:
        item.vector_id = await RAGService().add_document(_to_dict(item))
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("知识向量化失败(可稍后重建): {}", exc)

    return _to_dict(item)


@router.put("/{knowledge_id}", summary="更新知识")
async def update_knowledge(
    knowledge_id: int, payload: KnowledgeUpdate, db: AsyncSession = Depends(get_db)
) -> dict:
    item = await db.get(Knowledge, knowledge_id)
    if item is None:
        raise HTTPException(status_code=404, detail="知识不存在")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)

    try:
        item.vector_id = await RAGService().add_document(_to_dict(item))
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("知识重新向量化失败: {}", exc)

    return _to_dict(item)


@router.delete("/{knowledge_id}", summary="删除知识")
async def delete_knowledge(
    knowledge_id: int, db: AsyncSession = Depends(get_db)
) -> dict:
    item = await db.get(Knowledge, knowledge_id)
    if item is None:
        raise HTTPException(status_code=404, detail="知识不存在")

    await db.delete(item)
    await db.commit()

    try:
        await RAGService().delete_documents([knowledge_id])
    except Exception as exc:  # noqa: BLE001
        logger.warning("向量删除失败: {}", exc)

    return {"success": True, "id": knowledge_id}


@router.post("/search", summary="语义检索")
async def search_knowledge(payload: KnowledgeSearch) -> dict:
    filters = {"category": payload.category} if payload.category else None
    results = await RAGService().search(payload.query, top_k=payload.top_k, filters=filters)
    return {"query": payload.query, "results": results}

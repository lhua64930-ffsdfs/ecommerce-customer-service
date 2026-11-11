"""知识飞轮审核接口:低置信度问题 → 抽取候选 → 人工采纳/弃用 → 补库。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.audit_log import AuditLog
from app.models.knowledge import Knowledge
from app.models.low_confidence import LowConfidenceQuestion
from app.models.qa_staging import QaExtractionStaging
from app.services.knowledge_mining import mine_knowledge
from app.services.rag_service import RAGService
from app.utils.logger import logger

router = APIRouter()


def _staging_dict(item: QaExtractionStaging) -> dict:
    return {
        "id": item.id,
        "batch_no": item.batch_no,
        "source_ref": item.source_ref,
        "question": item.question,
        "answer": item.answer,
        "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("/queue", summary="知识飞轮待审队列")
async def review_queue(
    status: str = Query("extracted"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    items = (
        (
            await db.execute(
                select(QaExtractionStaging)
                .where(QaExtractionStaging.status == status)
                .order_by(QaExtractionStaging.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    pending_low_conf = await db.scalar(
        select(func.count())
        .select_from(LowConfidenceQuestion)
        .where(LowConfidenceQuestion.status == "pending")
    )
    return {
        "items": [_staging_dict(item) for item in items],
        "total": len(items),
        "pending_low_confidence": int(pending_low_conf or 0),
    }


@router.post("/mine", summary="从低置信度问题中抽取候选知识")
async def mine(db: AsyncSession = Depends(get_db)) -> dict:
    result = await mine_knowledge(db)
    return result


@router.post("/{staging_id}/approve", summary="采纳候选知识并写入知识库")
async def approve(
    staging_id: int, db: AsyncSession = Depends(get_db)
) -> dict:
    item = await db.get(QaExtractionStaging, staging_id)
    if item is None:
        raise HTTPException(status_code=404, detail="候选知识不存在")
    if item.status != "extracted":
        raise HTTPException(status_code=409, detail="该候选知识已处理")

    knowledge = Knowledge(
        category="对话沉淀",
        question=item.question,
        answer=item.answer,
        keywords="",
    )
    db.add(knowledge)
    item.status = "approved"
    db.add(
        AuditLog(
            action="review.approve",
            target_type="qa_staging",
            target_id=str(staging_id),
            detail_json={"question": item.question},
        )
    )
    await db.commit()
    await db.refresh(knowledge)

    try:
        knowledge.vector_id = await RAGService().add_document(
            {
                "id": knowledge.id,
                "category": knowledge.category,
                "question": knowledge.question,
                "answer": knowledge.answer,
            }
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - 向量化失败不阻塞入库
        logger.warning("采纳知识后向量化失败(可稍后重建): {}", exc)

    return {
        "success": True,
        "staging_id": staging_id,
        "knowledge_id": knowledge.id,
        "question": knowledge.question,
    }


@router.post("/{staging_id}/discard", summary="弃用候选知识")
async def discard(
    staging_id: int, db: AsyncSession = Depends(get_db)
) -> dict:
    item = await db.get(QaExtractionStaging, staging_id)
    if item is None:
        raise HTTPException(status_code=404, detail="候选知识不存在")
    if item.status != "extracted":
        raise HTTPException(status_code=409, detail="该候选知识已处理")

    item.status = "discarded"
    db.add(
        AuditLog(
            action="review.discard",
            target_type="qa_staging",
            target_id=str(staging_id),
            detail_json={"question": item.question},
        )
    )
    await db.commit()
    return {"success": True, "staging_id": staging_id, "status": "discarded"}

"""知识飞轮审核接口测试。"""
from __future__ import annotations

import uuid

import httpx
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.knowledge import Knowledge
from app.models.qa_staging import QaExtractionStaging


async def _insert_staging(question: str) -> int:
    async with AsyncSessionLocal() as session:
        item = QaExtractionStaging(
            batch_no="test-batch",
            source_ref="test",
            question=question,
            answer="测试候选答案",
            status="extracted",
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item.id


async def test_review_queue_approve_and_discard(client: httpx.AsyncClient) -> None:
    approve_question = f"审核采纳测试-{uuid.uuid4().hex[:8]}"
    discard_question = f"审核弃用测试-{uuid.uuid4().hex[:8]}"
    approve_id = await _insert_staging(approve_question)
    discard_id = await _insert_staging(discard_question)

    queue = await client.get("/api/v1/review/queue")
    assert queue.status_code == 200
    assert any(item["id"] == approve_id for item in queue.json()["items"])

    approved = await client.post(f"/api/v1/review/{approve_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["success"] is True

    async with AsyncSessionLocal() as session:
        knowledge = (
            await session.execute(
                select(Knowledge).where(Knowledge.question == approve_question)
            )
        ).scalar_one_or_none()
        assert knowledge is not None

    discarded = await client.post(f"/api/v1/review/{discard_id}/discard")
    assert discarded.status_code == 200
    assert discarded.json()["status"] == "discarded"

    queue_after = await client.get("/api/v1/review/queue")
    remaining_ids = {item["id"] for item in queue_after.json()["items"]}
    assert approve_id not in remaining_ids
    assert discard_id not in remaining_ids

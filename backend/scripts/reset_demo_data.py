"""恢复演示数据:订单状态 + 清理测试/飞轮产生的业务数据。

用法(在 backend 目录):
    python scripts/reset_demo_data.py
"""
import asyncio
import json
import sys
from pathlib import Path

# 允许直接运行 scripts/ 下的脚本
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select, update  # noqa: E402

from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.models.agent_step import AgentStep  # noqa: E402
from app.models.approval import Approval  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402
from app.models.knowledge import Knowledge  # noqa: E402
from app.models.knowledge_document import KnowledgeChunk, KnowledgeDocument  # noqa: E402
from app.models.low_confidence import LowConfidenceQuestion  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.qa_staging import QaExtractionStaging  # noqa: E402
from app.models.service_task import ServiceTask  # noqa: E402
from app.models.ticket import Ticket  # noqa: E402
from app.models.verification import Verification  # noqa: E402
from app.services.rag_service import RAGService  # noqa: E402

DEMO_ORDER_STATUS = {
    "ORDER20260315001": "shipped",
    "ORDER20260401001": "paid",
    "ORDER20260310005": "delivered",
    "ORDER20260320001": "pending",
}

FAQ_FILE = Path(__file__).resolve().parents[2] / "knowledge_base" / "faqs.json"


async def main() -> None:
    with FAQ_FILE.open("r", encoding="utf-8") as file:
        seed_questions = {item["question"] for item in json.load(file)}

    async with AsyncSessionLocal() as session:
        # 清理文档切块及其向量(文档知识按需通过 import_documents.py 导入)
        chunks = list((await session.execute(select(KnowledgeChunk))).scalars().all())
        chunk_vector_ids = [
            int(item.vector_id) for item in chunks if item.vector_id is not None
        ]
        if chunk_vector_ids:
            try:
                await RAGService().delete_documents(chunk_vector_ids)
            except Exception as exc:  # noqa: BLE001
                print(f"文档片段向量删除失败(可稍后重建): {exc}")
        await session.execute(delete(KnowledgeChunk))
        await session.execute(delete(KnowledgeDocument))

        # 清理测试/飞轮产生的知识条目及其向量
        extra_knowledge = list(
            (
                await session.execute(
                    select(Knowledge).where(Knowledge.question.notin_(seed_questions))
                )
            )
            .scalars()
            .all()
        )
        extra_ids = [item.id for item in extra_knowledge]
        if extra_ids:
            try:
                await RAGService().delete_documents(extra_ids)
            except Exception as exc:  # noqa: BLE001 - 向量删除失败不阻塞数据清理
                print(f"向量删除失败(可稍后重建): {exc}")
            await session.execute(delete(Knowledge).where(Knowledge.id.in_(extra_ids)))

        await session.execute(delete(QaExtractionStaging))
        await session.execute(delete(LowConfidenceQuestion))
        await session.execute(delete(Approval))
        await session.execute(delete(ServiceTask))
        await session.execute(delete(AgentStep))
        await session.execute(delete(AgentRun))
        await session.execute(delete(AuditLog))
        await session.execute(delete(Ticket))
        await session.execute(delete(Verification))

        for order_no, status in DEMO_ORDER_STATUS.items():
            await session.execute(
                update(Order)
                .where(Order.order_no == order_no)
                .values(status=status)
            )
        await session.commit()

    await engine.dispose()
    print("演示订单状态已恢复:", ", ".join(DEMO_ORDER_STATUS))
    print(f"已清理额外知识 {len(extra_ids)} 条,以及审批/任务/飞轮/审计等演示数据")


if __name__ == "__main__":
    asyncio.run(main())

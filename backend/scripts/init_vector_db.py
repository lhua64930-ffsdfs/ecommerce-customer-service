"""重建全部知识向量索引。

适用于:Milvus 数据丢失、更换 embedding 模型、批量修改知识之后。

用法(在 backend 目录):
    python scripts/init_vector_db.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

import app.models  # noqa: F401,E402
from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.models.knowledge import Knowledge  # noqa: E402
from app.services.rag_service import RAGService  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as session:
        items = (
            (
                await session.execute(
                    select(Knowledge).where(Knowledge.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )

        if not items:
            print("没有可索引的知识条目")
            await engine.dispose()
            return

        documents = [
            {
                "id": item.id,
                "category": item.category,
                "question": item.question,
                "answer": item.answer,
            }
            for item in items
        ]

        await RAGService().add_documents(documents)

        for item in items:
            item.vector_id = str(item.id)
        await session.commit()

    await engine.dispose()
    print(f"向量重建完成:{len(items)} 条")


if __name__ == "__main__":
    asyncio.run(main())

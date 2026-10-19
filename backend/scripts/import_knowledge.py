"""批量导入知识库 JSON 并写入向量索引。

用法(在 backend 目录):
    python scripts/import_knowledge.py --file ../knowledge_base/faqs.json
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

import app.models  # noqa: F401,E402
from app.core.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.models.knowledge import Knowledge  # noqa: E402
from app.services.rag_service import RAGService  # noqa: E402


async def main(file_path: Path) -> None:
    entries = json.loads(file_path.read_text(encoding="utf-8"))

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        existing = set((await session.execute(select(Knowledge.question))).scalars().all())
        new_items = []

        for entry in entries:
            question = entry.get("question", "").strip()
            if not question or question in existing:
                continue
            item = Knowledge(
                category=entry.get("category", "其他"),
                question=question,
                answer=entry.get("answer", ""),
                keywords=entry.get("keywords", ""),
                embedding_model="bge-small-zh-v1.5",
            )
            session.add(item)
            new_items.append(item)

        await session.commit()

        if new_items:
            for item in new_items:
                await session.refresh(item)

            documents = [
                {
                    "id": item.id,
                    "category": item.category,
                    "question": item.question,
                    "answer": item.answer,
                }
                for item in new_items
            ]
            await RAGService().add_documents(documents)

            for item in new_items:
                item.vector_id = str(item.id)
            await session.commit()

    await engine.dispose()
    print(f"导入完成:新增 {len(new_items)} 条,跳过 {len(entries) - len(new_items)} 条")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入知识库 JSON")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "knowledge_base" / "faqs.json",
        help="知识库 JSON 文件路径",
    )
    args = parser.parse_args()
    asyncio.run(main(args.file))

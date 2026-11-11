"""导入 Markdown 文档知识:切块 → MySQL → Milvus。

用法(在 backend 目录):
    python scripts/import_documents.py --file ../knowledge_base/after_sales_manual.md --title 售后处理手册
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.services.document_service import import_document  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="导入 Markdown 文档知识")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--source", default=None)
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--overlap", type=int, default=80)
    args = parser.parse_args()

    content = args.file.read_text(encoding="utf-8")
    async with AsyncSessionLocal() as session:
        result = await import_document(
            session,
            title=args.title,
            content=content,
            source=args.source or args.file.name,
            chunk_size=args.chunk_size,
            overlap=args.overlap,
        )
    await engine.dispose()
    print(
        f"文档导入完成: {result['title']} / {result['chunks']} 个片段 / "
        f"向量化={'成功' if result['vectorized'] else '失败(可稍后重建)'}"
    )


if __name__ == "__main__":
    asyncio.run(main())

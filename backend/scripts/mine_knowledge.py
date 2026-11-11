"""从低置信度问题/对话中抽取候选知识,写入待审队列。

用法(在 backend 目录):
    python scripts/mine_knowledge.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.services.knowledge_mining import mine_knowledge  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await mine_knowledge(session)
    await engine.dispose()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())

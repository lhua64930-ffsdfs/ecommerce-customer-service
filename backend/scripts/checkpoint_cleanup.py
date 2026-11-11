"""清理超过 CHECKPOINT_TTL_HOURS 的 LangGraph checkpoint thread。

用法(在 backend 目录):
    python scripts/checkpoint_cleanup.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.graph.checkpointer import (
    cleanup_expired_threads,
    close_checkpointer,
    init_checkpointer,
)
from app.core.database import engine


async def main() -> None:
    await init_checkpointer()
    try:
        result = await cleanup_expired_threads()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await close_checkpointer()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

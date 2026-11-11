"""数据保留期清理脚本。

用法(在 backend 目录):
    python scripts/retention_cleanup.py [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 允许直接运行 scripts/ 下的脚本
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import engine  # noqa: E402
from app.services.retention_service import run_retention  # noqa: E402


async def main(dry_run: bool) -> None:
    try:
        result = await run_retention(dry_run=dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="按 RETENTION_DAYS_* 清理过期数据")
    parser.add_argument("--dry-run", action="store_true", help="只统计不删除")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))

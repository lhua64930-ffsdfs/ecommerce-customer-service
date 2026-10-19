"""初始化数据库:建表 + 写入种子数据。

用法(在 backend 目录):
    python scripts/init_db.py
"""
import asyncio
import sys
from pathlib import Path

# 允许直接运行 scripts/ 下的脚本
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401,E402 - 注册全部模型
from app.core.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.core.seed import seed_all  # noqa: E402


async def main() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await seed_all(session)

    await engine.dispose()
    print("数据库初始化完成")


if __name__ == "__main__":
    asyncio.run(main())

"""把演示订单恢复到种子状态,便于重复演示复合任务。

用法(在 backend 目录):
    python scripts/reset_demo_data.py
"""
import asyncio
import sys
from pathlib import Path

# 允许直接运行 scripts/ 下的脚本
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import update  # noqa: E402

from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.models.order import Order  # noqa: E402

DEMO_ORDER_STATUS = {
    "ORDER20260315001": "shipped",
    "ORDER20260401001": "paid",
    "ORDER20260310005": "delivered",
}


async def main() -> None:
    async with AsyncSessionLocal() as session:
        for order_no, status in DEMO_ORDER_STATUS.items():
            await session.execute(
                update(Order)
                .where(Order.order_no == order_no)
                .values(status=status)
            )
        await session.commit()
    await engine.dispose()
    print("演示订单状态已恢复:", ", ".join(DEMO_ORDER_STATUS))


if __name__ == "__main__":
    asyncio.run(main())

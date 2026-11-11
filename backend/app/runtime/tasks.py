"""售后事项服务:同一会话、同一订单、同一类型的未完成事项复用。"""
from __future__ import annotations

import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_task import ServiceTask
from app.utils.logger import logger

ACTIVE_STATUSES = ("open", "pending_approval", "executing")


def _task_no() -> str:
    return f"TASK{int(time.time())}{uuid.uuid4().hex[:4].upper()}"


class ServiceTaskService:
    """售后事项的创建、复用与状态推进。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create(
        self,
        session_id: int,
        user_id: int,
        task_type: str,
        target_order_no: str | None = None,
        intent_code: str | None = None,
        summary: str | None = None,
    ) -> ServiceTask:
        statement = select(ServiceTask).where(
            ServiceTask.session_id == session_id,
            ServiceTask.task_type == task_type,
            ServiceTask.status.in_(ACTIVE_STATUSES),
        )
        if target_order_no:
            statement = statement.where(ServiceTask.target_order_no == target_order_no)
        result = await self.db.execute(
            statement.order_by(ServiceTask.id.desc()).limit(1)
        )
        task = result.scalar_one_or_none()
        if task is not None:
            return task

        return await self.create(
            session_id=session_id,
            user_id=user_id,
            task_type=task_type,
            target_order_no=target_order_no,
            intent_code=intent_code,
            summary=summary,
        )

    async def create(
        self,
        session_id: int,
        user_id: int,
        task_type: str,
        target_order_no: str | None = None,
        intent_code: str | None = None,
        summary: str | None = None,
        status: str = "open",
    ) -> ServiceTask:
        task = ServiceTask(
            task_no=_task_no(),
            session_id=session_id,
            user_id=user_id,
            intent_code=intent_code,
            task_type=task_type,
            status=status,
            target_order_no=target_order_no,
            summary=summary,
            # 显式赋值,避免 flush 后访问 server_default 触发异步懒加载
            version=1,
        )
        self.db.add(task)
        await self.db.flush()
        logger.info("售后事项已创建: {} type={} status={}", task.task_no, task_type, status)
        return task

    async def set_status(self, task: ServiceTask, status: str) -> None:
        task.status = status
        task.version += 1
        await self.db.flush()

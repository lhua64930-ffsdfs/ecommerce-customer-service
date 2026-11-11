"""数据保留期清理:按 created_at 分批删除,默认关闭。

删除顺序遵循外键依赖:agent_steps → agent_runs、messages → sessions、
low_confidence、audit_logs;不关闭 FOREIGN_KEY_CHECKS,避免孤儿数据。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, exists, func, not_, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep
from app.models.approval import Approval
from app.models.audit_log import AuditLog
from app.models.low_confidence import LowConfidenceQuestion
from app.models.message import Message
from app.models.service_task import ServiceTask
from app.models.session import Session
from app.models.ticket import Ticket
from app.utils.logger import logger


def _cutoff(days: int) -> datetime:
    return datetime.now() - timedelta(days=days)


async def _delete_where(
    db: Any,
    model: Any,
    condition: Any,
    batch_size: int,
    dry_run: bool,
) -> int:
    if dry_run:
        return int(
            await db.scalar(select(func.count()).select_from(model).where(condition))
            or 0
        )

    deleted = 0
    while True:
        ids = (
            (
                await db.execute(
                    select(model.id).where(condition).limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not ids:
            break
        await db.execute(delete(model).where(model.id.in_(ids)))
        await db.flush()
        deleted += len(ids)
    return deleted


async def run_retention(dry_run: bool = False) -> dict[str, int]:
    """执行清理;dry_run 只统计不删除。"""
    if not settings.RETENTION_ENABLED:
        return {"enabled": 0}

    counts: dict[str, int] = {}
    batch = max(1, settings.RETENTION_BATCH_SIZE)
    async with AsyncSessionLocal() as db:
        if settings.RETENTION_DAYS_AGENT_RUNS:
            cutoff = _cutoff(settings.RETENTION_DAYS_AGENT_RUNS)
            counts["agent_steps"] = await _delete_where(
                db, AgentStep, AgentStep.created_at < cutoff, batch, dry_run
            )
            counts["agent_runs"] = await _delete_where(
                db, AgentRun, AgentRun.started_at < cutoff, batch, dry_run
            )

        if settings.RETENTION_DAYS_MESSAGES:
            cutoff = _cutoff(settings.RETENTION_DAYS_MESSAGES)
            active_sessions = select(Session.id).where(
                Session.status.in_(["active", "waiting", "transferred"])
            )
            counts["messages"] = await _delete_where(
                db,
                Message,
                (Message.created_at < cutoff)
                & (not_(Message.session_id.in_(active_sessions))),
                batch,
                dry_run,
            )

        if settings.RETENTION_DAYS_SESSIONS:
            cutoff = _cutoff(settings.RETENTION_DAYS_SESSIONS)
            has_pending_approval = exists(
                select(Approval.id).where(
                    Approval.session_id == Session.id,
                    Approval.status == "pending",
                )
            )
            has_open_task = exists(
                select(ServiceTask.id).where(
                    ServiceTask.session_id == Session.id,
                    ServiceTask.status.notin_(["completed", "cancelled"]),
                )
            )
            has_open_ticket = exists(
                select(Ticket.id).where(
                    Ticket.session_id == Session.id,
                    Ticket.status.notin_(["resolved", "closed"]),
                )
            )
            counts["sessions"] = await _delete_where(
                db,
                Session,
                (Session.status == "closed")
                & (
                    func.coalesce(Session.last_message_at, Session.started_at)
                    < cutoff
                )
                & not_(has_pending_approval)
                & not_(has_open_task)
                & not_(has_open_ticket),
                batch,
                dry_run,
            )

        if settings.RETENTION_DAYS_LOW_CONF:
            cutoff = _cutoff(settings.RETENTION_DAYS_LOW_CONF)
            condition = LowConfidenceQuestion.created_at < cutoff
            if settings.RETENTION_KEEP_PENDING_LOW_CONF:
                condition &= LowConfidenceQuestion.status != "pending"
            counts["low_confidence_questions"] = await _delete_where(
                db,
                LowConfidenceQuestion,
                condition,
                batch,
                dry_run,
            )

        if settings.RETENTION_DAYS_AUDIT:
            cutoff = _cutoff(settings.RETENTION_DAYS_AUDIT)
            counts["audit_logs"] = await _delete_where(
                db, AuditLog, AuditLog.created_at < cutoff, batch, dry_run
            )

        if not dry_run:
            db.add(
                AuditLog(
                    action="retention_cleanup",
                    target_type="maintenance",
                    detail_json=counts,
                )
            )
        await db.commit()

    logger.info("数据保留期清理完成 dry_run={} counts={}", dry_run, counts)
    return counts

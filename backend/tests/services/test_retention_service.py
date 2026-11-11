"""数据保留期:dry-run 只统计,真实执行按外键顺序删除。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.message import Message
from app.models.session import Session
from app.models.user import User
from app.services.retention_service import run_retention


async def test_retention_dry_run_then_delete(client) -> None:
    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.username == "demo_customer"))
        ).scalar_one()
        old = datetime.now() - timedelta(days=10)
        session = Session(
            session_id=f"retention-{uuid.uuid4().hex}",
            user_id=user.id,
            status="closed",
            started_at=old,
            last_message_at=old,
            message_count=1,
        )
        db.add(session)
        await db.flush()
        message = Message(
            session_id=session.id,
            sender_type="user",
            content="old message",
            created_at=old,
        )
        db.add(message)
        await db.commit()
        session_db_id = session.id

    settings.RETENTION_ENABLED = True
    settings.RETENTION_DAYS_MESSAGES = 1
    settings.RETENTION_DAYS_SESSIONS = 1
    try:
        dry = await run_retention(dry_run=True)
        assert dry["messages"] >= 1
        assert dry["sessions"] >= 1

        async with AsyncSessionLocal() as db:
            assert await db.get(Session, session_db_id) is not None

        counts = await run_retention(dry_run=False)
        assert counts["sessions"] >= 1

        async with AsyncSessionLocal() as db:
            assert await db.get(Session, session_db_id) is None
            remaining = (
                await db.execute(
                    select(Message).where(Message.session_id == session_db_id)
                )
            ).scalars().all()
            assert remaining == []
    finally:
        settings.RETENTION_ENABLED = False
        settings.RETENTION_DAYS_MESSAGES = 0
        settings.RETENTION_DAYS_SESSIONS = 0
        async with AsyncSessionLocal() as db:
            # 若断言失败,尽量清理测试数据
            await db.execute(delete(Message).where(Message.session_id == session_db_id))
            await db.execute(delete(Session).where(Session.id == session_db_id))
            await db.commit()

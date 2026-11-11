"""只读观测接口:运行概览、轨迹回放与 Token 成本。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.observability import langfuse_enabled
from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep
from app.models.approval import Approval
from app.models.low_confidence import LowConfidenceQuestion

router = APIRouter()


def _since(days: int) -> datetime:
    return datetime.now() - timedelta(days=max(1, days))


@router.get("/overview", summary="运行与业务观测概览")
async def overview(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    since = _since(days)

    run_rows = (
        await db.execute(
            select(
                AgentRun.status,
                func.count(AgentRun.id),
                func.coalesce(func.sum(AgentRun.total_tokens), 0),
                func.coalesce(func.avg(AgentRun.total_latency_ms), 0),
            )
            .where(AgentRun.started_at >= since)
            .group_by(AgentRun.status)
        )
    ).all()
    runs_by_status = {
        status: {
            "count": int(count),
            "total_tokens": int(tokens),
            "avg_latency_ms": round(float(avg_latency or 0), 2),
        }
        for status, count, tokens, avg_latency in run_rows
    }

    failed_steps = int(
        await db.scalar(
            select(func.count(AgentStep.id)).where(
                AgentStep.created_at >= since,
                AgentStep.success.is_(False),
            )
        )
        or 0
    )
    top_failing = (
        await db.execute(
            select(AgentStep.name, func.count(AgentStep.id))
            .where(
                AgentStep.created_at >= since,
                AgentStep.success.is_(False),
            )
            .group_by(AgentStep.name)
            .order_by(func.count(AgentStep.id).desc())
            .limit(5)
        )
    ).all()

    low_conf_total = int(
        await db.scalar(select(func.count(LowConfidenceQuestion.id))) or 0
    )
    low_conf_pending = int(
        await db.scalar(
            select(func.count(LowConfidenceQuestion.id)).where(
                LowConfidenceQuestion.status == "pending"
            )
        )
        or 0
    )
    approval_rows = (
        await db.execute(
            select(Approval.status, func.count(Approval.id)).group_by(
                Approval.status
            )
        )
    ).all()

    return {
        "days": days,
        "runs": {
            "total": sum(item["count"] for item in runs_by_status.values()),
            "by_status": runs_by_status,
        },
        "steps": {
            "failed": failed_steps,
            "top_failing_tools": [
                {"name": name, "failed": int(count)}
                for name, count in top_failing
            ],
        },
        "low_confidence": {
            "total": low_conf_total,
            "pending": low_conf_pending,
        },
        "approvals": {
            status: int(count) for status, count in approval_rows
        },
        "langfuse_enabled": langfuse_enabled(),
    }


@router.get("/runs", summary="最近 Agent 运行")
async def list_runs(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    since = _since(days)
    rows = (
        (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.started_at >= since)
                .order_by(AgentRun.started_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "run_id": row.run_id,
                "session_id": row.session_id,
                "agent_mode": row.agent_mode,
                "status": row.status,
                "total_steps": row.total_steps,
                "total_latency_ms": row.total_latency_ms,
                "total_tokens": row.total_tokens,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.get("/runs/{run_id}", summary="运行详情与步骤回放")
async def get_run(
    run_id: str, db: AsyncSession = Depends(get_db)  # noqa: B008
) -> dict:
    run = (
        await db.execute(select(AgentRun).where(AgentRun.run_id == run_id))
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")

    steps = (
        (
            await db.execute(
                select(AgentStep)
                .where(AgentStep.run_id == run_id)
                .order_by(AgentStep.seq.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "agent_mode": run.agent_mode,
        "status": run.status,
        "total_steps": run.total_steps,
        "total_latency_ms": run.total_latency_ms,
        "total_tokens": run.total_tokens,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "steps": [
            {
                "seq": step.seq,
                "step_type": step.step_type,
                "name": step.name,
                "input": step.input_json,
                "output": step.output_json,
                "success": step.success,
                "latency_ms": step.latency_ms,
                "created_at": step.created_at,
            }
            for step in steps
        ],
    }


@router.get("/cost", summary="Token 成本(按天)")
async def cost(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    since = _since(days)
    rows = (
        await db.execute(
            select(
                func.date(AgentRun.started_at),
                func.coalesce(func.sum(AgentRun.total_tokens), 0),
                func.count(AgentRun.id),
            )
            .where(AgentRun.started_at >= since)
            .group_by(func.date(AgentRun.started_at))
            .order_by(func.date(AgentRun.started_at).asc())
        )
    ).all()
    items: list[dict[str, Any]] = [
        {
            "date": str(day),
            "tokens": int(tokens),
            "runs": int(runs),
        }
        for day, tokens, runs in rows
    ]
    return {
        "days": days,
        "total_tokens": sum(item["tokens"] for item in items),
        "items": items,
        "langfuse_enabled": langfuse_enabled(),
        "note": "本地 total_tokens 为上游 usage 或近似值;权威成本以 Langfuse 为准",
    }

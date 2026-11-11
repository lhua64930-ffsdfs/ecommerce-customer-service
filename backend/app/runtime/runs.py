"""Agent 运行记录:把一次请求的工具/策略步骤落库,供审计与后续轨迹评测使用。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep


class RunRecorder:
    """一次请求一个 run,每个工具/策略调用一个 step。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def start(
        self,
        session_id: int,
        agent_mode: str,
        task_id: int | None = None,
    ) -> AgentRun:
        run = AgentRun(
            run_id=uuid.uuid4().hex,
            session_id=session_id,
            task_id=task_id,
            agent_mode=agent_mode,
            status="running",
            started_at=datetime.now(),
        )
        self.db.add(run)
        return run

    async def record_steps(self, run: AgentRun, steps: list[dict[str, Any]]) -> None:
        total_latency = 0
        for index, step in enumerate(steps, 1):
            latency = int(step.get("latency_ms") or 0)
            total_latency += latency
            self.db.add(
                AgentStep(
                    run_id=run.run_id,
                    seq=index,
                    step_type=step.get("step_type") or "tool",
                    name=str(step.get("name") or "unknown")[:100],
                    input_json=step.get("input"),
                    output_json=step.get("output"),
                    success=bool(step.get("success", True)),
                    latency_ms=latency,
                )
            )
        run.total_steps = len(steps)
        run.total_latency_ms = total_latency
        await self.db.flush()

    async def finish(self, run: AgentRun, status: str) -> None:
        run.status = status
        run.finished_at = datetime.now()
        await self.db.flush()

"""后台作业接口:列表 / 启动 / 状态与日志 / 停止。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core import jobs as job_core

router = APIRouter()


def _known(name: str) -> None:
    if name not in job_core.JOBS:
        raise HTTPException(status_code=404, detail=f"未注册的作业:{name}")


@router.get("", summary="作业列表")
async def list_jobs() -> dict:
    return {"jobs": job_core.status_all()}


@router.post("/{name}", summary="启动作业")
async def start_job(name: str) -> dict:
    _known(name)
    try:
        return await job_core.start(name)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{name}", summary="作业状态与日志")
async def get_job(name: str) -> dict:
    _known(name)
    return job_core.status(name, with_log=True)


@router.post("/{name}/stop", summary="停止作业")
async def stop_job(name: str) -> dict:
    _known(name)
    try:
        return await job_core.stop(name)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

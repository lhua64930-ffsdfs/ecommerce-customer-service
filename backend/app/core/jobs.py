"""后台作业运行器:白名单脚本,argv 固定,页面传不进 shell。

作业只允许跑本模块注册表里的命令;前端只传作业名,不能传参数/路径。
日志写入 `logs/jobs/<name>.log`,状态保存在进程内存(重启后回到 idle)。
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from app.utils.logger import logger

BACKEND_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = BACKEND_ROOT.parent / "logs" / "jobs"
TAIL_LINES = 200
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class JobSpec:
    name: str
    title: str
    argv: tuple[str, ...]
    description: str = ""


JOBS: dict[str, JobSpec] = {
    job.name: job
    for job in (
        JobSpec(
            "evaluate-rag",
            "RAG 四策略评测",
            ("scripts/evaluate_rag.py", "--strategy", "all", "--output", "../docs/rag_eval_result.json"),
            "需要 Milvus + 已建库;分钟级",
        ),
        JobSpec(
            "evaluate-refusal",
            "无答案拒答评测",
            ("scripts/evaluate_refusal.py", "--self-check"),
            "需要 Milvus + 已建库 + LLM Key",
        ),
        JobSpec(
            "mine-knowledge",
            "对话挖知识",
            ("scripts/mine_knowledge.py",),
            "需要低置信度问题 + LLM Key",
        ),
        JobSpec(
            "import-manual",
            "导入售后处理手册",
            (
                "scripts/import_documents.py",
                "--file",
                "../knowledge_base/after_sales_manual.md",
                "--title",
                "售后处理手册",
            ),
            "写入文档切块与向量",
        ),
        JobSpec(
            "reset-demo-data",
            "重置演示数据",
            ("scripts/reset_demo_data.py",),
            "恢复订单、清理审批/飞轮/文档测试数据",
        ),
        JobSpec(
            "retention-cleanup",
            "数据保留期清理",
            ("scripts/retention_cleanup.py",),
            "按 RETENTION_DAYS_* 清理过期数据;默认关闭",
        ),
        JobSpec(
            "retention-dry-run",
            "数据保留期试算",
            ("scripts/retention_cleanup.py", "--dry-run"),
            "只统计不删除",
        ),
        JobSpec(
            "checkpoint-cleanup",
            "清理过期 checkpoint",
            ("scripts/checkpoint_cleanup.py",),
            "清理超过 CHECKPOINT_TTL_HOURS 的未完成 thread",
        ),
    )
}

_running: dict[str, asyncio.subprocess.Process] = {}
_last: dict[str, dict] = {}


def _log_path(name: str) -> Path:
    return LOG_DIR / f"{name}.log"


def _tail(name: str) -> str:
    path = _log_path(name)
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        text = _ANSI_RE.sub("", text)
        return "\n".join(text.splitlines()[-TAIL_LINES:])
    except OSError:
        return ""


def status(name: str, with_log: bool = False) -> dict:
    if name not in JOBS:
        raise KeyError(name)
    process = _running.get(name)
    last = _last.get(name)
    if process is not None and process.returncode is None:
        state, returncode = "running", None
    elif last is not None:
        returncode = last.get("returncode")
        state = "succeeded" if returncode == 0 else "failed"
    else:
        state, returncode = "idle", None

    payload = {
        "name": name,
        "title": JOBS[name].title,
        "description": JOBS[name].description,
        "status": state,
        "returncode": returncode,
    }
    if with_log:
        payload["log"] = _tail(name)
    return payload


def status_all() -> list[dict]:
    return [status(name) for name in JOBS]


async def start(name: str) -> dict:
    if name not in JOBS:
        raise KeyError(name)
    process = _running.get(name)
    if process is not None and process.returncode is None:
        raise RuntimeError(f"作业 {name} 正在运行")

    spec = JOBS[name]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _log_path(name).open("w", encoding="utf-8")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        *spec.argv,
        cwd=str(BACKEND_ROOT),
        stdout=log_file,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    _running[name] = process
    _last.pop(name, None)
    logger.info("后台作业已启动: {} pid={}", name, process.pid)

    async def _wait() -> None:
        returncode = await process.wait()
        log_file.close()
        _last[name] = {"returncode": returncode}
        _running.pop(name, None)
        logger.info("后台作业结束: {} returncode={}", name, returncode)

    asyncio.create_task(_wait())
    return status(name)


async def stop(name: str) -> dict:
    if name not in JOBS:
        raise KeyError(name)
    process = _running.get(name)
    if process is None or process.returncode is not None:
        raise RuntimeError(f"作业 {name} 不在运行")
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=10)
    except asyncio.TimeoutError:
        process.kill()
    return status(name)

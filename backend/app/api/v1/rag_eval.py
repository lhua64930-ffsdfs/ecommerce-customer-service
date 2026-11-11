"""RAG 评测看板只读接口:直接读取评测产出的 JSON,不在 API 里重算。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

ROOT = Path(__file__).resolve().parents[4]
RAG_EVAL_FILE = ROOT / "docs" / "rag_eval_result.json"
REFUSAL_FILE = ROOT / "docs" / "refusal_eval_result.json"


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return None


@router.get("/overview", summary="RAG 检索与拒答评测概览")
async def overview() -> dict:
    rag = _read(RAG_EVAL_FILE)
    refusal = _read(REFUSAL_FILE)

    best_strategy = None
    if rag and isinstance(rag.get("strategies"), dict):
        items = [
            (name, report)
            for name, report in rag["strategies"].items()
            if isinstance(report, dict)
        ]
        if items:
            name, report = max(
                items, key=lambda item: float(item[1].get("mrr_at_5") or 0)
            )
            best_strategy = {
                "name": name,
                "mrr_at_5": report.get("mrr_at_5"),
                "recall_at_1": report.get("recall_at_1"),
            }

    return {
        "present": rag is not None,
        "rag": rag,
        "rag_generated_at": _mtime(RAG_EVAL_FILE),
        "refusal": refusal,
        "refusal_generated_at": _mtime(REFUSAL_FILE),
        "best_strategy": best_strategy,
        "commands": {
            "rag": "python scripts/evaluate_rag.py --strategy all",
            "refusal": "python scripts/evaluate_refusal.py --self-check",
        },
    }

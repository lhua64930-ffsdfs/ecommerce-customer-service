"""RAG 无答案评测:知识库没有明确依据的问题,系统应拒答。

用法(在 backend 目录):
    python scripts/evaluate_refusal.py
    python scripts/evaluate_refusal.py --self-check   # 额外跑 LLM 自检
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.evidence import compute_evidence_confidence  # noqa: E402
from app.services.rag_service import RAGService  # noqa: E402
from app.services.retrieval import RetrievalService  # noqa: E402
from app.services.selfcheck import check_sufficient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_FILE = ROOT / "knowledge_base" / "unanswerable_questions.json"
OUTPUT_FILE = ROOT / "docs" / "refusal_eval_result.json"


async def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 无答案评测")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    args = parser.parse_args()

    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]
    rag = RAGService()
    retrieval = RetrievalService(rag)
    details = []
    refused = 0
    modes: dict[str, int] = {}

    for question in questions:
        hits = await retrieval.search(
            question, top_k=args.top_k, expand=False, split=False
        )
        evidence = compute_evidence_confidence(hits)
        mode = retrieval.last_mode
        modes[mode] = modes.get(mode, 0) + 1

        gate_refused = not evidence.strong
        self_check_refused = False
        if args.self_check and not gate_refused:
            check = await check_sufficient(
                question,
                [
                    f"{hit.get('question', '')}: {hit.get('answer', '')}"
                    for hit in hits
                ],
            )
            self_check_refused = not check["useful"]

        is_refused = gate_refused or self_check_refused
        refused += int(is_refused)
        details.append(
            {
                "question": question,
                "refused": is_refused,
                "evidence_score": evidence.score,
                "signals": evidence.signals,
                "self_check_refused": self_check_refused,
                "mode": mode,
                "top_questions": [hit.get("question") for hit in hits],
            }
        )

    total = len(questions)
    report = {
        "total": total,
        "refused": refused,
        "refusal_rate": round(refused / total, 4) if total else 0.0,
        "evidence_threshold": settings.RAG_EVIDENCE_THRESHOLD,
        "modes": modes,
        "details": details,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"无答案样本:{total}")
    print(f"正确拒答:{refused}")
    print(f"拒答率:{report['refusal_rate']:.4f}")
    print(f"检索模式:{modes}")
    print(f"JSON 结果已写入:{args.output}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())

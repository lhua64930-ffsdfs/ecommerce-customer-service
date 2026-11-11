"""运行 RAG 检索离线评测。

用法(在 backend 目录):
    python scripts/evaluate_rag.py
    python scripts/evaluate_rag.py --strategy all
    python scripts/evaluate_rag.py --strategy hybrid_rerank --json
    python scripts/evaluate_rag.py --output ../docs/rag_eval_result.json

评测集默认读取仓库根目录的 ``knowledge_base/eval_set.json``。
指标只反映检索排序质量,不评估生成答案。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 允许直接运行 scripts/ 下的脚本
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.rag_evaluator import (  # noqa: E402
    EvalReport,
    evaluate,
    load_eval_set,
)
from app.services.rag_service import RAGService  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVAL_SET = ROOT / "knowledge_base" / "eval_set.json"
STRATEGIES = ("vector", "bm25", "hybrid", "hybrid_rerank")


def _mode_label(report: EvalReport) -> str:
    if report.mode_counts:
        return ", ".join(
            f"{name}={count}" for name, count in sorted(report.mode_counts.items())
        )
    if report.keyword_queries == 0:
        return "vector(Milvus 语义检索)"
    if report.vector_queries == 0:
        return "keyword(向量检索不可用,已降级关键词检索)"
    return f"mixed(vector={report.vector_queries}, keyword={report.keyword_queries})"


def _print_report(report: EvalReport, title: str = "RAG 检索评测") -> None:
    print(title)
    print(f"  样本数:{report.total}    top_k:{report.top_k}")
    print(f"  检索模式:{_mode_label(report)}")
    print(f"  Recall@1:{report.recall_at_1:.4f}")
    print(f"  Recall@3:{report.recall_at_3:.4f}")
    print(f"  Recall@5:{report.recall_at_5:.4f}")
    print(f"  MRR@5   :{report.mrr_at_5:.4f}")
    if report.per_category:
        print("  分类别 Recall@3:")
        for name, stats in report.per_category.items():
            print(f"    - {name}: {stats['recall_at_3']:.4f} ({stats['total']} 条)")
    if report.misses:
        print(f"  未进入前 3 的样本({len(report.misses)} 条):")
        for item in report.misses:
            rank = item["rank"] if item["rank"] is not None else "未命中"
            print(
                f"    - [{item['mode']}] {item['query']}  "
                f"期望 id={item['expected_id']} 实际排名={rank}"
            )


def _print_comparison(reports: dict[str, EvalReport]) -> None:
    print("RAG 检索策略对照")
    print(
        f"{'策略':<14}{'Recall@1':>10}{'Recall@3':>10}{'Recall@5':>10}"
        f"{'MRR@5':>10}  检索模式"
    )
    for name, report in reports.items():
        print(
            f"{name:<14}{report.recall_at_1:>10.4f}{report.recall_at_3:>10.4f}"
            f"{report.recall_at_5:>10.4f}{report.mrr_at_5:>10.4f}  {_mode_label(report)}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 检索离线评测")
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--strategy",
        choices=[*STRATEGIES, "all"],
        default="hybrid_rerank",
        help="检索策略;all 输出四种策略对照",
    )
    parser.add_argument("--json", action="store_true", help="额外输出 JSON")
    parser.add_argument(
        "--include-chunks",
        action="store_true",
        help="把文档片段也纳入评测(默认只评 FAQ)",
    )
    parser.add_argument("--output", type=Path, help="把 JSON 结果写入文件")
    args = parser.parse_args()

    samples = load_eval_set(args.eval_set)
    rag = RAGService()

    healthy = await rag.health()
    print(f"Milvus 连通性:{'正常' if healthy else '不可用(检索会自动降级)'}\n")

    payload: dict
    if args.strategy == "all":
        reports: dict[str, EvalReport] = {}
        for strategy in STRATEGIES:
            reports[strategy] = await evaluate(
                rag,
                samples,
                top_k=args.top_k,
                strategy=strategy,
                exclude_chunks=not args.include_chunks,
            )
        _print_comparison(reports)
        payload = {
            "total": len(samples),
            "top_k": args.top_k,
            "strategies": {
                name: report.to_dict() for name, report in reports.items()
            },
        }
    else:
        report = await evaluate(
            rag,
            samples,
            top_k=args.top_k,
            strategy=args.strategy,
            exclude_chunks=not args.include_chunks,
        )
        _print_report(report, title=f"RAG 检索评测 · {args.strategy}")
        payload = report.to_dict()

    if args.json or args.output:
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.json:
            print("\n" + raw)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(raw + "\n", encoding="utf-8")
            print(f"\nJSON 结果已写入:{args.output}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())

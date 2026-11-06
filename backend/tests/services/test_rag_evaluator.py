"""RAG 评测集完整性与指标计算单测。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.rag_evaluator import (
    EvalSample,
    compute_report,
    load_eval_set,
)

ROOT = Path(__file__).resolve().parents[3]
EVAL_SET_PATH = ROOT / "knowledge_base" / "eval_set.json"
FAQ_PATH = ROOT / "knowledge_base" / "faqs.json"


def test_eval_set_is_valid_and_covers_all_knowledge_items() -> None:
    samples = load_eval_set(EVAL_SET_PATH)
    faq_ids = {item["id"] for item in json.loads(FAQ_PATH.read_text(encoding="utf-8"))}

    assert len(samples) >= 30
    assert {sample.expected_id for sample in samples} == faq_ids
    assert len({sample.query for sample in samples}) == len(samples)


def test_compute_report_calculates_recall_and_mrr() -> None:
    samples = [
        EvalSample(query="q1", expected_id=1, category="cat"),
        EvalSample(query="q2", expected_id=2, category="cat"),
        EvalSample(query="q3", expected_id=3, category="cat"),
        EvalSample(query="q4", expected_id=4, category="cat"),
    ]
    records = [
        (samples[0], [1, 9, 8, 7, 6], ["", "", "", "", ""], "vector"),
        (samples[1], [9, 2, 8, 7, 6], ["", "", "", "", ""], "vector"),
        (samples[2], [9, 8, 7, 3, 6], ["", "", "", "", ""], "keyword"),
        (samples[3], [9, 8, 7, 6, 5], ["", "", "", "", ""], "keyword"),
    ]

    report = compute_report(records, top_k=5)

    assert report.total == 4
    assert report.recall_at_1 == 0.25
    assert report.recall_at_3 == 0.5
    assert report.recall_at_5 == 0.75
    assert report.mrr_at_5 == 0.4375
    assert report.vector_queries == 2
    assert report.keyword_queries == 2
    assert report.per_category["cat"]["recall_at_3"] == 0.5
    assert len(report.misses) == 2


def test_load_eval_set_rejects_duplicate_queries(tmp_path: Path) -> None:
    path = tmp_path / "eval.json"
    path.write_text(
        json.dumps(
            {
                "samples": [
                    {"query": "重复问题", "expected_id": 1},
                    {"query": "重复问题", "expected_id": 2},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="重复问题"):
        load_eval_set(path)


def test_compute_report_matches_expected_question_when_id_drifts() -> None:
    """数据库 id 与评测集参考 id 不一致时,用标准问题文本兜底匹配。"""
    sample = EvalSample(
        query="客服电话是多少",
        expected_id=12,
        category="客服联系",
        expected_question="怎么联系人工客服",
    )
    records = [
        (
            sample,
            [13, 2, 9],
            ["怎么联系人工客服", "配送时间是多久", "订单可以修改地址吗"],
            "vector",
        )
    ]

    report = compute_report(records, top_k=5)

    assert report.recall_at_1 == 1.0
    assert report.mrr_at_5 == 1.0
    assert report.misses == []


def test_compute_report_requires_top_k_at_least_five() -> None:
    records = [(EvalSample(query="q", expected_id=1), [1], [""], "vector")]
    with pytest.raises(ValueError, match="top_k"):
        compute_report(records, top_k=3)

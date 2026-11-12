"""混合检索基础函数单测(不连接 Milvus)。"""
from app.services.evidence import compute_evidence_confidence
from app.services.retrieval import (
    _merge_round_robin,
    arrange_head_tail,
    rrf_fuse,
    split_clauses,
)


def test_split_clauses_splits_multi_intent_query() -> None:
    clauses = split_clauses("退款多久到账,顺便问下会员有什么优惠")
    assert len(clauses) == 2
    assert clauses[0] == "退款多久到账"
    assert "会员" in clauses[1]


def test_split_clauses_keeps_single_short_query() -> None:
    assert split_clauses("退货") == ["退货"]


def test_rrf_fuse_prefers_item_present_in_both_lists() -> None:
    dense = [
        {"id": 1, "question": "Q1", "answer": "A1", "score": 0.9},
        {"id": 2, "question": "Q2", "answer": "A2", "score": 0.8},
    ]
    bm25 = [
        {"id": 2, "question": "Q2", "answer": "A2", "score": 1.5},
        {"id": 3, "question": "Q3", "answer": "A3", "score": 1.0},
    ]

    fused = rrf_fuse([dense, bm25])

    assert fused[0]["id"] == 2
    assert fused[0]["score"] == 1.0
    assert {item["id"] for item in fused} == {1, 2, 3}


def test_merge_round_robin_interleaves_clause_results() -> None:
    first = [{"id": 1}, {"id": 2}, {"id": 3}]
    second = [{"id": 4}, {"id": 5}]

    merged = _merge_round_robin([first, second])

    assert [item["id"] for item in merged] == [1, 4, 2, 5, 3]


def test_merge_round_robin_dedupes_ids_and_moves_repeated_sections_to_tail() -> None:
    first = [
        {"id": 1, "section_path": "退款"},
        {"id": 2, "section_path": "退货"},
    ]
    second = [
        {"id": 1, "section_path": "退款"},
        {"id": 3, "section_path": "退款"},
        {"id": 4, "section_path": "运费"},
    ]

    merged = _merge_round_robin([first, second])

    assert [item["id"] for item in merged] == [1, 2, 4, 3]


def test_arrange_head_tail_moves_second_to_tail() -> None:
    items = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]
    assert arrange_head_tail(items) == [
        {"id": 1},
        {"id": 3},
        {"id": 4},
        {"id": 2},
    ]


def test_compute_evidence_confidence_strong_vs_empty() -> None:
    strong = compute_evidence_confidence(
        [
            {"question": "退款多久到账", "answer": "1-3 个工作日", "score": 0.95},
            {"question": "退货流程", "answer": "7 天无理由", "score": 0.7},
            {"question": "运费", "answer": "质量问题平台承担", "score": 0.6},
        ]
    )
    empty = compute_evidence_confidence([])

    assert strong.score >= 0.5
    assert strong.signals["key_clause_hit"] is True
    assert empty.score == 0.0

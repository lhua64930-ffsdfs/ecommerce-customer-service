"""RAG 引用构建单测。"""
from app.services.rag_service import RAGService
from app.utils.citations import build_citations


def test_build_citations_keeps_stable_fields_and_rounds_score() -> None:
    results = [
        {
            "id": 11,
            "category": "退款服务",
            "question": "退款多久到账",
            "answer": "不应出现在引用里",
            "score": 0.91234,
        }
    ]

    citations = build_citations(results)

    assert citations == [
        {
            "id": 11,
            "category": "退款服务",
            "question": "退款多久到账",
            "score": 0.9123,
        }
    ]
    assert "answer" not in citations[0]


def test_build_citations_dedupes_and_skips_invalid_rows() -> None:
    results = [
        {"id": 1, "category": "A", "question": "Q1", "score": 0.9},
        {"id": "1", "category": "A", "question": "Q1", "score": 0.8},
        {"id": None, "question": "missing id"},
        {"id": "bad", "question": "bad id"},
        {"id": 2, "category": "B", "question": "Q2", "score": "bad"},
    ]

    citations = build_citations(results)

    assert [item["id"] for item in citations] == [1, 2]
    assert citations[1]["score"] == 0.0


def test_rag_service_build_citations_delegates() -> None:
    results = [{"id": 3, "category": "C", "question": "Q3", "score": 0.5}]
    assert RAGService.build_citations(results) == [
        {"id": 3, "category": "C", "question": "Q3", "score": 0.5}
    ]

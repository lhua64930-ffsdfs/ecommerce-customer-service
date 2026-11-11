"""候选知识去重单测。"""
from app.services.dedupe import dedupe_candidates, normalize_question


def test_normalize_question_ignores_punctuation_and_space() -> None:
    assert normalize_question("退款 多久,到账?") == normalize_question("退款多久到账")


def test_dedupe_candidates_discards_exact_and_near_duplicates() -> None:
    candidates = [
        {"question": "退款多久到账", "answer": "1-3 个工作日"},
        {"question": "退款多久到账?", "answer": "1-3 个工作日"},
        {"question": "退款多久可以到账", "answer": "1-3 个工作日"},
        {"question": "会员有什么优惠", "answer": "积分返利"},
    ]

    kept, discarded = dedupe_candidates(candidates, [])

    assert [item["question"] for item in kept] == [
        "退款多久到账",
        "会员有什么优惠",
    ]
    assert len(discarded) == 2


def test_dedupe_against_existing_questions() -> None:
    kept, discarded = dedupe_candidates(
        [{"question": "商品可以退换吗", "answer": "7 天无理由"}],
        ["商品可以退换吗?"],
    )
    assert kept == []
    assert len(discarded) == 1

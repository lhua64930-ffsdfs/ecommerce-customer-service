"""回答机械校验单测。"""
from app.services.answer_guard import extract_entities, unsupported_entities


def test_extract_entities_order_money_date() -> None:
    text = "订单 ORDER20260401001 实付 ¥2699.00,承诺 2026-04-03 前处理。"
    entities = extract_entities(text)
    assert "ORDER20260401001" in entities
    assert "¥2699.00" in entities
    assert "2026-04-03" in entities


def test_unsupported_entities_flags_invented_values() -> None:
    evidence = "订单 ORDER20260401001 已支付,退款 1-3 个工作日。"
    answer = "订单 ORDER20260401001 退款 ¥8888.00,预计 2026-04-03 到账。"

    bad = unsupported_entities(answer, evidence)

    assert "¥8888.00" in bad
    assert "2026-04-03" in bad
    assert "ORDER20260401001" not in bad


def test_unsupported_entities_allows_evidence_values() -> None:
    evidence = "订单 ORDER20260401001 退款 ¥2699.00。"
    answer = "订单 ORDER20260401001 退款 ¥2699.00。"

    assert unsupported_entities(answer, evidence) == []

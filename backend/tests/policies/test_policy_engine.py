"""策略引擎规则匹配单测(不连接数据库)。"""
from __future__ import annotations

from app.models.policy_rule import PolicyRule
from app.policies.engine import (
    DECISION_ALLOW_AUTO,
    DECISION_DENY,
    DECISION_NEEDS_CONFIRM,
    DECISION_NEEDS_HUMAN,
    evaluate_rules,
    match_conditions,
)


def _rule(
    rule_id: str,
    action: str,
    conditions: list[dict],
    decision: str,
    priority: int,
    risk_level: str = "medium",
    is_active: bool = True,
) -> PolicyRule:
    return PolicyRule(
        rule_id=rule_id,
        action=action,
        description=rule_id,
        priority=priority,
        conditions=conditions,
        decision=decision,
        risk_level=risk_level,
        version=1,
        is_active=is_active,
    )


RULES = [
    _rule(
        "cancel_deny_shipped",
        "cancel",
        [{"field": "order.status", "op": "in", "value": ["shipped", "delivered"]}],
        DECISION_DENY,
        120,
        "high",
    ),
    _rule(
        "cancel_auto_low",
        "cancel",
        [
            {"field": "order.status", "op": "in", "value": ["pending", "paid"]},
            {"field": "order.pay_amount", "op": "lte", "value": 500},
        ],
        DECISION_ALLOW_AUTO,
        110,
        "low",
    ),
    _rule(
        "cancel_confirm_medium",
        "cancel",
        [
            {"field": "order.status", "op": "in", "value": ["pending", "paid"]},
            {"field": "order.pay_amount", "op": "gt", "value": 500},
        ],
        DECISION_NEEDS_CONFIRM,
        100,
    ),
    _rule(
        "return_human_shipped",
        "return,refund",
        [{"field": "order.status", "op": "in", "value": ["shipped", "delivered"]}],
        DECISION_NEEDS_HUMAN,
        110,
        "high",
    ),
]


def _context(status: str, amount: float | None) -> dict:
    return {"order": {"status": status, "pay_amount": amount}}


def test_low_value_cancel_is_auto_approved() -> None:
    result = evaluate_rules(RULES, "cancel", _context("pending", 99))
    assert result.decision == DECISION_ALLOW_AUTO
    assert result.rule_id == "cancel_auto_low"
    assert result.risk_level == "low"


def test_medium_value_cancel_needs_confirmation() -> None:
    result = evaluate_rules(RULES, "cancel", _context("paid", 2699))
    assert result.decision == DECISION_NEEDS_CONFIRM
    assert result.rule_id == "cancel_confirm_medium"


def test_shipped_cancel_is_denied_by_higher_priority() -> None:
    result = evaluate_rules(RULES, "cancel", _context("shipped", 9999))
    assert result.decision == DECISION_DENY
    assert result.rule_id == "cancel_deny_shipped"


def test_multi_action_rule_applies_to_refund_and_return() -> None:
    refund = evaluate_rules(RULES, "refund", _context("delivered", 1499))
    returned = evaluate_rules(RULES, "return", _context("delivered", 1499))
    assert refund.decision == returned.decision == DECISION_NEEDS_HUMAN


def test_no_matching_rule_defaults_to_deny() -> None:
    result = evaluate_rules(RULES, "cancel", _context("unknown_status", None))
    assert result.decision == DECISION_DENY
    assert result.rule_id is None
    assert "默认拒绝" in result.reason


def test_inactive_rule_is_ignored() -> None:
    rules = [
        _rule(
            "inactive_auto",
            "cancel",
            [{"field": "order.status", "op": "eq", "value": "paid"}],
            DECISION_ALLOW_AUTO,
            999,
            is_active=False,
        )
    ]
    result = evaluate_rules(rules, "cancel", _context("paid", 100))
    assert result.decision == DECISION_DENY


def test_match_conditions_requires_all_conditions_and_existing_fields() -> None:
    context = _context("paid", 100)
    assert match_conditions(
        context,
        [
            {"field": "order.status", "op": "eq", "value": "paid"},
            {"field": "order.pay_amount", "op": "gte", "value": 100},
        ],
    )
    assert not match_conditions(
        context,
        [
            {"field": "order.status", "op": "eq", "value": "paid"},
            {"field": "order.missing", "op": "eq", "value": "x"},
        ],
    )
    assert not match_conditions(context, [])

"""售后策略引擎:把「能不能退/能不能取消」从模型手里拿走。

规则定义在 ``config/policy_rules.yaml``,启动时幂等同步到 ``policy_rules`` 表。
每次评估都会写入 ``policy_decisions``,审批单通过 ``policy_decision_id`` 关联决策。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_loader import load_config
from app.models.policy_decision import PolicyDecision
from app.models.policy_rule import PolicyRule
from app.utils.logger import logger

DECISION_ALLOW_AUTO = "allow_auto"
DECISION_NEEDS_CONFIRM = "needs_confirm"
DECISION_NEEDS_HUMAN = "needs_human"
DECISION_DENY = "deny"

VALID_DECISIONS = {
    DECISION_ALLOW_AUTO,
    DECISION_NEEDS_CONFIRM,
    DECISION_NEEDS_HUMAN,
    DECISION_DENY,
}


@dataclass(frozen=True)
class PolicyResult:
    """一次策略评估的结果。"""

    decision: str
    risk_level: str
    rule_id: str | None
    rule_version: int
    reason: str
    policy_decision_id: int | None = None


def _get_value(context: dict[str, Any], path: str) -> Any:
    current: Any = context
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return actual in (expected or [])
    if op == "not_in":
        return actual not in (expected or [])
    if op == "exists":
        return (actual is not None) == bool(expected)
    if op in ("gt", "gte", "lt", "lte"):
        if actual is None or expected is None:
            return False
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right
        return left <= right
    raise ValueError(f"不支持的策略操作符: {op}")


def match_conditions(context: dict[str, Any], conditions: list[dict[str, Any]]) -> bool:
    """所有条件按 AND 组合;空条件视为不匹配。"""
    if not conditions:
        return False
    for condition in conditions:
        field = str(condition.get("field", ""))
        if not field:
            return False
        actual = _get_value(context, field)
        if not _compare(actual, str(condition.get("op", "eq")), condition.get("value")):
            return False
    return True


def _rule_applies(rule_action: str, action: str) -> bool:
    candidates = {item.strip() for item in str(rule_action or "").split(",") if item.strip()}
    return "*" in candidates or action in candidates


def evaluate_rules(
    rules: list[PolicyRule], action: str, context: dict[str, Any]
) -> PolicyResult:
    """纯规则匹配(不写库),便于单测与预览。"""
    for rule in sorted(rules, key=lambda item: item.priority, reverse=True):
        if not rule.is_active or not _rule_applies(rule.action, action):
            continue
        if match_conditions(context, rule.conditions or []):
            return PolicyResult(
                decision=rule.decision,
                risk_level=rule.risk_level,
                rule_id=rule.rule_id,
                rule_version=rule.version,
                reason=rule.description or f"命中规则 {rule.rule_id}",
            )

    return PolicyResult(
        decision=DECISION_DENY,
        risk_level="high",
        rule_id=None,
        rule_version=0,
        reason="没有匹配的售后策略,默认拒绝",
    )


class PolicyEngine:
    """策略引擎(无状态,规则从数据库读取)。"""

    async def load_rules(self, db: AsyncSession) -> list[PolicyRule]:
        result = await db.execute(
            select(PolicyRule)
            .where(PolicyRule.is_active.is_(True))
            .order_by(PolicyRule.priority.desc(), PolicyRule.id.asc())
        )
        return list(result.scalars().all())

    async def preview(
        self, db: AsyncSession, action: str, context: dict[str, Any]
    ) -> PolicyResult:
        return evaluate_rules(await self.load_rules(db), action, context)

    async def evaluate(
        self, db: AsyncSession, action: str, context: dict[str, Any]
    ) -> PolicyResult:
        """评估并落一条决策审计,返回带 decision_id 的结果。"""
        result = await self.preview(db, action, context)
        decision_row = PolicyDecision(
            rule_id=result.rule_id,
            rule_version=result.rule_version,
            action=action,
            input_json=context,
            decision=result.decision,
            reason=result.reason,
        )
        db.add(decision_row)
        await db.flush()
        return replace(result, policy_decision_id=decision_row.id)


async def sync_rules_from_config(db: AsyncSession) -> int:
    """把 YAML 规则幂等同步到数据库;规则内容变化时版本号 +1。"""
    config = load_config("policy_rules")
    policies = config.get("policies") or []
    if not isinstance(policies, list):
        logger.error("policy_rules.yaml 格式错误: policies 必须是列表")
        return 0

    existing = {
        rule.rule_id: rule
        for rule in (await db.execute(select(PolicyRule))).scalars().all()
    }

    changed = 0
    for item in policies:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule_id") or "").strip()
        decision = str(item.get("decision") or "").strip()
        if not rule_id or decision not in VALID_DECISIONS:
            logger.warning("跳过无效策略规则: {}", item)
            continue

        fields = {
            "action": str(item.get("action") or ""),
            "description": str(item.get("description") or ""),
            "priority": int(item.get("priority") or 0),
            "conditions": item.get("conditions") or [],
            "decision": decision,
            "risk_level": str(item.get("risk_level") or "medium"),
            "is_active": bool(item.get("is_active", True)),
        }

        rule = existing.get(rule_id)
        if rule is None:
            db.add(
                PolicyRule(
                    rule_id=rule_id,
                    version=int(item.get("version") or 1),
                    **fields,
                )
            )
            changed += 1
            continue

        dirty = any(getattr(rule, key) != value for key, value in fields.items())
        if dirty:
            for key, value in fields.items():
                setattr(rule, key, value)
            rule.version += 1
            changed += 1

    await db.flush()
    if changed:
        logger.info("已同步 {} 条售后策略规则", changed)
    return changed

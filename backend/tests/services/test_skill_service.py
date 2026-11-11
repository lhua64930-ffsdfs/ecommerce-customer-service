"""Skills:按意图加载 Markdown 指令包并注入提示词。"""
from __future__ import annotations

from app.agents.prompts.system_prompt import (
    get_multi_step_system_prompt,
    get_system_prompt,
)
from app.core.config import settings
from app.services.rag_service import RAGService
from app.services.skill_service import SkillService


def test_skill_disabled_returns_empty(monkeypatch, tmp_path) -> None:
    (tmp_path / "refund-policy.md").write_text("退款规则", encoding="utf-8")
    monkeypatch.setattr(settings, "SKILLS_ENABLED", False)

    assert SkillService(skills_dir=str(tmp_path)).get("refund_request") == ""


def test_skill_loads_by_intent_and_ignores_bad_names(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "SKILLS_ENABLED", True)
    (tmp_path / "refund-policy.md").write_text("退款规则", encoding="utf-8")
    (tmp_path / "Bad Name.md").write_text("ignored", encoding="utf-8")

    service = SkillService(skills_dir=str(tmp_path))

    assert service.get("refund_request") == "退款规则"
    assert service.get("cancel_order") == "退款规则"
    assert service.get("unknown_intent") == ""


def test_skill_is_injected_into_prompts(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SKILLS_ENABLED", True)

    single = get_system_prompt("特殊售后规则")
    multi = get_multi_step_system_prompt("特殊售后规则")
    rag = RAGService.build_prompt("能退吗", "知识库内容", "特殊售后规则")

    assert "当前场景操作说明" in single
    assert "特殊售后规则" in single
    assert "当前场景操作说明" in multi
    assert "特殊售后规则" in multi
    assert "当前场景操作说明" in rag
    assert "特殊售后规则" in rag


def test_prompt_unchanged_without_skill() -> None:
    assert "当前场景操作说明" not in get_system_prompt()
    assert "当前场景操作说明" not in get_multi_step_system_prompt()

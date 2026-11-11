"""Langfuse 观测:未配置时 no-op,启用时输出 trace 元数据。"""
from __future__ import annotations

from app.core import observability
from app.core.config import settings


def _disable_langfuse(monkeypatch) -> None:
    monkeypatch.setattr(settings, "LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr(settings, "LANGFUSE_SECRET_KEY", "")
    monkeypatch.setattr(settings, "LANGFUSE_BASE_URL", "")
    monkeypatch.setattr(observability, "_handler", None)


def test_langfuse_is_noop_without_configuration(monkeypatch) -> None:
    _disable_langfuse(monkeypatch)

    assert observability.langfuse_enabled() is False
    assert observability.get_callbacks() == []
    assert observability.langchain_config("session-1", 7) == {}
    with observability.trace_scope("session-1", 7):
        pass
    observability.tag_current_trace(
        metadata={"intent": "order_query"}, tags=["intent:order_query"]
    )
    observability.shutdown_observability()


def test_langchain_config_carries_trace_metadata(monkeypatch) -> None:
    monkeypatch.setattr(settings, "LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setattr(settings, "LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setattr(settings, "LANGFUSE_BASE_URL", "http://langfuse:3000")
    sentinel = object()
    monkeypatch.setattr(observability, "_handler", sentinel)

    config = observability.langchain_config(
        session_id="session-1",
        user_id=7,
        trace_name="multi_step_agent",
        tags=["agent"],
    )

    assert config["callbacks"] == [sentinel]
    assert config["metadata"] == {
        "langfuse_trace_name": "multi_step_agent",
        "langfuse_session_id": "session-1",
        "langfuse_user_id": "7",
        "langfuse_tags": ["agent"],
    }

"""LLM 终端错误分类:鉴权/余额不重试。"""
from __future__ import annotations

from types import SimpleNamespace

from app.services.llm_service import _is_terminal_error


def test_terminal_by_status_code() -> None:
    assert _is_terminal_error(SimpleNamespace(status_code=401)) is True
    assert _is_terminal_error(SimpleNamespace(status_code=402)) is True
    assert _is_terminal_error(SimpleNamespace(status_code=403)) is True
    assert _is_terminal_error(SimpleNamespace(status_code=500)) is False


def test_terminal_by_message() -> None:
    assert _is_terminal_error(Exception("Insufficient Balance")) is True
    assert _is_terminal_error(Exception("余额不足")) is True
    assert _is_terminal_error(Exception("Connection reset")) is False

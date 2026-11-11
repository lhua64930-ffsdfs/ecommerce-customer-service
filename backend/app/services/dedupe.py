"""候选知识去重:标准化 + 词面相似度。

不额外调用模型:知识飞轮是批处理,用 difflib 做确定性近似去重即可;
阈值默认 0.85,避免近似重复问题反复进入审核队列。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

_STRIP_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize_question(question: str) -> str:
    return _STRIP_RE.sub("", (question or "").strip().lower())


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_question(left), normalize_question(right)).ratio()


def dedupe_candidates(
    candidates: list[dict[str, Any]],
    existing_questions: list[str],
    threshold: float = 0.85,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []
    known = [normalize_question(item) for item in existing_questions]

    for candidate in candidates:
        question = str(candidate.get("question") or "")
        normalized = normalize_question(question)
        if not normalized:
            discarded.append(candidate)
            continue
        if any(
            normalized == existing or similarity(question, existing) >= threshold
            for existing in known
        ):
            discarded.append(candidate)
            continue
        kept.append(candidate)
        known.append(normalized)

    return kept, discarded

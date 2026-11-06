"""种子数据补缺逻辑单测(不连接数据库)。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.seed import _seed_knowledge
from app.models.knowledge import Knowledge

ROOT = Path(__file__).resolve().parents[2]
FAQ_PATH = ROOT / "knowledge_base" / "faqs.json"


class _FakeScalars:
    def __init__(self, items: list[Knowledge]) -> None:
        self._items = items

    def all(self) -> list[Knowledge]:
        return list(self._items)


class _FakeResult:
    def __init__(self, items: list[Knowledge]) -> None:
        self._items = items

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._items)


class _FakeSession:
    """只实现 _seed_knowledge 用到的最小接口。"""

    def __init__(self, existing: list[Knowledge]) -> None:
        self.existing = existing
        self.added: list[Knowledge] = []

    async def execute(self, statement: Any) -> _FakeResult:
        return _FakeResult(self.existing)

    def add_all(self, items: list[Knowledge]) -> None:
        self.added.extend(items)

    async def flush(self) -> None:
        for index, item in enumerate(self.added, start=100):
            item.id = index


def _knowledge(entry: dict[str, Any], item_id: int, vector_id: str | None) -> Knowledge:
    return Knowledge(
        id=item_id,
        category=entry["category"],
        question=entry["question"],
        answer=entry["answer"],
        keywords=entry["keywords"],
        vector_id=vector_id,
    )


async def test_seed_knowledge_backfills_missing_question() -> None:
    entries = json.loads(FAQ_PATH.read_text(encoding="utf-8"))
    existing = [
        _knowledge(entry, index, str(index))
        for index, entry in enumerate(entries[:-1], start=1)
    ]
    session = _FakeSession(existing)

    pending_vectors = await _seed_knowledge(session)  # type: ignore[arg-type]

    assert len(session.added) == 1
    assert session.added[0].question == entries[-1]["question"]
    assert pending_vectors == session.added
    assert pending_vectors[0].vector_id is None


async def test_seed_knowledge_skips_existing_questions() -> None:
    entries = json.loads(FAQ_PATH.read_text(encoding="utf-8"))
    existing = [
        _knowledge(entry, index, str(index))
        for index, entry in enumerate(entries, start=1)
    ]
    session = _FakeSession(existing)

    pending_vectors = await _seed_knowledge(session)  # type: ignore[arg-type]

    assert session.added == []
    assert pending_vectors == []

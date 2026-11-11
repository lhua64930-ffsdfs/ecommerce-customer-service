"""Skills:按意图加载 skills/*.md 运维指令包。

- 只在 SKILLS_ENABLED=true 时读文件,默认零 I/O;
- 目录按文件 mtime 缓存,改 Markdown 后无需重启;
- 指令包只追加到系统提示词,不改变工具/RAG 的代码路径。
"""
from __future__ import annotations

import re
from pathlib import Path

from app.core.config import settings
from app.utils.logger import logger

# 意图 -> 技能文件名(不含 .md)
INTENT_SKILLS: dict[str, str] = {
    "refund_request": "refund-policy",
    "cancel_order": "refund-policy",
    "after_sale": "after-sales",
    "complaint": "after-sales",
    "human_agent": "after-sales",
    "order_query": "order-query",
    "order_modify": "order-query",
    "shipping": "logistics",
}

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


class SkillService:
    """加载并缓存技能包;未启用时返回空串。"""

    def __init__(
        self,
        skills_dir: str | None = None,
        max_chars: int | None = None,
    ) -> None:
        base = Path(skills_dir or settings.SKILLS_DIR)
        self.dir = base if base.is_absolute() else Path(__file__).resolve().parents[2] / base
        self.max_chars = settings.SKILLS_MAX_CHARS if max_chars is None else max_chars
        self._cache: dict[str, str] = {}
        self._signature: tuple[tuple[str, float], ...] = ()

    def _load_all(self) -> dict[str, str]:
        if not self.dir.is_dir():
            return {}
        files = sorted(self.dir.glob("*.md"))
        signature = tuple((item.name, item.stat().st_mtime) for item in files)
        if signature == self._signature:
            return self._cache

        cache: dict[str, str] = {}
        for file in files:
            slug = file.stem
            if not _SLUG_RE.fullmatch(slug):
                logger.warning("忽略非法技能文件名: {}", file.name)
                continue
            try:
                cache[slug] = file.read_text(encoding="utf-8")[: self.max_chars]
            except OSError as exc:
                logger.warning("读取技能包失败 [{}]: {}", file.name, exc)
        self._cache = cache
        self._signature = signature
        return cache

    def get(self, intent_code: str) -> str:
        """返回该意图对应的技能文本;未启用/未匹配时为空串。"""
        if not settings.SKILLS_ENABLED:
            return ""
        slug = INTENT_SKILLS.get(intent_code)
        if not slug:
            return ""
        return self._load_all().get(slug, "").strip()

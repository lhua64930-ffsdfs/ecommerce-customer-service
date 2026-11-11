"""文档切块:Markdown 标题分层 + 中文递归切分 + 句级 overlap。

- Markdown 按 #/##/###/#### 切成 section,记录 section_path;
- 超长 section 按中文标点递归切分,避免把一句话切断;
- 相邻 chunk 用完整句 overlap,缓解边界信息丢失。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

HEADER_RE = re.compile(r"^(#{1,4})\s+(.*)$")
CJK_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "!", "?", ";", "，", " ", ""]
SENTENCE_RE = re.compile(r"[^。！？!?…\n]*[。！？!?…\n]|[^。！？!?…\n]+$")


@dataclass(frozen=True)
class DocumentChunk:
    section_path: str
    chunk_index: int
    content: str


def _split_sentences(text: str) -> list[str]:
    return [item for item in SENTENCE_RE.findall(text) if item]


def _trailing_sentences(text: str, max_chars: int) -> str:
    out: list[str] = []
    total = 0
    for sentence in reversed(_split_sentences(text)):
        if out and total + len(sentence) > max_chars:
            break
        out.insert(0, sentence)
        total += len(sentence)
    return "".join(out)


def _recursive_split(
    text: str, chunk_size: int, separators: list[str]
) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    for index, separator in enumerate(separators):
        if not separator:
            continue
        if separator not in text:
            continue

        parts = text.split(separator)
        chunks: list[str] = []
        buffer = ""
        for part in parts:
            candidate = f"{buffer}{separator}{part}" if buffer else part
            if len(candidate) <= chunk_size:
                buffer = candidate
                continue
            if buffer:
                chunks.append(buffer)
            if len(part) > chunk_size:
                chunks.extend(
                    _recursive_split(part, chunk_size, separators[index + 1 :])
                )
                buffer = ""
            else:
                buffer = part
        if buffer:
            chunks.append(buffer)
        return [chunk.strip() for chunk in chunks if chunk.strip()]

    return [
        text[start : start + chunk_size]
        for start in range(0, len(text), chunk_size)
    ]


def split_markdown(
    markdown: str,
    chunk_size: int = 500,
    overlap: int = 80,
) -> list[DocumentChunk]:
    """把 Markdown 切为带 section_path 的片段。"""
    lines = (markdown or "").splitlines()
    sections: list[tuple[str, str]] = []
    path: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            sections.append((" > ".join(path) or "正文", text))
        buffer.clear()

    for line in lines:
        match = HEADER_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            path = path[: level - 1] + [match.group(2).strip()]
            continue
        buffer.append(line)
    flush()

    chunks: list[DocumentChunk] = []
    for section_path, text in sections:
        pieces = _recursive_split(text, chunk_size, CJK_SEPARATORS)
        previous = ""
        for index, piece in enumerate(pieces):
            content = piece
            if previous and overlap > 0:
                prefix = _trailing_sentences(previous, overlap)
                if prefix and not content.startswith(prefix):
                    content = f"{prefix}{content}"
            chunks.append(
                DocumentChunk(
                    section_path=section_path,
                    chunk_index=index,
                    content=content,
                )
            )
            previous = piece
    return chunks

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
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


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


def _find_table_header(lines: list[str]) -> int:
    """返回表头行下标(其后紧跟 --- 分隔行);无表格返回 -1。"""
    for index in range(len(lines) - 1):
        if (
            lines[index].lstrip().startswith("|")
            and TABLE_SEP_RE.match(lines[index + 1])
            and "-" in lines[index + 1]
        ):
            return index
    return -1


def is_table_block(text: str) -> bool:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return _find_table_header(lines) != -1


def split_table_rows(table_md: str, max_rows: int) -> list[str]:
    """大表格按行切,每块重贴表头行 + 分隔行;首块保留表头前的散文行。"""
    lines = [line for line in table_md.strip().splitlines() if line.strip()]
    header_index = _find_table_header(lines)
    if header_index == -1:
        return [table_md.strip()]
    preamble = lines[:header_index]
    header = lines[header_index]
    separator = lines[header_index + 1]
    rows = lines[header_index + 2 :]
    if len(rows) <= max_rows:
        return [table_md.strip()]
    pieces: list[str] = []
    for index, start in enumerate(range(0, len(rows), max_rows)):
        group = rows[start : start + max_rows]
        block = (
            [*preamble, header, separator, *group]
            if index == 0
            else [header, separator, *group]
        )
        pieces.append("\n".join(block))
    return pieces


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
    table_max_rows: int = 10,
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
        table_block = is_table_block(text)
        pieces = (
            split_table_rows(text, table_max_rows)
            if table_block
            else _recursive_split(text, chunk_size, CJK_SEPARATORS)
        )
        previous = ""
        for index, piece in enumerate(pieces):
            content = piece
            if not table_block and previous and overlap > 0:
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

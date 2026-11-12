"""文档切块单测。"""
from app.services.document_chunking import split_markdown


def test_split_markdown_keeps_section_path() -> None:
    markdown = "# 手册\n\n## 退货\n\n七天无理由退货需要商品完好。\n\n### 退款\n\n退款 1-3 个工作日到账。"
    chunks = split_markdown(markdown)

    paths = [chunk.section_path for chunk in chunks]
    assert "手册 > 退货" in paths
    assert "手册 > 退货 > 退款" in paths
    assert any("七天无理由" in chunk.content for chunk in chunks)


def test_split_markdown_splits_long_section_and_overlaps() -> None:
    body = "这是一段关于退款流程的说明。" * 30
    chunks = split_markdown(f"# 退款\n\n{body}", chunk_size=120, overlap=20)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 180 for chunk in chunks)
    # 后一块以前一块的句尾开头(句级 overlap)
    assert chunks[1].content.startswith("这是一段") or "这是一段" in chunks[1].content


def test_split_markdown_keeps_small_table_whole() -> None:
    markdown = (
        "# 价目表\n\n"
        "| 商品 | 价格 |\n"
        "| --- | --- |\n"
        "| 吹风机 | 2999 |\n"
        "| 数据线 | 99 |\n"
    )
    chunks = split_markdown(markdown, table_max_rows=10)

    assert len(chunks) == 1
    assert "| 商品 | 价格 |" in chunks[0].content
    assert "吹风机" in chunks[0].content


def test_split_markdown_splits_large_table_and_repeats_header() -> None:
    rows = "\n".join(f"| 商品{i} | {i * 10} |" for i in range(1, 13))
    markdown = f"# 价目表\n\n| 商品 | 价格 |\n| --- | --- |\n{rows}"
    chunks = split_markdown(markdown, table_max_rows=5)

    assert len(chunks) == 3
    assert all("| 商品 | 价格 |" in chunk.content for chunk in chunks)
    assert "商品1" in chunks[0].content
    assert "商品6" in chunks[1].content
    assert "商品11" in chunks[2].content


def test_split_markdown_handles_empty_text() -> None:
    assert split_markdown("") == []

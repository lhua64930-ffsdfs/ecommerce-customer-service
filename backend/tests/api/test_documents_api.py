"""文档知识导入/删除接口测试。"""
from __future__ import annotations

import uuid

import httpx


async def test_import_list_and_delete_document(client: httpx.AsyncClient) -> None:
    title = f"测试文档-{uuid.uuid4().hex[:8]}"
    content = (
        "# 测试手册\n\n"
        "## 退货\n\n七天无理由退货需要商品完好。\n\n"
        "## 退款\n\n退款 1-3 个工作日原路退回。"
    )

    imported = await client.post(
        "/api/v1/knowledge/documents/import",
        json={"title": title, "source": "test.md", "content": content},
    )
    assert imported.status_code == 200
    data = imported.json()
    assert data["chunks"] >= 2
    assert data["vectorized"] is True
    document_id = data["document_id"]

    listed = await client.get("/api/v1/knowledge/documents")
    assert listed.status_code == 200
    assert any(item["id"] == document_id for item in listed.json()["items"])

    deleted = await client.delete(f"/api/v1/knowledge/documents/{document_id}")
    assert deleted.status_code == 200
    assert deleted.json()["success"] is True

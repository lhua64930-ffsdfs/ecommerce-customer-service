"""只读观测 API:概览、运行列表、回放与成本。"""
from __future__ import annotations


async def test_observability_overview(client) -> None:
    response = await client.get("/api/v1/observability/overview")

    assert response.status_code == 200
    data = response.json()
    assert "runs" in data
    assert "steps" in data
    assert "low_confidence" in data
    assert "approvals" in data
    assert "langfuse_enabled" in data


async def test_observability_runs_and_cost(client) -> None:
    runs = await client.get("/api/v1/observability/runs?days=7&limit=5")
    assert runs.status_code == 200
    assert isinstance(runs.json()["items"], list)

    cost = await client.get("/api/v1/observability/cost?days=30")
    assert cost.status_code == 200
    assert isinstance(cost.json()["items"], list)


async def test_observability_run_detail_not_found(client) -> None:
    response = await client.get("/api/v1/observability/runs/not-exist")
    assert response.status_code == 404

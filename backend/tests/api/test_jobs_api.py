"""后台作业接口测试。"""
import httpx


async def test_jobs_list_exposes_whitelist(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/jobs")

    assert response.status_code == 200
    names = {item["name"] for item in response.json()["jobs"]}
    assert {"evaluate-rag", "evaluate-refusal", "mine-knowledge"}.issubset(names)


async def test_unknown_job_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/jobs/not-a-job")

    assert response.status_code == 404

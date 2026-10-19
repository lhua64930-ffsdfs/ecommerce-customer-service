"""pytest 公共夹具。

集成测试直接使用本机 Docker 容器(MySQL / Redis / Milvus),
启动 lifespan 完成建表与种子数据(幂等)。
"""
from collections.abc import AsyncGenerator

import httpx
import pytest

from app.main import app


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client

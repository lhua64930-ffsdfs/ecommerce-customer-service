"""pytest 公共夹具。

集成测试直接使用本机 Docker 容器(MySQL / Redis / Milvus),
启动 lifespan 完成建表与种子数据(幂等)。
"""
from collections.abc import AsyncGenerator, Iterator

import httpx
import pytest

from app.api.deps import get_chat_model
from app.main import app


@pytest.fixture(autouse=True)
def _no_real_chat_model() -> Iterator[None]:
    """默认禁用真实 ChatModel,测试绝不会访问 DeepSeek。

    需要多步路径的测试在用例内覆盖 ``get_chat_model`` 注入脚本化模型。
    """
    app.dependency_overrides[get_chat_model] = lambda: None
    yield
    app.dependency_overrides.pop(get_chat_model, None)


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client

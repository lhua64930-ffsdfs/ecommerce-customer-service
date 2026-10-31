"""pytest 公共夹具。

集成测试直接使用本机 Docker 容器(MySQL / Redis / Milvus),
启动 lifespan 完成建表与种子数据(幂等)。
"""
from collections.abc import AsyncGenerator, Iterator

import httpx
import pytest

from app.api.deps import get_chat_model
from app.main import app
from app.services.llm_service import LLMService


@pytest.fixture(autouse=True)
def _no_real_chat_model() -> Iterator[None]:
    """禁用所有真实 LLM 调用,测试绝不访问 DeepSeek。

    - 多步图的 ChatModel 由 ``get_chat_model`` 依赖提供,默认返回 None;
    - 单步路径的 IntentService 直接使用 LLMService 单例,这里强制 mock,
      避免开发者本地配置了 API Key 时测试仍然打真实接口。
    需要多步路径的测试在用例内覆盖 ``get_chat_model`` 注入脚本化模型。
    """
    app.dependency_overrides[get_chat_model] = lambda: None
    llm_service = LLMService()
    original_is_mock = llm_service.is_mock
    llm_service.is_mock = True
    yield
    llm_service.is_mock = original_is_mock
    app.dependency_overrides.pop(get_chat_model, None)


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client

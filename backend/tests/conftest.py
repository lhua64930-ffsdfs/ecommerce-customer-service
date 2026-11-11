"""pytest 公共夹具。

集成测试直接使用本机 Docker 容器(MySQL / Redis / Milvus),
启动 lifespan 完成建表与种子数据(幂等)。
"""
from collections.abc import AsyncGenerator, Iterator

import httpx
import pytest
from sqlalchemy import select

from app.api.deps import get_chat_model
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.order import Order
from app.services.llm_service import LLMService

DEMO_ORDER_STATUS = {
    "ORDER20260315001": "shipped",
    "ORDER20260401001": "paid",
    "ORDER20260310005": "delivered",
    "ORDER20260320001": "pending",
}


@pytest.fixture(autouse=True)
async def _fresh_redis_client() -> AsyncGenerator[None, None]:
    """每个测试使用新的事件循环,重置 Redis 单例避免跨 loop 复用连接。"""
    from app.utils import cache

    cache._client = None
    cache.reset_redis_state()
    yield
    try:
        await cache.close_redis()
    except Exception:  # noqa: BLE001 - 清理失败不阻塞测试
        cache._client = None
    cache.reset_redis_state()


@pytest.fixture(autouse=True)
def _memory_checkpointer(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试不落 SQLite 文件,统一用 InMemorySaver。"""
    monkeypatch.setattr(settings, "CHECKPOINTER_BACKEND", "memory")


@pytest.fixture(autouse=True)
def _reset_circuit_breakers() -> Iterator[None]:
    """熔断器是进程单例,测试间重置,避免失败用例影响后续。"""
    from app.core import circuit

    breakers = (circuit.chat_breaker, circuit.embed_breaker, circuit.rerank_breaker)
    for breaker in breakers:
        breaker.reset()
    yield
    for breaker in breakers:
        breaker.reset()


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


@pytest.fixture
async def demo_orders(
    client: httpx.AsyncClient,
) -> AsyncGenerator[dict[str, str], None]:
    """把演示订单恢复到种子状态,保证审批/取消类用例可重复执行。"""

    async def _reset() -> None:
        async with AsyncSessionLocal() as session:
            for order_no, status in DEMO_ORDER_STATUS.items():
                order = (
                    await session.execute(
                        select(Order).where(Order.order_no == order_no)
                    )
                ).scalar_one_or_none()
                if order is not None:
                    order.status = status
            await session.commit()

    await _reset()
    yield DEMO_ORDER_STATUS
    await _reset()

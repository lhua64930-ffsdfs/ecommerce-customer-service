"""意图识别与实体抽取测试。"""
import pytest

from app.services.intent_service import IntentService


@pytest.fixture
def service() -> IntentService:
    return IntentService()


async def test_order_intent_and_entity(service: IntentService) -> None:
    result = await service.recognize("查订单 ORDER20260315001")

    assert result.intent_code == "order_query"
    assert result.handler_type == "tool"
    assert any(
        entity.type == "order_no" and entity.value == "ORDER20260315001"
        for entity in result.entities
    )


async def test_refund_intent(service: IntentService) -> None:
    result = await service.recognize("我要申请退款")

    assert result.intent_code == "refund_request"
    assert result.handler_type == "tool"


async def test_human_agent_intent(service: IntentService) -> None:
    result = await service.recognize("给我转人工")

    assert result.intent_code == "human_agent"
    assert result.handler_type == "transfer"


async def test_phone_entity(service: IntentService) -> None:
    result = await service.recognize("我的手机号是 13812345678,请帮我查订单")

    assert any(
        entity.type == "phone" and entity.value == "13812345678"
        for entity in result.entities
    )


async def test_empty_text_falls_back(service: IntentService) -> None:
    result = await service.recognize("   ")

    assert result.intent_code == "fallback"
    assert result.handler_type == "llm"

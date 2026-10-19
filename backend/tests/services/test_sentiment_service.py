"""情感分析规则测试(覆盖文档示例中的两个 bug)。"""
import pytest

from app.services.sentiment_service import SentimentService, SentimentType


@pytest.fixture
def service() -> SentimentService:
    return SentimentService()


async def test_exclamation_does_not_flip_negative(service: SentimentService) -> None:
    """感叹号只能放大强度,不能把负面拉成正分。"""
    sentiment, score = await service.analyze("太差了!!!")

    assert sentiment == SentimentType.NEGATIVE
    assert score <= -0.3


async def test_negation_flips_polarity(service: SentimentService) -> None:
    """「不差」应识别为弱正面,而不是负面。"""
    sentiment, score = await service.analyze("不差,挺满意的")

    assert score > 0
    assert sentiment == SentimentType.POSITIVE


async def test_positive_words(service: SentimentService) -> None:
    sentiment, score = await service.analyze("谢谢,非常满意,推荐购买")

    assert sentiment == SentimentType.POSITIVE
    assert score >= 0.3


async def test_neutral_text(service: SentimentService) -> None:
    sentiment, score = await service.analyze("我想查询一下订单状态")

    assert sentiment == SentimentType.NEUTRAL
    assert score == 0.0

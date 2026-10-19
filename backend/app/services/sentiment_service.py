"""情感分析服务:词典 + 规则。

相比文档示例修复了两个逻辑问题:
1. 否定词判断:只看情感词前面 4 个字符的窗口,而不是全文第一个否定词;
2. 感叹号/重复字符只作为"强度"放大器,不再无条件加正分
   (避免"太差了!!!"因为感叹号被拉向正面)。
"""
from __future__ import annotations

import re
from enum import Enum

from app.utils.logger import logger


class SentimentType(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class SentimentService:
    """情感分析服务(无状态,可直接实例化)。"""

    NEGATIVE_WORDS: dict[str, float] = {
        "非常差": -1.0, "很差": -0.9, "太差": -0.9, "差": -0.8,
        "不满意": -0.7, "失望": -0.7, "生气": -0.9, "愤怒": -1.0,
        "投诉": -0.8, "骗子": -1.0, "糟糕": -0.8, "后悔": -0.6,
        "垃圾": -0.9, "坑人": -0.9, "恶心": -0.8, "无语": -0.5,
        "退货": -0.4, "退款": -0.3, "慢": -0.4, "拖": -0.4,
    }

    POSITIVE_WORDS: dict[str, float] = {
        "非常好": 1.0, "很好": 0.9, "棒": 0.8, "满意": 0.7,
        "喜欢": 0.8, "感谢": 0.6, "谢谢": 0.5, "好评": 0.8,
        "推荐": 0.7, "划算": 0.6, "便宜": 0.5, "漂亮": 0.7,
        "及时": 0.5, "耐心": 0.6, "专业": 0.5,
    }

    NEGATION_WORDS = ("不", "没", "无", "非", "别", "勿", "未")

    def __init__(self) -> None:
        # 长词优先,避免"非常差"被拆成"差"重复计分
        self._words = sorted(
            list(self.NEGATIVE_WORDS.items()) + list(self.POSITIVE_WORDS.items()),
            key=lambda item: -len(item[0]),
        )

    async def analyze(self, text: str) -> tuple[SentimentType, float]:
        """返回 (情感类型, 情感得分 -1.0 ~ 1.0)。"""
        text = text or ""
        base_score = self._lexicon_analysis(text)
        score = max(-1.0, min(1.0, base_score * self._intensity(text)))
        sentiment_type = self._score_to_type(score)
        logger.debug("情感分析: text={!r} score={:.3f} type={}", text[:30], score, sentiment_type.value)
        return sentiment_type, round(score, 4)

    # ---------------- 内部实现 ----------------
    def _lexicon_analysis(self, text: str) -> float:
        matches = self._match_words(text)
        if not matches:
            return 0.0

        total = 0.0
        for _word, score, position in matches:
            if self._is_negated(text, position):
                total += -score * 0.6   # "不差" → 弱正面
            else:
                total += score

        return max(-1.0, min(1.0, total / len(matches)))

    def _match_words(self, text: str) -> list[tuple[str, float, int]]:
        """最长匹配优先,已占用的字符不重复计分。"""
        occupied = [False] * len(text)
        matches: list[tuple[str, float, int]] = []

        for word, score in self._words:
            start = 0
            while True:
                index = text.find(word, start)
                if index < 0:
                    break
                end = index + len(word)
                if not any(occupied[index:end]):
                    for i in range(index, end):
                        occupied[i] = True
                    matches.append((word, score, index))
                start = index + 1

        return matches

    def _is_negated(self, text: str, index: int) -> bool:
        """只看情感词前 4 个字符内是否有否定词。"""
        window = text[max(0, index - 4):index]
        return any(neg in window for neg in self.NEGATION_WORDS)

    @staticmethod
    def _intensity(text: str) -> float:
        """标点/重复字符只放大强度,不改变情感方向。"""
        exclamations = text.count("!") + text.count("！")
        repeats = len(re.findall(r"(.)\1{2,}", text))
        return 1.0 + min(0.5, 0.1 * (exclamations + repeats))

    @staticmethod
    def _score_to_type(score: float) -> SentimentType:
        if score <= -0.3:
            return SentimentType.NEGATIVE
        if score >= 0.3:
            return SentimentType.POSITIVE
        return SentimentType.NEUTRAL

    def get_response_strategy(self, sentiment: SentimentType, score: float) -> dict:
        """根据情感返回回复策略(供 Agent 使用)。"""
        strategies = {
            SentimentType.NEGATIVE: {
                "tone": "empathetic",
                "prefix": "很抱歉给您带来不愉快的体验",
                "action": "优先安抚,必要时转人工",
                "emoji": "😔",
            },
            SentimentType.NEUTRAL: {
                "tone": "professional",
                "prefix": "您好",
                "action": "正常服务流程",
                "emoji": "🤖",
            },
            SentimentType.POSITIVE: {
                "tone": "friendly",
                "prefix": "很高兴为您服务",
                "action": "主动推荐关联服务",
                "emoji": "😊",
            },
        }
        return strategies.get(sentiment, strategies[SentimentType.NEUTRAL])

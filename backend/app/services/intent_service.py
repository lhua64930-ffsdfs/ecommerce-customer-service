"""意图识别服务:关键词匹配 + LLM 理解双路融合 + 实体抽取。

与文档示例的差异:
- 意图融合改为 `confidence * (0.6 + 0.04 * priority)`,避免 priority 量级
  直接把 LLM 结果压死(文档里 0.7*10 > 0.95*5);
- LLM 返回的意图会映射回其配置的 handler_type(该走工具就走工具);
- 实体抽取返回真实位置 start/end,而不是恒为 0。
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.intent import Entity, IntentResult
from app.services.llm_service import LLMError, LLMService
from app.utils.logger import logger


class IntentService:
    """意图识别服务(单例)。"""

    _instance: "IntentService | None" = None

    # 意图配置:code -> (中文名, 关键词, 处理器类型, 优先级)
    INTENT_CONFIGS: dict[str, dict[str, Any]] = {
        "product_inquiry": {
            "name": "商品咨询",
            "keywords": ["商品", "产品", "多少钱", "价格", "怎么样", "好不好", "推荐"],
            "handler": "rag", "priority": 5,
        },
        "promotion": {
            "name": "促销活动",
            "keywords": ["促销", "优惠", "活动", "满减", "打折", "折扣", "618", "双11", "双十一"],
            "handler": "rag", "priority": 4,
        },
        "shipping": {
            "name": "配送时效",
            "keywords": ["配送", "发货时间", "多久到", "几天到", "送达", "运费", "包邮"],
            "handler": "rag", "priority": 5,
        },
        "payment": {
            "name": "支付问题",
            "keywords": ["支付", "付款", "支付宝", "微信支付", "花呗", "银行卡", "分期"],
            "handler": "rag", "priority": 4,
        },
        "coupon": {
            "name": "优惠券使用",
            "keywords": ["优惠券", "红包", "抵扣", "券怎么用"],
            "handler": "rag", "priority": 3,
        },
        "membership": {
            "name": "会员权益",
            "keywords": ["会员", "积分", "vip", "权益", "等级"],
            "handler": "rag", "priority": 3,
        },
        "after_sale": {
            "name": "售后政策",
            "keywords": ["保修", "质保", "售后", "维修", "退换"],
            "handler": "rag", "priority": 4,
        },
        "order_query": {
            "name": "订单查询",
            "keywords": ["订单", "查订单", "发货没", "物流", "快递", "到哪了", "什么时候到"],
            "handler": "tool", "priority": 8,
        },
        "order_modify": {
            "name": "订单修改",
            "keywords": ["修改订单", "改地址", "修改地址", "改收货", "换地址"],
            "handler": "tool", "priority": 7,
        },
        "cancel_order": {
            "name": "取消订单",
            "keywords": ["取消订单", "取消", "不要了", "撤单"],
            "handler": "tool", "priority": 9,
        },
        "refund_request": {
            "name": "退款退货",
            "keywords": ["退款", "退货", "退钱", "返款", "退换货"],
            "handler": "tool", "priority": 10,
        },
        "complaint": {
            "name": "投诉建议",
            "keywords": ["投诉", "差评", "太差", "骗子", "态度差", "差劲"],
            "handler": "transfer", "priority": 10,
        },
        "human_agent": {
            "name": "人工客服",
            "keywords": ["人工", "转人工", "真人", "人工服务", "找客服"],
            "handler": "transfer", "priority": 10,
        },
        "greeting": {
            "name": "问候",
            "keywords": ["你好", "您好", "hi", "hello", "在吗", "在不在"],
            "handler": "llm", "priority": 1,
        },
        "fallback": {
            "name": "其他",
            "keywords": [],
            "handler": "llm", "priority": 0,
        },
    }

    def __new__(cls) -> "IntentService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.llm_service = LLMService()

    async def recognize(self, text: str, user_id: int | None = None) -> IntentResult:
        """识别用户意图。"""
        text = (text or "").strip()
        if not text:
            return self._fallback_result()

        keyword_result = self._keyword_match(text)
        llm_result = await self._llm_understand(text)
        final_result = self._fuse(keyword_result, llm_result)

        entities = self._extract_entities(text)
        final_result = final_result.model_copy(update={"entities": entities})

        logger.info(
            "意图识别完成: code={} confidence={:.2f} handler={}",
            final_result.intent_code,
            final_result.confidence,
            final_result.handler_type,
        )
        return final_result

    # ---------------- 关键词匹配 ----------------
    def _keyword_match(self, text: str) -> IntentResult | None:
        lowered = text.lower()
        best: IntentResult | None = None
        best_score = 0.0

        for code, config in self.INTENT_CONFIGS.items():
            matched = [kw for kw in config["keywords"] if kw.lower() in lowered]
            if not matched:
                continue

            # 命中词越长、数量越多,置信度越高
            match_score = sum(len(kw) for kw in matched)
            if match_score > best_score:
                best_score = float(match_score)
                best = IntentResult(
                    intent_code=code,
                    intent_name=config["name"],
                    confidence=round(min(0.95, 0.65 + 0.05 * len(matched)), 4),
                    entities=[],
                    handler_type=config["handler"],
                    priority=config["priority"],
                )

        return best

    # ---------------- LLM 理解 ----------------
    async def _llm_understand(self, text: str) -> IntentResult | None:
        intent_lines = "\n".join(
            f"- {code}: {config['name']}"
            for code, config in self.INTENT_CONFIGS.items()
            if code != "fallback"
        )
        prompt = (
            "你是电商客服系统的意图分类器。请分析用户输入,只返回 JSON。\n\n"
            f"用户输入:{text}\n\n"
            f"可选意图:\n{intent_lines}\n- fallback: 其他\n\n"
            '返回格式:{"intent_code": "上面某个意图代码", "confidence": 0.0到1.0之间}'
        )

        try:
            raw = await self.llm_service.generate(prompt, temperature=0.1, json_mode=True)
        except LLMError as exc:
            logger.warning("LLM 意图理解失败,仅使用关键词结果: {}", exc)
            return None

        data = self._parse_json(raw)
        if not data:
            return None

        code = str(data.get("intent_code", "fallback"))
        config = self.INTENT_CONFIGS.get(code, self.INTENT_CONFIGS["fallback"])
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5

        return IntentResult(
            intent_code=code if code in self.INTENT_CONFIGS else "fallback",
            intent_name=config["name"],
            confidence=round(max(0.0, min(1.0, confidence)), 4),
            entities=[],
            handler_type=config["handler"],
            priority=config["priority"],
        )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | None:
        """容错解析 LLM 返回的 JSON(可能带代码块或前后说明)。"""
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)
        try:
            data = json.loads(cleaned)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            logger.warning("LLM 返回内容无法解析为 JSON: {}", raw[:100])
            return None

    # ---------------- 融合 ----------------
    def _fuse(self, *candidates: IntentResult | None) -> IntentResult:
        valid = [item for item in candidates if item is not None]
        if not valid:
            return self._fallback_result()

        def weight(result: IntentResult) -> float:
            # priority 0~10 映射为 0.6~1.0 的乘数,避免量级压制
            priority_factor = 0.6 + 0.04 * min(max(result.priority, 0), 10)
            return result.confidence * priority_factor

        return max(valid, key=weight)

    def _fallback_result(self) -> IntentResult:
        config = self.INTENT_CONFIGS["fallback"]
        return IntentResult(
            intent_code="fallback",
            intent_name=config["name"],
            confidence=0.5,
            entities=[],
            handler_type=config["handler"],
            priority=config["priority"],
        )

    # ---------------- 实体抽取 ----------------
    ENTITY_PATTERNS: dict[str, str] = {
        "order_no": r"ORDER[A-Za-z0-9]{8,20}",
        "phone": r"1[3-9]\d{9}",
        "product_name": r"[《「\"]([^》」\"]{2,30})[》」\"]",
        "price": r"[¥￥]\s*\d+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?\s*元",
        "date": r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?",
    }

    def _extract_entities(self, text: str) -> list[Entity]:
        entities: list[Entity] = []
        for entity_type, pattern in self.ENTITY_PATTERNS.items():
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = match.group(0)
                if entity_type == "product_name" and match.lastindex:
                    value = match.group(1)
                if entity_type == "order_no":
                    value = value.upper()
                entities.append(
                    Entity(type=entity_type, value=value, start=match.start(), end=match.end())
                )
        return entities

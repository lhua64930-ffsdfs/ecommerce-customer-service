"""意图识别相关 Schema。"""
from pydantic import BaseModel, Field


class Entity(BaseModel):
    """从用户消息中抽取的实体。"""

    type: str = Field(..., description="实体类型: order_no / phone / product_name / price / date")
    value: str = Field(..., description="实体文本")
    start: int = Field(0, description="在原文中的起始位置")
    end: int = Field(0, description="在原文中的结束位置")


class IntentResult(BaseModel):
    """意图识别结果。"""

    intent_code: str
    intent_name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    entities: list[Entity] = Field(default_factory=list)
    handler_type: str = Field(..., description="rag / tool / transfer / llm")
    priority: int = 0

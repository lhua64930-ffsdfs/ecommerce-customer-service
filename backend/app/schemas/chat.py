"""对话相关 Schema(照文档定义)。"""
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SentimentType(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class SenderType(str, Enum):
    USER = "user"
    BOT = "bot"
    AGENT = "agent"


# ---------------- 请求 ----------------
class SendMessageRequest(BaseModel):
    session_id: str = Field(..., description="会话ID")
    content: str = Field(..., min_length=1, max_length=2000, description="消息内容")
    user_id: int | None = Field(None, description="用户ID")
    content_type: str = Field("text", description="内容类型")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")


class CreateSessionRequest(BaseModel):
    user_id: int | None = Field(None, description="用户ID")
    channel: str = Field("web", description="渠道来源")
    initial_message: str | None = Field(None, description="初始消息")


class TransferRequest(BaseModel):
    session_id: str
    reason: str | None = None


class RateRequest(BaseModel):
    session_id: str
    score: int = Field(..., ge=1, le=5)
    comment: str | None = None


# ---------------- 响应 ----------------
class IntentInfo(BaseModel):
    intent_code: str
    intent_name: str
    confidence: float
    entities: list[dict[str, Any]] = Field(default_factory=list)
    handler_type: str
    priority: int = 0


class MessageResponse(BaseModel):
    id: int
    session_id: str
    sender_type: SenderType
    content: str
    content_type: str
    intent: IntentInfo | None = None
    sentiment: SentimentType | None = None
    sentiment_score: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SendMessageResponse(BaseModel):
    response: str = Field(..., description="回复内容")
    intent: IntentInfo = Field(..., description="意图信息")
    sentiment: SentimentType = Field(..., description="情感类型")
    sentiment_score: float = Field(..., description="情感得分")
    quick_replies: list[str] = Field(default_factory=list, description="快捷回复")
    need_transfer: bool = Field(False, description="是否需要转人工")
    message_id: int | None = Field(None, description="机器人消息ID")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list, description="工具调用记录")


class SessionInfo(BaseModel):
    session_id: str
    user_id: int | None
    status: str
    started_at: datetime
    message_count: int = 0
    bot_name: str = "智能客服小e"


class CreateSessionResponse(BaseModel):
    session: SessionInfo
    welcome_message: str
    quick_replies: list[str] = Field(default_factory=list)


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int
    page: int
    page_size: int

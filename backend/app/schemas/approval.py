"""售后审批与订单核验请求模型。"""
from pydantic import BaseModel, Field


class VerifyOrderRequest(BaseModel):
    session_id: str = Field(..., description="会话ID")
    order_no: str = Field(..., min_length=4, max_length=32, description="订单号")
    phone_last4: str = Field(..., min_length=4, max_length=4, description="手机号后四位")


class ApproveRequest(BaseModel):
    session_id: str = Field(..., description="会话ID")
    reviewer: str | None = Field(None, max_length=50, description="人工审核人(高风险必填)")


class RejectRequest(BaseModel):
    session_id: str = Field(..., description="会话ID")
    reason: str | None = Field(None, max_length=500, description="拒绝原因")
    reviewer: str | None = Field(None, max_length=50, description="人工审核人")

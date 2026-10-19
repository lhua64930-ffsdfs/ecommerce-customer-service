"""意图识别接口。"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.schemas.intent import IntentResult
from app.services.intent_service import IntentService

router = APIRouter()


class RecognizeRequest(BaseModel):
    text: str
    user_id: int | None = None


@router.post("/recognize", response_model=IntentResult, summary="识别意图")
async def recognize(payload: RecognizeRequest) -> IntentResult:
    return await IntentService().recognize(payload.text, payload.user_id)


@router.get("/configs", summary="查看意图配置")
async def list_configs() -> list[dict]:
    return [
        {
            "intent_code": code,
            "intent_name": config["name"],
            "handler_type": config["handler"],
            "priority": config["priority"],
            "keywords": config["keywords"],
        }
        for code, config in IntentService.INTENT_CONFIGS.items()
    ]

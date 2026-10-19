"""Agent 信息接口。"""
from fastapi import APIRouter

from app.agents.customer_agent import CustomerServiceAgent
from app.core.config import settings
from app.services.llm_service import LLMService

router = APIRouter()


@router.get("/info", summary="Agent 信息")
async def agent_info() -> dict:
    agent = CustomerServiceAgent(session_id="system")
    llm = LLMService()
    return {
        "name": "小e",
        "version": settings.VERSION,
        "model": settings.LLM_MODEL,
        "llm_provider": settings.LLM_PROVIDER,
        "llm_mock": llm.is_mock,
        "tools": list(agent.tools.keys()),
    }


@router.get("/tools", summary="工具列表")
async def list_tools() -> list[dict]:
    agent = CustomerServiceAgent(session_id="system")
    return [tool.get_schema() for tool in agent.tools.values()]

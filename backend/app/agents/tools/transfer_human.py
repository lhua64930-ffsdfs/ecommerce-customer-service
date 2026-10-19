"""转人工工具:更新会话状态并写入 Redis 排队队列。"""
from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_loader import load_config
from app.models.session import Session
from app.utils.cache import get_redis
from app.utils.logger import logger


class TransferHumanTool:
    """将用户转接给人工客服。"""

    def __init__(self) -> None:
        self.name = "transfer_human"
        self.description = "将用户转接给人工客服,处理复杂问题"
        self.requires_auth = False
        self.queue_name = "human_agent_queue"

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        db: AsyncSession | None = params.get("db")
        session_id: str = params.get("session_id", "")
        user_id: int | None = params.get("user_id")
        message: str = params.get("user_message", "")
        reason: str = params.get("reason") or self._detect_reason(message)

        try:
            queue_info = await self._queue_transfer(session_id, user_id, reason)
            if db is not None:
                await self._update_session_status(db, session_id)

            return {
                "success": True,
                "response": self._generate_message(reason, queue_info),
                "transfer_id": queue_info["transfer_id"],
                "queue_position": queue_info["position"],
                "estimated_wait_time": queue_info["wait_time"],
                "reason": reason,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("转人工失败: {}", exc)
            return {
                "success": False,
                "response": "抱歉,转接人工客服失败,请稍后重试。",
            }

    @staticmethod
    def _detect_reason(message: str) -> str:
        if "投诉" in message:
            return "投诉"

        transfer_config = load_config("agent_config").get("agent", {}).get("transfer", {})
        keywords = transfer_config.get(
            "manual_trigger_keywords", ["人工", "转人工", "真人", "找客服"]
        )
        if any(word in message for word in keywords):
            return "用户主动请求"
        return "其他"

    async def _queue_transfer(
        self, session_id: str, user_id: int | None, reason: str
    ) -> dict[str, Any]:
        transfer_id = f"TRF{int(time.time())}"
        position = 1
        try:
            client = get_redis()
            await client.lpush(
                self.queue_name,
                json.dumps(
                    {
                        "transfer_id": transfer_id,
                        "session_id": session_id,
                        "user_id": user_id,
                        "reason": reason,
                        "created_at": int(time.time()),
                    },
                    ensure_ascii=False,
                ),
            )
            position = max(1, int(await client.llen(self.queue_name)))
        except Exception as exc:  # noqa: BLE001 - 队列不可用时仍允许转接
            logger.warning("转人工队列写入失败,使用默认排队位置: {}", exc)

        return {
            "transfer_id": transfer_id,
            "position": position,
            "wait_time": position * 3,
            "queue_name": self.queue_name,
        }

    @staticmethod
    async def _update_session_status(db: AsyncSession, session_id: str) -> None:
        result = await db.execute(select(Session).where(Session.session_id == session_id))
        session = result.scalar_one_or_none()
        if session is not None:
            session.status = "transferred"
            await db.commit()

    @staticmethod
    def _generate_message(reason: str, queue_info: dict[str, Any]) -> str:
        position = queue_info.get("position", 1)
        wait_time = queue_info.get("wait_time", 3)

        if reason == "投诉":
            return (
                "😔 非常抱歉给您带来不好的体验。\n\n"
                "已为您优先转接投诉处理专员\n"
                f"当前队列位置:第 {position} 位\n"
                f"预计等待时间:{wait_time} 分钟\n\n"
                "我们非常重视您的反馈,会尽快为您处理!"
            )
        if reason == "用户主动请求":
            return (
                "👤 已为您转接人工客服\n\n"
                f"当前队列位置:第 {position} 位\n"
                f"预计等待时间:{wait_time} 分钟\n\n"
                "💡 请保持当前页面,客服将自动接入。"
            )
        return (
            "👤 正在为您转接人工客服...\n\n"
            f"当前队列位置:第 {position} 位\n"
            f"预计等待时间:{wait_time} 分钟\n\n"
            "请稍候,客服代表将马上为您服务。"
        )

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "enum": ["用户主动请求", "投诉", "技术问题", "其他"],
                        "description": "转接原因",
                    }
                },
                "required": ["reason"],
            },
        }

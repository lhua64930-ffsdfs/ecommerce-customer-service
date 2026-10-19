"""Agent 基类:会话管理、工具注册、状态追踪、历史记录。"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.utils.logger import logger


class BaseAgent(ABC):
    """所有 Agent 的基类。"""

    def __init__(self, session_id: str, user_id: int | None = None) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.agent_id = str(uuid.uuid4())
        self.state: dict[str, Any] = {}
        self.tools: dict[str, Any] = {}
        self.conversation_history: list[dict[str, str]] = []
        self.created_at = datetime.now().isoformat()
        logger.info("Agent {} 初始化,会话: {}", self.agent_id, session_id)

    def register_tool(self, name: str, tool: Any) -> None:
        self.tools[name] = tool
        logger.debug("工具注册: {}", name)

    def get_tool(self, name: str) -> Any | None:
        return self.tools.get(name)

    def update_state(self, key: str, value: Any) -> None:
        self.state[key] = value

    def get_state(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def add_to_history(self, role: str, content: str) -> None:
        self.conversation_history.append(
            {"role": role, "content": content, "timestamp": datetime.now().isoformat()}
        )

    def get_history(self, last_n: int | None = None) -> list[dict[str, str]]:
        if last_n is None:
            return self.conversation_history
        return self.conversation_history[-last_n:]

    def clear_history(self) -> None:
        self.conversation_history = []
        logger.info("Agent {} 清空对话历史", self.agent_id)

    @abstractmethod
    async def process(self, input_text: str) -> dict[str, Any]:
        """处理输入,子类必须实现。"""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "state": self.state,
            "tools": list(self.tools.keys()),
            "history_count": len(self.conversation_history),
            "created_at": self.created_at,
        }

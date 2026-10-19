"""知识库检索工具(真实 Milvus 检索,失败自动降级)。"""
from __future__ import annotations

from typing import Any

from app.services.rag_service import RAGService
from app.utils.logger import logger


class SearchKnowledgeTool:
    """从知识库检索与用户问题最相关的内容。"""

    def __init__(self) -> None:
        self.name = "search_knowledge"
        self.description = "从知识库中检索相关信息,用于回答商品、政策、常见问题等"
        self.requires_auth = False

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query") or params.get("user_message", "")
        top_k = int(params.get("top_k", 3))
        category = params.get("category")
        filters = {"category": category} if category else None

        try:
            results = await RAGService().search(query, top_k=top_k, filters=filters)
        except Exception as exc:  # noqa: BLE001
            logger.error("知识库检索失败: {}", exc)
            return {
                "success": False,
                "response": "检索服务暂时不可用,请稍后重试",
                "results": [],
                "source": "knowledge_base",
            }

        if not results:
            return {
                "success": False,
                "response": "抱歉,知识库中没有找到相关信息,建议您咨询人工客服",
                "results": [],
                "source": "knowledge_base",
            }

        best = results[0]
        score = float(best.get("score", 0.0))
        if score >= 0.8:
            prefix = "根据您的疑问,我找到以下信息:"
        elif score >= 0.5:
            prefix = "您可能想了解的是:"
        else:
            prefix = "以下信息供您参考:"

        parts = [f"{prefix}\n\n📖 {best.get('answer', '')}\n"]
        if len(results) > 1:
            parts.append("\n💡 您可能还想了解:")
            for item in results[1:3]:
                parts.append(f"\n  • {item.get('question', '')}")
        parts.append(f"\n\n📂 来源:{best.get('category', '')}")

        return {
            "success": True,
            "response": "".join(parts),
            "results": results,
            "source": "knowledge_base",
            "score": score,
        }

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "用户的查询问题"},
                    "category": {"type": "string", "description": "限定知识库分类(可选)"},
                    "top_k": {"type": "integer", "description": "返回结果数量,默认3", "default": 3},
                },
                "required": ["query"],
            },
        }

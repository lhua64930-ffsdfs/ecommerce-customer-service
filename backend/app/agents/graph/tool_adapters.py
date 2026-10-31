"""LangChain 工具适配层:复用现有 6 个工具,不改工具内部逻辑。

现有工具接收一个 ``params`` 字典(含 db / user_id / session_id),
模型调用时只提供业务参数。适配层负责:

1. 把工具 ``get_schema()`` 的 JSON Schema 转成 StructuredTool 的 pydantic 参数模型;
2. 把请求上下文合并进工具参数;
3. 把工具结果序列化为模型可读的 Observation,并记录对外工具调用。
"""
from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import Field, create_model

from app.agents.graph.context import ToolContext

_PYTHON_TYPES: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _args_schema(tool_name: str, schema: dict[str, Any]) -> type:
    """把工具 JSON Schema 转成 pydantic 参数模型。"""
    parameters = schema.get("parameters") or {}
    properties: dict[str, dict[str, Any]] = parameters.get("properties") or {}
    required = set(parameters.get("required") or [])

    fields: dict[str, tuple[Any, Any]] = {}
    for field_name, spec in properties.items():
        enum_values = spec.get("enum")
        if enum_values:
            annotation: Any = Literal[tuple(enum_values)]
        else:
            annotation = _PYTHON_TYPES.get(spec.get("type", "string"), str)

        description = spec.get("description", "")
        if field_name in required:
            fields[field_name] = (annotation, Field(..., description=description))
        else:
            fields[field_name] = (
                annotation | None,
                Field(default=spec.get("default"), description=description),
            )

    model_name = "".join(part.capitalize() for part in tool_name.split("_")) + "Args"
    return create_model(model_name, **fields)


def build_lc_tools(
    tools: dict[str, Any], context: ToolContext
) -> list[StructuredTool]:
    """把现有工具包装成 LangChain StructuredTool 列表。"""
    lc_tools: list[StructuredTool] = []

    for name, tool in tools.items():
        schema = tool.get_schema()

        async def _run(
            _tool: Any = tool,
            _name: str = name,
            **kwargs: Any,
        ) -> str:
            try:
                result = await _tool.execute(context.tool_params(**kwargs))
            except Exception as exc:  # noqa: BLE001 - 工具异常交给模型判断下一步
                result = {
                    "success": False,
                    "response": f"工具 {_name} 执行失败: {exc}",
                }
            context.record_tool_call(_name, result)
            return json.dumps(result, ensure_ascii=False, default=str)

        lc_tools.append(
            StructuredTool.from_function(
                coroutine=_run,
                name=name,
                description=tool.description,
                args_schema=_args_schema(name, schema),
            )
        )

    return lc_tools

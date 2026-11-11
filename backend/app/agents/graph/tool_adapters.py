"""LangChain 工具适配层 + 统一执行引擎。

所有工具调用都走同一管道:
1. 查工具/权限(写操作在图内一律拒绝,只能由审批服务执行);
2. JSON Schema 校验(失败回灌模型,让它修正参数或追问用户);
3. 执行(超时;只读工具允许一次重试);
4. 结果格式化 + 记录到 ToolContext(后续落 agent_steps)。
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from langchain_core.tools import StructuredTool
from pydantic import Field, create_model

from app.agents.graph.context import ToolContext
from app.agents.tools.registry import ToolSpec, spec_from_tool

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


def validate_args(spec: ToolSpec, args: dict[str, Any]) -> str | None:
    """按原始 JSON Schema 校验;返回人类可读错误(None 表示通过)。"""
    try:
        error = best_match(Draft202012Validator(spec.json_schema).iter_errors(args))
    except Exception as exc:  # noqa: BLE001 - 外部/异常 schema 不应打崩工具
        return f"参数定义异常({type(exc).__name__})"
    if error is None:
        return None
    where = f"(字段 {error.json_path})" if error.json_path != "$" else ""
    return f"{error.message}{where}"


def tool_error_payload(
    tool_name: str, exc: Exception | str, error_code: str = "TOOL_ERROR"
) -> dict[str, Any]:
    """工具失败时的统一 Observation 结构。"""
    detail = exc if isinstance(exc, str) else str(exc)
    return {
        "success": False,
        "response": f"工具 {tool_name} 执行失败: {detail}",
        "error_code": error_code,
    }


async def _execute_with_policy(
    spec: ToolSpec, tool: Any, context: ToolContext, kwargs: dict[str, Any]
) -> dict[str, Any]:
    if spec.permission == "write" and not context.write_confirmed:
        return {
            "success": False,
            "response": (
                "该写操作需要用户确认。请先通过确认卡片确认;"
                "模型不能直接执行写操作。"
            ),
            "error_code": "WRITE_FORBIDDEN",
        }

    # LangChain 会把未填写的可选参数以 None 传入;从校验/执行参数中移除,
    # 让「可选字段缺省」与「显式 null」保持一致的语义。
    cleaned = {key: value for key, value in kwargs.items() if value is not None}
    validation_error = validate_args(spec, cleaned)
    if validation_error is not None:
        return {
            "success": False,
            "response": (
                f"参数校验未通过:{validation_error}。"
                "请修正参数重新调用;缺少的信息请先向用户追问,不要编造。"
            ),
            "error_code": "VALIDATION_ERROR",
        }

    attempts = 1 + (
        max(0, spec.max_retries) if spec.permission == "read" else 0
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return await asyncio.wait_for(
                tool.execute(context.tool_params(**cleaned)),
                timeout=spec.timeout,
            )
        except asyncio.TimeoutError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                continue
            return tool_error_payload(
                spec.name, f"执行超时(>{spec.timeout:.0f}s)", "TIMEOUT"
            )
        except (ConnectionError, OSError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                continue
            return tool_error_payload(spec.name, exc, "TRANSIENT_ERROR")
        except Exception as exc:  # noqa: BLE001 - 业务失败不重试,回灌模型
            return tool_error_payload(spec.name, exc)

    return tool_error_payload(spec.name, last_error or "unknown", "TOOL_ERROR")


def build_lc_tools(
    tools: dict[str, Any], context: ToolContext
) -> list[StructuredTool]:
    """把现有工具包装成 LangChain StructuredTool 列表。"""
    lc_tools: list[StructuredTool] = []

    for name, tool in tools.items():
        spec = spec_from_tool(tool)

        async def _run(
            _tool: Any = tool,
            _spec: ToolSpec = spec,
            **kwargs: Any,
        ) -> str:
            started = time.perf_counter()
            result = await _execute_with_policy(
                _spec, _tool, context, dict(kwargs)
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            context.record_tool_call(
                _spec.name, result, args=dict(kwargs), latency_ms=latency_ms
            )
            return json.dumps(result, ensure_ascii=False, default=str)

        lc_tools.append(
            StructuredTool.from_function(
                coroutine=_run,
                name=spec.name,
                description=spec.description,
                args_schema=_args_schema(name, tool.get_schema()),
            )
        )

    return lc_tools

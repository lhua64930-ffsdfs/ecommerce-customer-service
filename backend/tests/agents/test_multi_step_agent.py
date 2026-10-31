"""多步 Agent 图:单工具路径、fallback 触发条件与步数上限。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.graph.multi_step_agent import (
    MultiStepAgent,
    MultiStepEmptyResultError,
    MultiStepExecutionError,
    MultiStepLimitError,
)
from tests.support.fake_chat_model import FakeOrderTool, ScriptedChatModel


async def test_order_query_runs_tool_and_returns_multi_step_result() -> None:
    tool = FakeOrderTool()
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_order",
                        "args": {"order_no": "ORDER20260401001"},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="您的订单 ORDER20260401001 已支付,待发货。"),
        ]
    )
    agent = MultiStepAgent(chat_model=model, tools={"query_order": tool})

    result = await agent.run(
        user_message="查订单 ORDER20260401001",
        history=[],
        db=None,
        user_id=1,
        session_id="session-1",
    )

    assert result.response == "您的订单 ORDER20260401001 已支付,待发货。"
    assert result.tool_calls == [{"tool": "query_order", "success": True}]
    assert tool.calls[0]["order_no"] == "ORDER20260401001"
    assert tool.calls[0]["user_id"] == 1
    assert tool.calls[0]["session_id"] == "session-1"

    # 图执行了 模型 → 工具 → 模型 两轮,并把工具结果回传给模型
    assert len(model.calls) == 2
    observation = model.calls[1][-1]
    assert isinstance(observation, ToolMessage)
    assert "已支付" in str(observation.content)


async def test_graph_failure_raises_typed_error() -> None:
    model = ScriptedChatModel(fail_with="graph exploded")
    agent = MultiStepAgent(chat_model=model, tools={"query_order": FakeOrderTool()})

    with pytest.raises(MultiStepExecutionError) as exc_info:
        await agent.run(
            user_message="查订单 ORDER20260401001",
            history=[],
            db=None,
            user_id=1,
            session_id="session-1",
        )

    assert "graph exploded" in str(exc_info.value)


async def test_empty_final_answer_is_rejected() -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_order",
                        "args": {"order_no": "ORDER20260401001"},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="   "),
        ]
    )
    agent = MultiStepAgent(chat_model=model, tools={"query_order": FakeOrderTool()})

    with pytest.raises(MultiStepEmptyResultError):
        await agent.run(
            user_message="查订单 ORDER20260401001",
            history=[],
            db=None,
            user_id=1,
            session_id="session-1",
        )


async def test_answer_without_tool_call_is_rejected() -> None:
    model = ScriptedChatModel(responses=[AIMessage(content="订单已经发出了")])
    agent = MultiStepAgent(chat_model=model, tools={"query_order": FakeOrderTool()})

    with pytest.raises(MultiStepEmptyResultError):
        await agent.run(
            user_message="查订单 ORDER20260401001",
            history=[],
            db=None,
            user_id=1,
            session_id="session-1",
        )


async def test_step_limit_stops_runaway_tool_loop() -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_order",
                        "args": {"order_no": "ORDER20260401001"},
                        "id": "call_1",
                    }
                ],
            )
        ]
    )
    agent = MultiStepAgent(
        chat_model=model, tools={"query_order": FakeOrderTool()}, max_steps=3
    )

    with pytest.raises(MultiStepLimitError):
        await agent.run(
            user_message="查订单 ORDER20260401001",
            history=[],
            db=None,
            user_id=1,
            session_id="session-1",
        )

    assert len(model.calls) == 3


async def test_history_is_passed_to_model() -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_order",
                        "args": {"order_no": "ORDER20260401001"},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="已为您查询"),
        ]
    )
    agent = MultiStepAgent(chat_model=model, tools={"query_order": FakeOrderTool()})

    await agent.run(
        user_message="查订单 ORDER20260401001",
        history=[{"role": "user", "content": "之前的问题"}, {"role": "assistant", "content": "之前的回答"}],
        db=None,
        user_id=1,
        session_id="session-1",
    )

    first_call = model.calls[0]
    assert any(
        isinstance(message, HumanMessage) and message.content == "之前的问题"
        for message in first_call
    )

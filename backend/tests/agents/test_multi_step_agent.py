"""多步 Agent 图:单工具路径、fallback 触发条件与步数上限。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.graph.multi_step_agent import (
    MultiStepAgent,
    MultiStepEmptyResultError,
    MultiStepExecutionError,
    MultiStepLimitError,
    MultiStepResumeError,
)
from tests.support.fake_chat_model import (
    FakeKnowledgeTool,
    FakeOrderListTool,
    FakeOrderTool,
    FakeProposeTool,
    FakeTicketTool,
    ScriptedChatModel,
)


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


async def test_compound_order_then_cancel_submits_approval() -> None:
    """复合任务:先查订单状态,再提交取消申请(不直接写库)。"""
    order_tool = FakeOrderTool()
    propose_tool = FakeProposeTool()
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
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "propose_after_sales_action",
                        "args": {"action": "cancel", "order_no": "ORDER20260401001"},
                        "id": "call_2",
                    }
                ],
            ),
            AIMessage(content="已为您生成取消申请,请在确认卡片中确认。"),
        ]
    )
    agent = MultiStepAgent(
        chat_model=model,
        tools={
            "query_order": order_tool,
            "propose_after_sales_action": propose_tool,
        },
    )

    result = await agent.run(
        user_message="查订单 ORDER20260401001 然后帮我取消",
        history=[],
        db=None,
        user_id=1,
        session_id="session-1",
    )

    assert result.response == "已为您生成取消申请,请在确认卡片中确认。"
    assert result.tool_calls == [
        {"tool": "query_order", "success": True},
        {"tool": "propose_after_sales_action", "success": True},
    ]
    assert propose_tool.calls[0]["action"] == "cancel"
    assert propose_tool.calls[0]["order_no"] == "ORDER20260401001"
    assert result.pending_approval is not None
    assert result.pending_approval["action"] == "cancel"
    assert len(model.calls) == 3


async def test_search_knowledge_tool_produces_citations() -> None:
    """图内知识检索的结果应转换为结构化引用。"""
    knowledge_tool = FakeKnowledgeTool()
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_knowledge",
                        "args": {"query": "商品可以退换吗"},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="7 天内可以无理由退换货。"),
        ]
    )
    agent = MultiStepAgent(
        chat_model=model, tools={"search_knowledge": knowledge_tool}
    )

    result = await agent.run(
        user_message="商品可以退换吗",
        history=[],
        db=None,
        user_id=1,
        session_id="session-1",
    )

    assert result.tool_calls == [{"tool": "search_knowledge", "success": True}]
    assert result.citations == [
        {
            "id": 1,
            "category": "退换货政策",
            "question": "商品可以退换吗",
            "score": 0.93,
        }
    ]


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


async def test_conversation_thread_reuses_history_and_resets_steps() -> None:
    """会话级 checkpoint:第二轮带上一轮历史,但 steps/工具记录只算本轮。"""
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
            AIMessage(content="第一轮查询完成。"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_order",
                        "args": {"order_no": "ORDER20260315001"},
                        "id": "call_2",
                    }
                ],
            ),
            AIMessage(content="第二轮查询完成。"),
        ]
    )
    agent = MultiStepAgent(
        chat_model=model,
        tools={"query_order": FakeOrderTool()},
        checkpointer=InMemorySaver(),
    )
    thread_id = "session-conversation-1"

    first = await agent.run(
        user_message="查订单 ORDER20260401001",
        history=[],
        db=None,
        user_id=1,
        session_id=thread_id,
        thread_id=thread_id,
    )
    second = await agent.run(
        user_message="再查订单 ORDER20260315001",
        history=[],
        db=None,
        user_id=1,
        session_id=thread_id,
        thread_id=thread_id,
    )

    assert first.response == "第一轮查询完成。"
    assert second.response == "第二轮查询完成。"
    # 第二轮第一次模型调用应能看到第一轮的消息
    second_turn_messages = model.calls[2]
    assert any(
        isinstance(message, HumanMessage)
        and message.content == "查订单 ORDER20260401001"
        for message in second_turn_messages
    )
    assert any(
        isinstance(message, AIMessage) and message.content == "第一轮查询完成。"
        for message in second_turn_messages
    )
    # 第二轮的工具记录只包含本轮调用,不会把上一轮累加进来
    assert second.tool_calls == [{"tool": "query_order", "success": True}]
    # 本轮 steps:模型 → 工具 → 模型(3 条);没有累加第一轮的步骤
    assert len(second.steps) == 3


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


async def test_order_selection_interrupt_then_resume() -> None:
    """无订单号提出售后申请时先 interrupt,resume 后只执行一次申请。"""
    order_tool = FakeOrderListTool()
    propose_tool = FakeProposeTool()
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "propose_after_sales_action",
                        "args": {"action": "cancel"},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="取消申请已生成,请在卡片中确认。"),
        ]
    )
    agent = MultiStepAgent(
        chat_model=model,
        tools={
            "query_order": order_tool,
            "propose_after_sales_action": propose_tool,
        },
        checkpointer=InMemorySaver(),
    )
    thread_id = "session-1:42"

    first = await agent.run(
        user_message="帮我取消订单",
        history=[],
        db=None,
        user_id=1,
        session_id="session-1",
        thread_id=thread_id,
    )

    assert first.interrupted is True
    assert first.interrupt is not None
    assert first.interrupt["type"] == "select_order"
    assert [item["order_no"] for item in first.interrupt["orders"]] == [
        "ORDER-A",
        "ORDER-B",
    ]
    assert propose_tool.calls == []

    second = await agent.resume(
        thread_id,
        {"type": "select_order", "order_no": "ORDER-B"},
        db=None,
    )

    assert second.interrupted is False
    assert second.response == "取消申请已生成,请在卡片中确认。"
    assert propose_tool.calls[0]["order_no"] == "ORDER-B"
    assert second.pending_approval is not None
    assert any(call["tool"] == "propose_after_sales_action" for call in second.tool_calls)

    with pytest.raises(MultiStepResumeError):
        await agent.resume(
            thread_id,
            {"type": "select_order", "order_no": "ORDER-B"},
            db=None,
        )


async def test_ticket_confirmation_interrupt_then_resume() -> None:
    """create_ticket 先确认,resume 确认后只执行一次。"""
    ticket_tool = FakeTicketTool()
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "create_ticket",
                        "args": {
                            "type": "consult",
                            "content": "修改收货地址",
                        },
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="工单已创建,编号 TKT-TEST。"),
        ]
    )
    agent = MultiStepAgent(
        chat_model=model,
        tools={"create_ticket": ticket_tool},
        checkpointer=InMemorySaver(),
    )
    thread_id = "session-1:43"

    first = await agent.run(
        user_message="帮我建个工单修改地址",
        history=[],
        db=None,
        user_id=1,
        session_id="session-1",
        thread_id=thread_id,
    )

    assert first.interrupted is True
    assert first.interrupt is not None
    assert first.interrupt["type"] == "confirm_ticket"
    assert ticket_tool.calls == []

    second = await agent.resume(
        thread_id,
        {"type": "confirm_ticket", "confirmed": True},
        db=None,
    )

    assert second.interrupted is False
    assert second.response == "工单已创建,编号 TKT-TEST。"
    assert len(ticket_tool.calls) == 1


async def test_ticket_confirmation_can_be_cancelled() -> None:
    ticket_tool = FakeTicketTool()
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "create_ticket",
                        "args": {
                            "type": "consult",
                            "content": "修改收货地址",
                        },
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="已取消建单。"),
        ]
    )
    agent = MultiStepAgent(
        chat_model=model,
        tools={"create_ticket": ticket_tool},
        checkpointer=InMemorySaver(),
    )
    thread_id = "session-1:44"

    first = await agent.run(
        user_message="帮我建个工单修改地址",
        history=[],
        db=None,
        user_id=1,
        session_id="session-1",
        thread_id=thread_id,
    )
    assert first.interrupted is True

    second = await agent.resume(
        thread_id,
        {"type": "confirm_ticket", "confirmed": False},
        db=None,
    )

    assert second.interrupted is False
    assert ticket_tool.calls == []
    assert second.response == "已取消建单。"

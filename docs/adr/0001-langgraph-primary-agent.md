# LangGraph 作为主 Agent,单步路由作为 fallback

**Status**: accepted

## Context

项目目标是面向 AI/LLM 岗位的作品集,需要在 2–3 天内展示多步工具调用能力。现有 `CustomerServiceAgent` 是单步意图路由:一条消息只调用一个工具或 RAG。它稳定、易调试,但无法完成“查订单 → 判断状态 → 取消/退款”这类复合任务。

## Decision

使用 LangGraph 实现主 Agent:把现有 6 个工具包装成图节点,由模型决定调用顺序,最多 5 步。保留现有单步 Agent 作为 fallback:当图执行失败、超过步数或 LLM 不可用时,同一请求回退到单步路由。工具与 RAG 服务复用,不重写。

## Considered Options

- **LangChain AgentExecutor**:可用,但循环控制与状态可视化弱于 LangGraph,面试叙事也不如 LangGraph 清晰。
- **LlamaIndex**:强在 RAG 与索引,不是多步 Agent 的主场;本项目 RAG 已有自研实现。
- **纯 function calling 自研**:可控且无新依赖,但用户明确要求引入 LangChain 系框架,且少一个生态关键词。
- **完全替换单步 Agent**:代码更干净,但 2–3 天内演示风险高;保留 fallback 不影响主路径展示。

## Consequences

- 新增 `langgraph`、`langchain-core`、`langchain-openai` 依赖;镜像与冷启动略增。
- 现有工具类需要包一层 LangChain `StructuredTool` 适配,但不改工具内部逻辑。
- 响应中需要暴露工具调用链,便于演示与调试;失败路径必须测试 fallback。
- 两套 Agent 并存会增加维护成本,计划在本阶段结束后评估是否删除旧路径。

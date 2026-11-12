# LangGraph 作为主 Agent,失败强停兜底

**Status**: accepted(2026-11-12 更新:移除单步 Agent fallback,对齐 MewHelp 的强停兜底)

## Context

项目目标是面向 AI/LLM 岗位的作品集,需要展示多步工具调用能力。现有 `CustomerServiceAgent` 是单步意图路由:一条消息只调用一个工具或 RAG。它稳定、易调试,但无法完成“查订单 → 判断状态 → 取消/退款”这类复合任务。

## Decision

使用 LangGraph 实现主 Agent:把现有 6 个工具包装成图节点,由模型决定调用顺序,最多 **6 步**。多步图失败、超步、空回复或没有工具结果时,**强停并返回固定兜底话术**,不再回退到单步 Agent。无 ChatModel 时保留单步离线模式,用于本地演示与测试,但它不是失败 fallback。

工具与 RAG 服务复用,不重写;审批单 + 策略引擎 + 订单核验仍是售后执行真源。

## Considered Options

- **LangChain AgentExecutor**:可用,但循环控制与状态可视化弱于 LangGraph,面试叙事也不如 LangGraph 清晰。
- **LlamaIndex**:强在 RAG 与索引,不是多步 Agent 的主场;本项目 RAG 已有自研实现。
- **纯 function calling 自研**:可控且无新依赖,但用户明确要求引入 LangChain 系框架,且少一个生态关键词。
- **完全替换单步 Agent**:代码更干净,但无模型时无法演示;保留单步离线模式只用于 mock/本地演示,不参与失败语义。
- **失败回退单步 Agent**:早期方案;会引入两套路径的语义分叉,且副作用场景难以保证不重复执行,因此改为强停兜底。

## Consequences

- 新增 `langgraph`、`langchain-core`、`langchain-openai` 依赖;镜像与冷启动略增。
- 现有工具类需要包一层 LangChain `StructuredTool` 适配,但不改工具内部逻辑。
- 响应中暴露 `agent_mode`(`multi_step` / `single_step`)与工具调用链,便于演示与调试。
- 不再保留“多步失败 → 单步 Agent”路径;失败时用户得到明确兜底话术,避免重复执行副作用。
- 测试需要覆盖强停话术、步数上限与无模型离线模式。

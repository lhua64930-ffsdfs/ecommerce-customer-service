# 售后智答

售后智答是一个电商售后智能客服系统。本上下文定义项目中反复出现的领域术语,供人与 Agent 在设计、实现和评审时使用同一套语言。

## 会话与售后

**会话 (Session)**:
一次用户与客服之间的连续对话,包含多条消息和最终状态。
_Avoid_: 聊天、对话记录、ticket

**转人工 (Human handoff)**:
将当前会话交给人工客服继续处理。
_Avoid_: 升级、转接客服、人工

**工单 (Ticket)**:
脱离会话独立跟踪的售后事项记录,用于后续人工处理。
_Avoid_: 任务、issue、工单号(作为概念)

## Agent

**单步 Agent (Single-step Agent)**:
对一条用户消息只做一次意图判断,并调用一个处理器或工具就结束的 Agent。
_Avoid_: 路由、意图路由、ReAct

**多步 Agent (Multi-step Agent)**:
在一次用户请求内可以多次调用工具、观察结果并决定下一步,直到完成任务或达到步数上限的 Agent。
_Avoid_: 工作流、链、ReAct

**Agent Fallback**:
当多步 Agent 失败、超过步数或没有可用结果时,改用单步 Agent 处理同一请求。
_Avoid_: 降级(与检索降级混淆)

**Agent 模式 (Agent mode)**:
本次请求实际使用的 Agent 路径,对应响应字段 `agent_mode`:
多步 Agent(`multi_step`)、单步 Agent(`single_step`)、Agent Fallback(`single_step_fallback`)。
_Avoid_: 路由模式、处理类型、降级模式

## 检索与评估

**知识条目 (Knowledge item)**:
知识库中的一条“问题—答案”记录,带分类和关键词。
_Avoid_: 文档、FAQ、语料

**RAG 引用 (Citation)**:
附着在生成回答上的来源标识,指向生成时使用的知识条目。
_Avoid_: 来源、参考、链接

**评测集 (Evaluation set)**:
一组固定的“问题 → 期望知识条目”样本,用于衡量检索质量。
_Avoid_: 测试集(单元测试)、数据集

**Recall@3**:
评测集中,期望知识条目出现在检索结果前 3 名的题目比例。
_Avoid_: 命中率、准确率

**检索降级 (Retrieval fallback)**:
向量检索不可用时,改用关键词检索知识条目的策略。
_Avoid_: 降级、Agent Fallback

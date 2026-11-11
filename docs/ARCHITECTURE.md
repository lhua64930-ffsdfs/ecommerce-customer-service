# 架构设计

> 可复现命令见 [演示脚本](DEMO.md)。

## 1. 总览

```text
React SPA (Ant Design)
        │  /api (axios)
        ▼
FastAPI ── Chat API
        ├─ 消息预处理(清洗 / 敏感词)
        ├─ 情感分析 ──────────────► SentimentService
        ├─ 意图识别 ──────────────► IntentService(规则 + LLM)
        ├─ 路由
        │    ├─ 订单查询 / 取消 / 退款 → LangGraph 多步 Agent(只读工具 + 申请工具,≤5 步)
        │    │              ├─ 复合任务:query_order → 判断状态 → propose_after_sales_action
        │    │              └─ 失败 / 超步数 / 空结果 → 单步 fallback
        │    ├─ transfer → TransferHumanTool → Redis 队列 + sessions.status
        │    ├─ tool     → QueryOrder / QueryProduct / ProposeAction / CreateTicket → MySQL
        │    ├─ rag      → RAGService → EmbeddingService → Milvus
        │    │              └─ 返回 answer + citations;失败降级关键词检索
        │    └─ llm      → LLMService → DeepSeek
        ├─ 审批服务 → 策略引擎 + 订单核验 + 审批执行 → MySQL
        └─ 落库 messages / sessions / service_tasks / agent_runs / agent_steps
           / approvals / policy_decisions / audit_logs → MySQL
```

## 2. 分层

| 层 | 目录 | 职责 |
| --- | --- | --- |
| 接口层 | `app/api/v1/` | 参数校验、鉴权边界、响应组装、审批接口 |
| Agent 层 | `app/agents/` | 决策路由、工具编排、提示词 |
| 运行时 | `app/runtime/` | 售后事项、Agent 运行步骤、审批状态机与执行 |
| 策略层 | `app/policies/` | policy-as-code 规则匹配与决策审计 |
| 服务层 | `app/services/` | LLM、情感、意图、向量、RAG |
| 数据层 | `app/models/`、`app/core/database.py` | ORM 与连接池(16 张表) |
| 基础设施 | MySQL / Redis / Milvus | 业务数据、缓存队列、向量索引 |

## 3. 一次对话的完整流程

1. `POST /api/v1/chat/send` 校验会话,Redis Lua 原子滑动窗口限流(默认 60 次/分钟)。
2. 读取最近 10 条消息作为上下文。
3. 先提交用户消息,再执行 Agent;即使工具异常回滚,用户输入也不会丢失。
4. `CustomerServiceAgent.chat()`:
   - 清洗文本、替换敏感词;
   - 情感分析 → `positive / neutral / negative`;
   - 意图识别 → 关键词与 LLM 融合,抽取实体;
   - `order_query` / `cancel_order` / `refund_request` 优先交给 LangGraph 多步 Agent:
     模型节点决定调用哪个工具,工具节点执行只读工具或生成售后申请并回传 Observation,
     条件边决定继续或结束,最多 5 步;复合任务由模型自主完成
     「query_order → 判断状态 → propose_after_sales_action」;
   - 图不可用、执行失败、超步数、空回复或没有工具结果时,回退到既有单步 Agent(Agent Fallback);
   - 其余意图仍按 `handler_type` 路由:转人工 / 工具 / RAG / 纯 LLM;
   - RAG 路径同时返回 `citations`,知识检索工具在多步图内也会回填引用;
   - 负向情绪自动添加安抚前缀。
5. 保存机器人回复(意图、置信度、情感、工具调用记录、citations、待审批申请),
   并记录 `agent_run` 与 `agent_steps`。
6. 更新会话状态、消息数、最后消息时间。
7. 订单工具输出与订单 API 响应统一做 PII 脱敏(手机号 / 姓名 / 详细地址)。
8. 用户核验订单后确认/拒绝审批;高风险申请需要客服工号,审批服务重新走策略与状态校验
   后幂等执行(取消写库、退款/退货建工单)。

## 4. Agent 与工具

| 工具 | 数据来源 | 说明 |
| --- | --- | --- |
| `search_knowledge` | Milvus + 本地 JSON 降级 | 语义检索知识库 |
| `query_order` | MySQL | 按订单号/用户查询,**校验订单归属**,输出 PII 脱敏 |
| `query_product` | MySQL | 关键词匹配商品、库存、价格 |
| `propose_after_sales_action` | MySQL | 生成取消/退款/退货**申请单**,不直接写订单 |
| `transfer_human` | Redis + MySQL | 排队、更新会话为 transferred |
| `create_ticket` | MySQL | 创建工单 |

意图 → 工具映射在 `CustomerServiceAgent._handle_with_tools()`:
`order_query → query_order`、`cancel_order → propose(action=cancel)`、
`refund_request → propose(action=refund)`、`order_modify → create_ticket`、
`complaint/human_agent → transfer_human`。

多步路径通过 `app/agents/graph/tool_adapters.py` 把工具包装成
LangChain `StructuredTool`;多步图只暴露只读工具 + 申请工具 + 转人工,
**不包含任何直接写库的工具**。ChatModel 与图均通过依赖注入提供,
测试使用脚本化 Fake ChatModel,不会访问真实 DeepSeek。

多步图覆盖 `order_query` / `cancel_order` / `refund_request` 三类订单售后意图。
复合任务由模型自主编排:先查询真实状态,再提交取消/退货申请;
申请不会立即执行,而是返回 `pending_approval` 给前端确认。

一次复合任务的工具链会在响应的 `tool_calls` 中完整呈现:

```json
[
  { "tool": "query_order", "success": true },
  { "tool": "propose_after_sales_action", "success": true }
]
```

### 4.1 任务运行时与审批

```text
propose_after_sales_action
  → 校验订单归属
  → PolicyEngine.evaluate(金额 / 状态 / 风险)
  → 创建 service_task + approval + policy_decision + audit_log
  → 返回 pending_approval(待确认 / 待人工审核 / 自动执行)

POST /chat/verify-order
  → 订单号 + 手机后四位 → verifications

POST /chat/approvals/{id}/approve
  → 校验审批归属与状态
  → 高风险必须带 reviewer 客服工号
  → 必须已核验订单
  → 重新执行策略与订单状态校验
  → 幂等执行(取消写库 / 退款退货建工单)
  → approval=executed + task=completed + audit_log
```

- 四档决策:`allow_auto`(低风险自动执行)、`needs_confirm`(用户确认)、
  `needs_human`(人工审核)、`deny`(拒绝并说明原因)。
- 审批单状态机:`pending → executed / rejected`;重复 approve 返回 `already_executed`。
- 执行前重新查订单并重跑策略,避免「申请后订单状态变化仍盲目执行」。
- 每次请求记录 `agent_runs` / `agent_steps`,为后续轨迹评测与 Trace 面板备料。

## 5. RAG 链路

```text
知识入库:MySQL knowledge 表 ──► BGE 向量化 ──► Milvus(collection: knowledge_base)
在线检索:用户问题 ──► BGE 向量化 ──► Milvus COSINE top-k
        ──► 拼接上下文 + citations ──► LLM 生成
```

- 向量主键直接使用 `knowledge.id`,与业务数据天然对应,重复写入即更新(upsert)。
- `retrieve_with_citations()` 同时返回 LLM 上下文与结构化引用:
  `id / category / question / score`;引用随聊天响应返回,并写入消息 metadata,
  会话回放时仍可展示。
- Milvus 或 Embedding 不可用时自动降级为本地关键词检索(`knowledge_base/faqs.json`),
  并设置 30 秒冷却,避免每个请求重复重试已宕机的向量库。
- 离线评测脚本 `scripts/evaluate_rag.py` 读取 `knowledge_base/eval_set.json`,
  计算 Recall@1/3/5 与 MRR@5,并标注本次运行实际使用的检索模式。
- 更换向量库时,只需实现 `RAGService` 的 `add_documents / search / delete_documents`。

## 6. 关键设计决策

| 决策 | 原因 |
| --- | --- |
| Service 单例 + 懒加载 | BGE 模型加载需数秒/数百 MB,禁止按请求重复加载 |
| Agent 无状态 + DB 历史 | 多 worker/重启后不丢上下文 |
| 配置分两层(.env + YAML) | 密钥与连接串不進 Git;业务参数可共享 |
| 统一数据库事务 | 知识条目与向量主键同源,避免双写不一致 |
| 工具接收 `AsyncSession` | 同一次请求复用一个连接,避免连接爆炸 |
| 失败降级 | LLM/RAG/Redis 任一故障不阻断主流程 |
| 多步 Agent 主路径 + 单步 fallback | 展示 LangGraph 多步工具调用,同时保留稳定可演示的兜底路径 |
| 写操作幂等 | 审批状态机 + 执行前状态重验,重复确认不会重复执行 |
| 模型提申请、系统执行 | 模型没有退款/取消写权限,避免过度自治与误操作 |
| Policy-as-code | 金额/状态/风险规则可配置、可审计、可版本化 |
| 订单核验 | 订单号 + 手机后四位,防止仅凭订单号查看/操作他人订单 |
| 运行步骤落库 | 每次 Agent 执行的模型/工具步骤可回放,为评测与排障备料 |
| 结构化引用 | RAG 回答可追溯到知识条目,引用随消息持久化 |
| Redis 原子滑动窗口 | Lua 保证清理、计数、写入原子性,计数随窗口自然过期 |
| PII 脱敏 | 工具输出与 API 响应统一脱敏,原始数据留库 |

## 7. 可扩展性

- **向量层可替换**:`RAGService` 只暴露 `add_documents / search / delete_documents`,
  更换 Milvus 或 Embedding 模型不影响 Agent 层。
- **工具可扩展**:新增工具只需实现 `execute()` 与 `get_schema()`,
  单步 Agent 与多步图的适配层共用同一套实现。
- **意图可扩展**:意图配置集中在 `IntentService.INTENT_CONFIGS`,
  新增意图后同步种子数据即可参与关键词与 LLM 融合。
- **评测可扩展**:`eval_set.json` 与 `rag_evaluator.py` 解耦,
  增加样本或替换知识库后可直接重跑同一套指标。

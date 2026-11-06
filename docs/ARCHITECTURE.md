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
        │    ├─ 订单查询 / 取消 / 退款 → LangGraph 多步 Agent(model ↔ tools,≤5 步)
        │    │              ├─ 复合任务:query_order → 判断状态 → refund
        │    │              └─ 失败 / 超步数 / 空结果 → 单步 fallback
        │    ├─ transfer → TransferHumanTool → Redis 队列 + sessions.status
        │    ├─ tool     → QueryOrder / QueryProduct / Refund / CreateTicket → MySQL
        │    ├─ rag      → RAGService → EmbeddingService → Milvus
        │    │              └─ 返回 answer + citations;失败降级关键词检索
        │    └─ llm      → LLMService → DeepSeek
        └─ 落库 messages / sessions → MySQL(citations 写入 message metadata)
```

## 2. 分层

| 层 | 目录 | 职责 |
| --- | --- | --- |
| 接口层 | `app/api/v1/` | 参数校验、鉴权边界、响应组装 |
| Agent 层 | `app/agents/` | 决策路由、工具编排、提示词 |
| 服务层 | `app/services/` | LLM、情感、意图、向量、RAG |
| 数据层 | `app/models/`、`app/core/database.py` | ORM 与连接池 |
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
     模型节点决定调用哪个工具,工具节点执行现有工具并回传 Observation,
     条件边决定继续或结束,最多 5 步;复合任务由模型自主完成
     「query_order → 判断状态 → refund(cancel/return)」;
   - 图不可用、执行失败、超步数、空回复或没有工具结果时,回退到既有单步 Agent(Agent Fallback);
   - 其余意图仍按 `handler_type` 路由:转人工 / 工具 / RAG / 纯 LLM;
   - RAG 路径同时返回 `citations`,知识检索工具在多步图内也会回填引用;
   - 负向情绪自动添加安抚前缀。
5. 保存机器人回复(意图、置信度、情感、工具调用记录、citations)。
6. 更新会话状态、消息数、最后消息时间。
7. 订单工具输出与订单 API 响应统一做 PII 脱敏(手机号 / 姓名 / 详细地址)。

## 4. Agent 与工具

| 工具 | 数据来源 | 说明 |
| --- | --- | --- |
| `search_knowledge` | Milvus + 本地 JSON 降级 | 语义检索知识库 |
| `query_order` | MySQL | 按订单号/用户查询,**校验订单归属**,输出 PII 脱敏 |
| `query_product` | MySQL | 关键词匹配商品、库存、价格 |
| `refund` | MySQL | 取消订单真实写库(幂等);退款/退货给流程指引 |
| `transfer_human` | Redis + MySQL | 排队、更新会话为 transferred |
| `create_ticket` | MySQL | 创建工单 |

意图 → 工具映射在 `CustomerServiceAgent._handle_with_tools()`:
`order_query → query_order`、`cancel_order/refund_request → refund`、
`order_modify → create_ticket`、`complaint/human_agent → transfer_human`。

多步路径通过 `app/agents/graph/tool_adapters.py` 把同一批工具包装成
LangChain `StructuredTool`,工具内部逻辑不变;ChatModel 与图均通过依赖注入提供,
测试使用脚本化 Fake ChatModel,不会访问真实 DeepSeek。

多步图覆盖 `order_query` / `cancel_order` / `refund_request` 三类订单售后意图。
复合任务由模型自主编排:先查询真实状态,再决定 `refund(action=cancel)` 或
`refund(action=return)`;取消工具只对「待支付 / 已支付」生效,并做幂等处理,
避免 Agent Fallback 重复执行写操作。

一次复合任务的工具链会在响应的 `tool_calls` 中完整呈现:

```json
[
  { "tool": "query_order", "success": true },
  { "tool": "refund", "success": true }
]
```

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
| 写操作幂等 | 复合任务与 fallback 可能重复调用工具,取消/退款做幂等处理 |
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

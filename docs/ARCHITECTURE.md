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
        │    ├─ 订单查询 → LangGraph 多步 Agent(model ↔ tools,≤5 步)→ 现有工具
        │    │              └─ 失败 / 超步数 / 空结果 → 单步 fallback
        │    ├─ transfer → TransferHumanTool → Redis 队列 + sessions.status
        │    ├─ tool     → QueryOrder / QueryProduct / Refund / CreateTicket → MySQL
        │    ├─ rag      → RAGService → EmbeddingService → Milvus
        │    └─ llm      → LLMService → DeepSeek
        └─ 落库 messages / sessions → MySQL
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

1. `POST /api/v1/chat/send` 校验会话,Redis 限流(默认 60 次/分钟)。
2. 读取最近 10 条消息作为上下文。
3. 保存用户消息(先落库,工具内部 commit 时一并持久化)。
4. `CustomerServiceAgent.chat()`:
   - 清洗文本、替换敏感词;
   - 情感分析 → `positive / neutral / negative`;
   - 意图识别 → 关键词与 LLM 融合,抽取实体;
   - 订单查询优先交给 LangGraph 多步 Agent:模型节点决定调用哪个工具,
     工具节点执行现有工具并回传 Observation,条件边决定继续或结束,最多 5 步;
   - 图不可用、执行失败、超步数、空回复或没有工具结果时,回退到既有单步 Agent(Agent Fallback);
   - 其余意图仍按 `handler_type` 路由:转人工 / 工具 / RAG / 纯 LLM;
   - 负向情绪自动添加安抚前缀。
5. 保存机器人回复(意图、置信度、情感、工具调用记录)。
6. 更新会话状态、消息数、最后消息时间。

## 4. Agent 与工具

| 工具 | 数据来源 | 说明 |
| --- | --- | --- |
| `search_knowledge` | Milvus + 本地 JSON 降级 | 语义检索知识库 |
| `query_order` | MySQL | 按订单号/用户查询,**校验订单归属** |
| `query_product` | MySQL | 关键词匹配商品、库存、价格 |
| `refund` | MySQL | 取消订单真实写库;退款/退货给流程指引 |
| `transfer_human` | Redis + MySQL | 排队、更新会话为 transferred |
| `create_ticket` | MySQL | 创建工单 |

意图 → 工具映射在 `CustomerServiceAgent._handle_with_tools()`:
`order_query → query_order`、`cancel_order/refund_request → refund`、
`order_modify → create_ticket`、`complaint/human_agent → transfer_human`。

多步路径通过 `app/agents/graph/tool_adapters.py` 把同一批工具包装成
LangChain `StructuredTool`,工具内部逻辑不变;ChatModel 与图均通过依赖注入提供,
测试使用脚本化 Fake ChatModel,不会访问真实 DeepSeek。

当前阶段只有 `order_query` 意图接入多步图,其余意图保持单步 Agent,以便先验证
工具适配与 fallback 链路;这与 ADR-0001 的渐进接入方向一致,后续 ticket 再扩展。

## 5. RAG 链路

```text
知识入库:MySQL knowledge 表 ──► BGE 向量化 ──► Milvus(collection: knowledge_base)
在线检索:用户问题 ──► BGE 向量化 ──► Milvus COSINE top-k ──► 拼接上下文 ──► LLM 生成
```

- 向量主键直接使用 `knowledge.id`,与业务数据天然对应,重复写入即更新(upsert)。
- Milvus 或 Embedding 不可用时自动降级为本地关键词检索(`knowledge_base/faqs.json`),
  保证开发期系统始终可用。
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

## 7. 已知演进方向

- 登录与 JWT 鉴权(目录与依赖已预留)。
- 意图语义召回(将示例语料向量化)。
- WebSocket 流式输出。
- Alembic 数据库迁移。
- 意图/情感准确率离线评估集。

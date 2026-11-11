# 架构设计

> 可复现命令见 [演示脚本](DEMO.md)。

## 1. 总览

```text
静态 HTML/CSS/JS
        │  HTTP / SSE
        ▼
FastAPI ── Chat API
        ├─ 消息预处理(清洗 / 敏感词)
        ├─ 指代消解 ──────────────► CorefService
        ├─ 情感分析 ──────────────► SentimentService
        ├─ 意图识别 ──────────────► IntentService(规则 + LLM)
        ├─ 路由
        │    ├─ 订单查询 / 取消 / 退款 → LangGraph 多步 Agent(只读工具 + 申请工具,≤5 步)
        │    │              ├─ 复合任务:query_order → 判断状态 → propose_after_sales_action
        │    │              └─ 失败 / 超步数 / 空结果 → 单步 fallback
        │    ├─ transfer → TransferHumanTool → Redis 队列 + sessions.status
        │    ├─ tool     → QueryOrder / QueryProduct / ProposeAction / CreateTicket → MySQL
        │    ├─ rag      → RetrievalService(BM25 + 向量 + RRF + bge-reranker)
        │    │              ├─ 证据闸 + 自检 → 充分才生成 answer + citations
        │    │              └─ 不足 → 拒答 + low_confidence_questions
        │    └─ llm      → LLMService → DeepSeek
        ├─ 工具执行 ──────────────► 进程内工具 / MCP Server(Streamable HTTP,可选)
        ├─ 审批服务 → 策略引擎 + 订单核验 + 审批执行 → MySQL
        ├─ 知识飞轮 → low_confidence_questions → qa_extraction_staging → 人工采纳 → knowledge
        ├─ SSE 事件流 → meta / delta / tool / citations / actions / done
        ├─ 观测(可选) ────────────► Langfuse(trace / generation)
        └─ 落库 messages / sessions / service_tasks / agent_runs / agent_steps
           / approvals / policy_decisions / audit_logs / low_confidence_questions
           / qa_extraction_staging → MySQL
```

## 2. 分层

| 层 | 目录 | 职责 |
| --- | --- | --- |
| 接口层 | `app/api/v1/` | 参数校验、鉴权边界、响应组装、审批接口 |
| Agent 层 | `app/agents/` | 决策路由、工具编排、提示词、MCP 客户端代理 |
| 工具服务层 | `app/mcp/` | 两个独立 MCP Server:知识/商品、订单/售后 |
| 运行时 | `app/runtime/` | 售后事项、Agent 运行步骤、审批状态机与执行 |
| 策略层 | `app/policies/` | policy-as-code 规则匹配与决策审计 |
| 服务层 | `app/services/` | LLM、情感、意图、向量、混合检索、重排、证据闸、自检、记忆、知识飞轮 |
| 数据层 | `app/models/`、`app/core/database.py` | ORM 与连接池(22 张表) |
| 基础设施 | MySQL / Redis / Milvus | 业务数据、缓存队列、向量 + BM25 索引 |

## 3. 一次对话的完整流程

1. `POST /api/v1/chat/send`(或 `/send-stream`)校验会话,
   Redis Lua 原子滑动窗口限流(默认 60 次/分钟)。
2. 读取最近 30 条消息,按字符预算滑窗;若会话有摘要,把摘要行放在上下文最前。
3. 先提交用户消息,再执行 Agent;即使工具异常回滚,用户输入也不会丢失。
4. `CustomerServiceAgent.chat()`:
   - 清洗文本、替换敏感词;
   - 指代消解:把「那物流呢」「帮我退了」补成完整问法(LLM + 规则兜底);
   - 情感分析 → `positive / neutral / negative`;
   - 意图识别 → 关键词与 LLM 融合,抽取实体;
   - `order_query` / `cancel_order` / `refund_request` 优先交给 LangGraph 多步 Agent:
     模型节点决定调用哪个工具,工具节点执行只读工具或生成售后申请并回传 Observation,
     条件边决定继续或结束,最多 5 步;复合任务由模型自主完成
     「query_order → 判断状态 → propose_after_sales_action」;
   - 图不可用、执行失败、超步数、空回复或没有工具结果时,回退到既有单步 Agent(Agent Fallback);
   - 其余意图仍按 `handler_type` 路由:转人工 / 工具 / RAG / 纯 LLM;
   - 工具执行统一走注册表:权限 → JSON Schema → 超时/只读重试 → 审计;
   - RAG 路径:混合检索 → 证据闸 → 自检 → 生成;
     证据不足返回固定兜底话术、`citations=[]`、`evidence_status=insufficient`,
     并写入低置信度池;
   - 问候/闲聊走固定话术,零模型调用;负向情绪自动添加安抚前缀。
5. 保存机器人回复(意图、置信度、情感、工具调用记录、citations、待审批申请、
   证据状态),并记录 `agent_run` 与 `agent_steps`。
6. 更新会话状态、消息数、最后消息时间;长会话异步生成摘要。
7. 订单工具输出与订单 API 响应统一做 PII 脱敏(手机号 / 姓名 / 详细地址)。
8. 用户核验订单后确认/拒绝审批;高风险申请需要客服工号,审批服务重新走策略与状态校验
   后幂等执行(取消写库、退款/退货建工单)。
9. `send-stream` 用 SSE 输出事件;RAG 路径逐 token 输出,工具路径输出事件 + 完整回复。

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

工具执行统一走 `app/agents/tools/registry.py` + `tool_adapters.py`:

```text
查工具 → 权限(read / proposal / write)
→ JSON Schema 校验(失败回灌模型,让它修正或追问)
→ 执行(超时;只读工具允许一次重试)
→ 审计(名称 / 参数 / 结果摘要 / 耗时 / 状态)
```

`write` 权限在图内一律拒绝,真实写操作只能由审批服务执行;
`proposal` 允许模型提交售后申请,但不会直接改订单。

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

### 4.2 MCP 工具服务化

默认走进程内工具;设置 `MCP_ENABLED=true` 后,`build_default_tools()` 与
`build_graph_tools()` 会把每个工具包装成 `McpToolProxy`:

```text
模型 tool_call
  → tool_adapters(权限 / JSON Schema / 超时)
  → McpToolProxy(注入 user_id / session_id / user_message)
  → MCP ClientSession(Streamable HTTP)
  → app/mcp/knowledge_server.py / aftersales_server.py
  → 同一套工具实现 → MySQL / Redis / Milvus
  └─ 连接 / 协议 / 超时失败 → 进程内工具(可配置关闭)
```

- 模型可见 Schema 优先来自 Server 动态清单(默认缓存 60 秒),上下文参数不暴露给模型;
  清单不可达时退回本地工具 Schema;
- MCP Server 每次调用创建独立 `AsyncSessionLocal`,与后端共用基础设施;
- 只有幂等只读工具(`search_knowledge` / `query_order` / `query_product`)
  允许传输失败后回退本地;写/申请/转人工返回 `MCP_RESULT_UNKNOWN`;
- 执行引擎对这三个副作用工具不自动重试,避免超时后重复建单/排队;
- 独立进程与后端共享 `knowledge_base` / `config` / HF 缓存卷;
- `/health` 只做存活检查,不触发数据库或向量库连接;
- MCP Server 只部署在可信内部网络,不映射宿主端口。

## 5. RAG 2.0 链路

```text
知识入库:MySQL knowledge ──► BGE 向量 ──► Milvus(dense)
                         └─ text(问题+答案) ──► BM25 function ──► sparse

在线检索:用户问题
  → Query 扩写 / 子句拆分(可选)
  → 向量 + BM25 并行召回
  → RRF 融合
  → 本地 bge-reranker 精排
  → 证据置信度(四信号)+ 生成前自检
  → 充分:生成回答 + citations
  → 不足:固定兜底话术 + low_confidence_questions
```

- 向量主键直接使用 `knowledge.id`,重复写入即更新(upsert);写入后 flush,
  保证 BM25 索引可检索。
- `text` 字段使用 Milvus 中文 analyzer(`{"type": "chinese"}`),BM25 函数只接受
  1 个输入字段,因此用「问题 + 答案」拼接文本参与 BM25。
- 四策略可评测:`vector / bm25 / hybrid / hybrid_rerank`;
  本地重排把 Recall@1 从 0.9722 提升到 1.0000(36 条评测,详见 [RAG_EVAL.md](RAG_EVAL.md))。
- Embedding / Rerank 可通过 `EMBEDDING_PROVIDER`、`RERANK_PROVIDER` 切到
  OpenAI 兼容远程服务(如 SiliconFlow);远程失败回退本地 embedding / 混合顺序。
- 证据置信度四个信号:Top1 分、有效证据数、Top1-Top2 分差、关键条款命中;
  阈值默认 0.5。证据不足不硬生成,避免编造政策。
- `retrieve_with_evidence()` 返回 hits / context / citations / evidence / mode;
  引用随聊天响应返回并写入消息 metadata,会话回放仍可展示。
- Milvus 或 Embedding 不可用时自动降级为关键词 + bigram 检索,
  并带 30 秒冷却;BM25 与向量使用独立冷却,避免一个字段缺失拖垮另一路。
- 知识飞轮:低置信度问题 → `scripts/mine_knowledge.py` 抽取候选 →
  `qa_extraction_staging` → 人工采纳才写入 `knowledge` 并向量化。
- 文档知识:`scripts/import_documents.py` 把 Markdown 按标题分层、中文递归切块、
  句级 overlap 后写入 `knowledge_documents/chunks`;片段以 `10_000_000 + chunk.id`
  写入同一 Milvus collection,引用可定位到 `section_path`。
- 回答机械校验:订单号/金额/日期必须逐字来自证据;不一致时重写一次,
  仍不一致则拒答并落低置信度池(`source=answer_guard`)。
- 用户反馈:👍 只记日志,👎 写入低置信度池(`source=user_feedback`),进入飞轮。
- 评测看板:`/api/v1/rag-eval/overview` 只读评测产物(四策略 + 拒答率),
  不在请求里重算。
- 后台作业:`/api/v1/jobs` 只接受白名单作业名,argv 写死在 `app/core/jobs.py`,
  子进程日志写入 `logs/jobs/`;页面无法注入 shell 参数。
- 可观测:配置 `LANGFUSE_*` 后,聊天入口创建根 span 并写入 session/user/tags,
  多步图通过 `CallbackHandler` 上报模型/工具 span,
  `LLMService` 通过 `langfuse.openai.AsyncOpenAI` 上报 generation;
  关闭时统一 flush。未配置时所有观测调用 no-op。

## 6. 关键设计决策

| 决策 | 原因 |
| --- | --- |
| Service 单例 + 懒加载 | BGE / Reranker 模型加载需数秒/数百 MB,禁止按请求重复加载 |
| Agent 无状态 + DB 历史 | 多 worker/重启后不丢上下文 |
| 配置分两层(.env + YAML) | 密钥与连接串不进 Git;业务参数可共享 |
| 统一数据库事务 | 知识条目与向量主键同源,避免双写不一致 |
| 工具接收 `AsyncSession` | 同一次请求复用一个连接,避免连接爆炸 |
| 失败降级 | LLM / RAG / Redis 任一故障不阻断主流程 |
| 多步 Agent 主路径 + 单步 fallback | 展示 LangGraph 多步工具调用,同时保留稳定可演示的兜底路径 |
| 写操作幂等 | 审批状态机 + 执行前状态重验,重复确认不会重复执行 |
| 模型提申请、系统执行 | 模型没有退款/取消写权限,避免过度自治与误操作 |
| Policy-as-code | 金额/状态/风险规则可配置、可审计、可版本化 |
| 订单核验 | 订单号 + 手机后四位,防止仅凭订单号查看/操作他人订单 |
| 混合检索 + RRF + 重排 | 互补召回,重排把弱召回重新排到正确位置 |
| 证据闸 + 自检 | 证据不足拒答,比“检索到就硬答”安全 |
| 知识飞轮 | 模型候选不直接入库,人工复核后才成为依据 |
| 运行步骤落库 | 每次 Agent 执行的模型/工具步骤可回放,为评测与排障备料 |
| 结构化引用 | RAG 回答可追溯到知识条目,引用随消息持久化 |
| Redis 原子滑动窗口 | Lua 保证清理、计数、写入原子性,计数随窗口自然过期 |
| PII 脱敏 | 工具输出与 API 响应统一脱敏,原始数据留库 |
| MCP 工具服务化 | 工具以标准协议独立部署,便于跨进程/跨语言复用;上下文由后端注入,传输失败回退进程内工具保证可用性 |
| Langfuse 观测 | 模型、工具、token 与延迟可追溯;三项配置缺失时完全 no-op,不增加运行负担 |
| 认证默认关闭 | 本地演示零门槛;生产 AUTH_ENABLED=true 并强制 ≥32 字节密钥 |
| 按轮 checkpointer | 不复制跨轮状态,避免标量泄漏;interrupt 只在缺订单号时暂停 |
| Redis 可选 | 单机不依赖 Redis;多副本/共享限流时再启用 |
| 副作用工具不回退 | 超时可能已执行,回退会重复建单/排队;只允许只读工具回退 |

## 7. 可扩展性

- **检索层可替换**:`RetrievalService` 的策略可扩展;更换向量库只需实现
  `RAGService` 的 `add_documents / search_dense / search_bm25 / delete_documents`。
- **工具可扩展**:新增工具只需实现 `execute()` 与 `get_schema()`,
  在 `registry.py` 登记权限/超时/重试即可被单步与多步路径复用。
- **意图可扩展**:意图配置集中在 `IntentService.INTENT_CONFIGS`,
  新增意图后同步种子数据即可参与关键词与 LLM 融合。
- **评测可扩展**:`eval_set.json`、`rag_evaluator.py` 与检索策略解耦,
  增加样本、切换策略或替换知识库后可直接重跑同一套指标。

## 8. MCP 工具服务化

MCP Server 与后端是两个进程,共用同一套工具实现与基础设施:

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| MCP Server(知识/商品) | `app/mcp/knowledge_server.py` | `search_knowledge` / `query_product`;8001 |
| MCP Server(订单/售后) | `app/mcp/aftersales_server.py` | 订单 / 售后申请 / 转人工 / 工单;8002 |
| MCP 客户端代理 | `app/agents/mcp/client.py` | 隐藏上下文参数、注入身份、Streamable HTTP 调用、传输失败回退 |
| 工具工厂 | `app/agents/tools/factory.py` | `MCP_ENABLED` 决定返回本地工具或代理 |
| Docker 服务 | `docker/docker-compose.yml` | `cs-mcp-knowledge` / `cs-mcp-aftersales`,仅内部网络可达 |

调用链:

```text
ToolContext(user_id, session_id, user_message)
  → tool_adapters(权限 / Schema / 超时 / 审计)
  → McpToolProxy.execute()
  → ClientSession → MCP Server → 本地工具 → MySQL / Redis / Milvus
```

关键约束:

- `user_id` / `session_id` 由后端注入,不出现在模型可见 Schema 中;
- 工具清单通过 `list_tools()` 动态拉取并缓存(`MCP_TOOL_CACHE_TTL`,默认 60 秒);
  Server 侧新增工具无需重启后端,缓存过期后自动生效;
- 只有幂等只读工具允许传输失败后回退本地;写/申请/转人工返回
  `MCP_RESULT_UNKNOWN`,且执行引擎对这些工具不自动重试;
- `MCP_FALLBACK_TO_LOCAL=false` 可关闭只读工具回退,用于验证纯 MCP 链路;
- `MCP_TIMEOUT` 默认 45 秒,覆盖 MCP Server 首次加载 BGE / Reranker 的时间;
- 独立进程首次检索会各自加载模型,镜像共享 HF 缓存卷;
- MCP Server 无公网鉴权,生产环境必须保持内部网络隔离。

## 9. Langfuse 观测

| 链路 | 接入方式 | 记录内容 |
| --- | --- | --- |
| LangGraph | `langfuse.langchain.CallbackHandler` + `langchain_config()` | 模型节点、工具节点、图执行耗时 |
| 原生 OpenAI | `langfuse.openai.AsyncOpenAI` | generation:模型、token、延迟、输入输出 |
| 聊天入口 | 根 span + `propagate_attributes` | trace 名称、session_id、user_id、tags、请求输入 |
| 意图标注 | `tag_current_trace()`(`propagate_attributes` + `create_event`) | intent、intent_confidence、`intent:*` tag |
| 进程退出 | `shutdown_observability()` | flush + shutdown |

- 三项配置(`LANGFUSE_PUBLIC_KEY` / `SECRET_KEY` / `BASE_URL`)缺任意一项时,
  `get_callbacks()`、`trace_scope()`、`tag_current_trace()`、`shutdown_observability()`
  全部 no-op;
- `LANGFUSE_BASE_URL` 同时兼容 Langfuse Cloud 与自建实例;
- 仓库提供可选自托管栈 `docker/docker-compose.langfuse.yml`,使用 Chainguard
  MinIO 规避官方镜像停发问题,并 headless 初始化项目 key;
- 观测失败只记录 warning,不影响聊天、工具与审批主流程。

## 10. 认证与 RBAC

- `AUTH_ENABLED=false` 时保持本地演示兼容,不做鉴权;
- 开启后纯 ASGI 中间件保护 `/api/v1/*`(登录/注册/`/auth/config` 放行),
  每次请求从数据库重载 `is_active` 与 `user_type`,不信任 token 里的角色;
- `require_roles` / `require_admin` 用于路由级 RBAC;知识库、飞轮、作业、
  RAG 评测、分析等管理接口要求 admin;
- 会话/订单/审批接口通过 `app/core/access.py` 做归属校验,
  顾客访问他人资源返回 404,staff 放行;
- 口令使用 bcrypt,令牌使用 PyJWT HS256;生产必须配置 ≥32 字节 JWT 密钥;
- `users.token_version` 写入 JWT `ver`;改密/重置/改角色/禁用时 +1,
  中间件对比数据库版本,旧 token 立即失效;
- `/api/v1/admin/users` 提供用户列表/创建/角色/禁用/重置密码,
  并保护最后一个启用管理员;
- 短信登录:验证码只存 HMAC(`login_codes`),console 通道写日志,
  登录时手机号不存在则自动建 customer;
- 扫码登录:`qr_login_sessions` 票据 → 已登录用户 approve → status 轮询领取 token;
- `tenant_id` 写入 User/Session/JWT;中间件以数据库为准,会话访问按租户隔离。

## 11. Checkpointer 与 interrupt/resume

```text
thread_id = f"{session_id}:{user_message_id}"
多步图 ── 模型节点 ── gate ── interrupt(订单选择 / 工单确认) ── 工具节点
                     │                                    ├─ propose_after_sales_action
                     │                                    └─ create_ticket(确认后)
                     └─ 无缺参时直接进入工具节点
```

- SQLite checkpointer 默认开启,Postgres 可选;初始化失败降级 `InMemorySaver`;
- 订单选择 gate 只做只读查询;工单 gate 在 `write_confirmed` 前不允许写;
- 售后申请仍走审批单 + 策略引擎 + 订单核验;工单确认只解决建单 slot-filling;
- 每轮结束清理 checkpoint,避免 SQLite 无限增长。

### 11.1 确定性路由图

`GRAPH_ORCHESTRATOR_ENABLED=true` 时,`CustomerServiceAgent.chat` 先走
`app/agents/graph/orchestrator.py`:

```text
preprocess → memory_context → coref → intent → route
  ├─ script(问候/闲聊)
  ├─ transfer(转人工)
  ├─ retrieve_knowledge → evidence_gate → generate_answer
  ├─ main_agent(单步工具 / 多步 ReAct 子图)
  └─ llm(普通生成)
→ finalize(情感前缀 / 快捷回复 / 结果组装)
```

共 12 个节点;图失败自动回退旧单步链路;SSE 工具/转人工路径复用同一结果,
RAG 流式仍走原逐 token 路径。

## 12. 韧性与运维

- **限流**:`RATE_LIMIT_BACKEND=auto|memory|redis`;Redis 未配置走进程内存,
  Redis 故障自动降级/冷却;可选纯 ASGI 按 IP 中间件。
- **熔断**:chat / embed / rerank 三个熔断器,closed → open → half_open,
  半开只放一个探针;401/402/403 不重试。
- **保留期**:`app/services/retention_service.py` 按 created_at 分批删除,
  先子后父,默认关闭;提供 dry-run 作业。
- **Skills**:`app/services/skill_service.py` 按意图加载 `skills/*.md`,
  只追加系统提示词。
- **语义历史**:摘要边界切窗 + 可选 embedding 检索补捞,失败静默降级。
- **观测**:`/api/v1/observability/*` 提供运行概览、轨迹回放与按天 Token 成本;
  `agent_runs.total_tokens` 由模型 usage/近似值汇总。
- **Checkpoint 清理**:每轮正常结束删除 thread;`checkpoint-cleanup` 作业按
  `CHECKPOINT_TTL_HOURS` 清理遗留的未完成 thread。

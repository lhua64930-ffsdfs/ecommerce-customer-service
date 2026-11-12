# API 规范

- Base URL:`http://127.0.0.1:8000`
- 前缀:`/api/v1`
- 内容类型:`application/json`
- 交互式文档:`/docs`、`/redoc`

## 错误格式

```json
{ "detail": "错误说明" }
```

| 状态码 | 含义 |
| --- | --- |
| 400 | 请求体解析失败 / thread_id 无效 |
| 401 | 未登录或 token 无效 |
| 403 | 角色不足或账号停用 |
| 404 | 资源不存在 / 无权访问 |
| 409 | 审批/thread 状态冲突 |
| 422 | 参数校验失败 |
| 429 | 触发限流 |
| 500 | 服务内部错误 |

---

## 认证

`AUTH_ENABLED=true` 时,除 `/auth/config`、`/auth/login`、`/auth/register`
外的 `/api/v1/*` 都需要 `Authorization: Bearer <token>`。

### GET /api/v1/auth/config

返回 `{ "auth_enabled": true, "registration_enabled": true }`。

### POST /api/v1/auth/login

```json
{ "username": "demo_admin", "password": "admin123" }
```

返回 `{ "token": "...", "user_id": 1, "username": "demo_admin", "user_type": "admin" }`。

### POST /api/v1/auth/register

`AUTH_ENABLED=true` 且 `REGISTRATION_ENABLED=true` 时可用;角色固定为 customer。

### GET /api/v1/auth/me

返回当前账号 `user_id / username / roles`。

### POST /api/v1/auth/change-password

`{ "old_password": "...", "new_password": "..." }`。

### 短信登录(需 AUTH_ENABLED=true)

- `POST /api/v1/auth/sms/send` `{ "phone": "13900000000" }`;
  `SMS_DEBUG_RETURN_CODE=true` 时返回 `debug_code`;
- `POST /api/v1/auth/sms/login` `{ "phone": "...", "code": "123456" }` →
  token;手机号不存在时自动创建 customer。

### 扫码登录(需 AUTH_ENABLED=true)

- `POST /api/v1/auth/qr/start` → `{ ticket, expires_in, url }`;
- `POST /api/v1/auth/qr/approve`(Bearer)`{ "ticket": "..." }`;
- `GET /api/v1/auth/qr/status?ticket=...` → `pending/approved/expired/consumed`;
  approved 时返回 token 并标记 consumed。

### 租户

注册、管理员建用户可传 `tenant_id`;JWT 带 `tenant`,会话按租户隔离,
跨租户访问返回 404。

---

## 对话

### POST /api/v1/chat/session

创建会话。不传 `user_id` 时使用演示用户 `demo_customer`。

请求:

```json
{ "user_id": null, "channel": "web", "initial_message": null }
```

响应:

```json
{
  "session": {
    "session_id": "34a85931b2444f04897391f573870a95",
    "user_id": 1,
    "status": "active",
    "started_at": "2026-10-19T14:00:00",
    "message_count": 0,
    "bot_name": "智能客服小e"
  },
  "welcome_message": "您好!我是智能客服小e...",
  "quick_replies": ["查订单", "商品咨询", "退款退货", "转人工"]
}
```

### POST /api/v1/chat/send

发送消息。每会话默认限流 60 次/分钟,Redis Lua 原子滑动窗口计数;
超限返回 429,并带 `Retry-After: 60` 响应头。

请求:

```json
{ "session_id": "xxx", "content": "查订单 ORDER20260315001" }
```

响应:

```json
{
  "response": "📦 订单详情...",
  "intent": {
    "intent_code": "order_query",
    "intent_name": "订单查询",
    "confidence": 0.75,
    "entities": [
      { "type": "order_no", "value": "ORDER20260315001", "start": 4, "end": 20 }
    ],
    "handler_type": "tool",
    "priority": 8
  },
  "sentiment": "neutral",
  "sentiment_score": 0.0,
  "quick_replies": ["查看全部订单", "物流到哪了", "转人工"],
  "need_transfer": false,
  "message_id": 42,
  "tool_calls": [{ "tool": "query_order", "success": true }],
  "citations": [],
  "pending_approval": null,
  "evidence_status": null,
  "run_id": "a1b2c3d4e5f6...",
  "agent_mode": "multi_step",
  "thread_id": "session-uuid",
  "interrupt": null
}
```

多步图缺订单号时会返回:

```json
{
  "interrupt": {
    "type": "select_order",
    "message": "请选择要办理的订单",
    "orders": [{ "order_no": "ORDER20260401001", "status": "paid" }]
  },
  "thread_id": "session-uuid"
}
```

`evidence_status` 仅 RAG 路径有值:`sufficient` / `insufficient`;证据不足时
`citations=[]` 且回复为固定兜底话术。

MCP 开启时,`tool_calls` 可能带可选的 `transport` 字段:`mcp`(远程执行)或
`local_fallback`(MCP 不可用,回退进程内工具);未开启或进程内执行时不带该字段。

`citations` 为 RAG 回答引用的知识条目;非 RAG 路径返回空数组:

```json
{
  "id": 1,
  "category": "退换货政策",
  "question": "商品可以退换吗",
  "score": 0.77
}
```

复合任务(查订单 → 取消)不会直接修改订单,而是返回待确认的售后申请:

```json
{
  "response": "已生成取消申请,请在确认卡片中确认...",
  "tool_calls": [
    { "tool": "query_order", "success": true },
    { "tool": "propose_after_sales_action", "success": true }
  ],
  "citations": [],
  "pending_approval": {
    "approval_id": "APV1730000000ABCD",
    "action": "cancel",
    "order_no": "ORDER20260401001",
    "summary": "取消订单 ORDER20260401001,退款 ¥2699.00 原路退回",
    "risk_level": "medium",
    "status": "pending",
    "requires_verification": true,
    "requires_human": false
  },
  "evidence_status": null,
  "run_id": "a1b2c3d4e5f6...",
  "agent_mode": "multi_step"
}
```

`agent_mode` 表示本次请求实际使用的处理路径:

| 值 | 含义 |
| --- | --- |
| `multi_step` | 订单查询 / 售后申请由 LangGraph 多步 Agent(只读工具 + 申请工具,最多 6 步)完成 |
| `single_step` | 单步路径(转人工 / 只读工具 / RAG / LLM);无模型时为单步离线模式 |

> 多步图失败、超步或空结果时仍返回 `multi_step` + 固定兜底话术,
> 不再切换到单步 Agent。真实的取消/退款/退货写操作只能通过审批接口执行,模型无法直接写库。

### POST /api/v1/chat/verify-order

敏感售后操作前核验订单归属:订单号 + 手机号后四位。

```json
{ "session_id": "xxx", "order_no": "ORDER20260401001", "phone_last4": "1234" }
```

成功返回脱敏订单摘要;失败返回 `{"success": false, "reason": "订单号或手机号后四位不正确"}`。

### POST /api/v1/chat/approvals/{approval_id}/approve

确认/审核售后申请并执行。高风险申请必须传 `reviewer`(客服工号)。

```json
{ "session_id": "xxx", "reviewer": "A001" }
```

```json
{
  "success": true,
  "status": "executed",
  "task_id": 42,
  "result": {
    "success": true,
    "message": "已取消订单 ORDER20260401001,退款将在 1-3 个工作日内原路退回",
    "order_status": "cancelled"
  }
}
```

重复确认返回 `{"success": true, "status": "executed", "already_executed": true}`。

### POST /api/v1/chat/approvals/{approval_id}/reject

```json
{ "session_id": "xxx", "reason": "用户改变主意" }
```

### GET /api/v1/chat/approvals?session_id=xxx

返回会话的审批列表(含状态、风险等级、执行结果)。

### 审批错误码

| code | 含义 |
| --- | --- |
| `require_verification` | 需要先核验订单号 + 手机后四位 |
| `require_human_review` | 高风险操作需要客服工号审核 |
| `already_executed` | 审批单已执行 |
| `approval_not_found` | 审批单不存在或不属于当前会话 |
| `order_not_found` | 订单不存在或不属于当前账号 |
| `invalid_status` | 审批单状态不允许当前操作 |

### POST /api/v1/chat/send-stream

SSE 流式发送消息。请求体同 `/chat/send`;响应 `text/event-stream`,
每条事件为 `data: {json}`:

| 事件 | 说明 |
| --- | --- |
| `meta` | 意图、情感、情感分 |
| `delta` | 回答文本片段(RAG 路径逐 token) |
| `tool` | 工具调用名称/成功标志(工具路径) |
| `citations` | RAG 引用列表 |
| `actions` | 快捷回复与 `pending_approval` |
| `interrupt` | 图暂停:`thread_id`、`kind`、`orders` / `message` |
| `error` | 流处理错误 |
| `done` | `message_id`、`run_id` 与完整结果 |

```text
data: {"event":"meta","intent":{...},"sentiment":"neutral","sentiment_score":0.0}

data: {"event":"delta","text":"商品支持"}

data: {"event":"citations","items":[{...}]}

data: {"event":"actions","quick_replies":[...],"pending_approval":null}

data: {"event":"done","message_id":88,"run_id":"...","result":{...}}
```

### POST /api/v1/chat/resume

继续被 interrupt 暂停的多步图。请求:

```json
{
  "session_id": "xxx",
  "thread_id": "xxx",
  "resume": { "type": "select_order", "order_no": "ORDER20260401001" }
}
```

工单确认场景:

```json
{
  "session_id": "xxx",
  "thread_id": "xxx",
  "resume": { "type": "confirm_ticket", "confirmed": true }
}
```

`confirmed=false` 时不执行建单。返回 `response / thread_id / interrupt /
pending_approval / tool_calls / citations / run_id / message_id / agent_mode`。
thread 不属于该会话、已过期或没有 pending interrupt 时返回 409。

### GET /api/v1/chat/history

参数:`session_id`、`page`(默认 1)、`page_size`(默认 20,最大 100)。

```json
{
  "messages": [
    {
      "id": 1,
      "session_id": "xxx",
      "sender_type": "user",
      "content": "商品可以退换吗",
      "content_type": "text",
      "intent": {
        "intent_code": "product_inquiry",
        "intent_name": "商品咨询",
        "confidence": 0.7,
        "entities": [],
        "handler_type": "rag",
        "priority": 5
      },
      "sentiment": "neutral",
      "sentiment_score": 0.0,
      "citations": [
        {
          "id": 1,
          "category": "退换货政策",
          "question": "商品可以退换吗",
          "score": 0.77
        }
      ],
      "created_at": "2026-10-19T14:00:01"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 20
}
```

### POST /api/v1/chat/transfer

```json
{ "session_id": "xxx", "reason": "用户主动请求" }
```

### POST /api/v1/chat/rate

```json
{ "session_id": "xxx", "score": 5, "comment": "很满意" }
```

---

## 意图

### POST /api/v1/intent/recognize

```json
{ "text": "我要退款", "user_id": 1 }
```

响应为 `IntentResult`(结构同 `chat/send` 中的 `intent`)。

### GET /api/v1/intent/configs

返回全部意图配置(编码、名称、处理器、优先级、关键词)。

---

## Agent

### GET /api/v1/agent/info

```json
{
  "name": "小e",
  "personality": "专业、友好、有耐心",
  "version": "1.0.0",
  "model": "deepseek-chat",
  "llm_provider": "deepseek",
  "llm_mock": true,
  "tools": ["search_knowledge", "query_order", "query_product", "propose_after_sales_action", "transfer_human", "create_ticket"]
}
```

### GET /api/v1/agent/tools

返回 6 个工具的 JSON Schema。

---

## 知识库

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/knowledge/list` | 分页列表,支持 `category` |
| POST | `/knowledge/add` | 新增并向量化 |
| PUT | `/knowledge/{id}` | 更新并重建向量 |
| DELETE | `/knowledge/{id}` | 删除条目与向量 |
| POST | `/knowledge/search` | 语义检索 |

新增请求:

```json
{
  "category": "退换货政策",
  "question": "商品可以退换吗",
  "answer": "7天内可无理由退换货...",
  "keywords": "退换货 退货 退款"
}
```

语义检索请求/响应:

```json
{ "query": "退款多久到账", "top_k": 5, "category": null }
```

```json
{
  "query": "退款多久到账",
  "results": [
    { "id": 11, "score": 0.93, "category": "退款服务", "question": "退款多久到账", "answer": "..." }
  ]
}
```

---

## 文档知识

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/knowledge/documents` | 文档列表与片段数 |
| POST | `/api/v1/knowledge/documents/import` | 导入/替换 Markdown 文档 |
| DELETE | `/api/v1/knowledge/documents/{id}` | 删除文档与片段向量 |

导入请求:

```json
{
  "title": "售后处理手册",
  "source": "after_sales_manual.md",
  "content": "# 售后处理手册\n\n## 退货与退款\n...",
  "chunk_size": 500,
  "overlap": 80
}
```

响应:`{ "document_id": 1, "chunks": 10, "vectorized": true }`。

## 用户反馈

### POST /api/v1/feedback

```json
{ "session_id": "xxx", "question": "质量问题怎么退换", "rating": "down", "comment": "没解决" }
```

👍 只记日志;👎 写入低置信度池,响应 `{"success": true, "pooled": true, "id": 3}`。

## RAG 评测看板

### GET /api/v1/rag-eval/overview

只读 `docs/rag_eval_result.json` 与 `docs/refusal_eval_result.json`:
四策略 Recall/MRR、最佳策略、无答案拒答率与生成时间。没有产物时返回
`present=false` 和运行命令,不在接口里重算。

## 后台作业

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/jobs` | 作业列表与状态 |
| POST | `/api/v1/jobs/{name}` | 启动白名单作业 |
| GET | `/api/v1/jobs/{name}` | 状态 + 日志尾部 |
| POST | `/api/v1/jobs/{name}/stop` | 停止作业 |

作业名:`evaluate-rag`、`evaluate-refusal`、`mine-knowledge`、`import-manual`、
`reset-demo-data`。argv 写死在 `app/core/jobs.py`,前端只能传作业名,不能传参数或路径。

## 知识飞轮

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/review/queue` | 待审候选知识 + 低置信度待处理数 |
| POST | `/api/v1/review/mine` | 从低置信度问题/对话抽取候选知识 |
| POST | `/api/v1/review/{id}/approve` | 采纳候选并写入知识库、向量化 |
| POST | `/api/v1/review/{id}/discard` | 弃用候选 |

`GET /review/queue` 响应:

```json
{
  "items": [
    {
      "id": 7,
      "batch_no": "mine-20261111173126",
      "source_ref": "low_confidence",
      "question": "订单已发货后如何查询物流?",
      "answer": "订单发货后可凭运单号在快递官网或小程序查询物流进度。",
      "status": "extracted",
      "created_at": "2026-11-11T17:31:26"
    }
  ],
  "total": 1,
  "pending_low_confidence": 2
}
```

候选知识不会自动入库;`approve` 后才写 `knowledge` 并重建向量,
`discard` 只改状态,保留审计记录。

## 订单 / 商品

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| GET | `/order/list` | `user_id`、`status`、`page`、`page_size` |
| GET | `/order/{order_no}` | 订单号 |
| GET | `/product/list` | `keyword`、`category`、分页 |
| GET | `/product/{sku}` | SKU |

> 订单接口返回的 `receiver_name`、`receiver_phone`、`shipping_address` 已脱敏,
> 例如 `张**`、`138****6789`、`北京市朝阳区***`。原始数据保留在数据库。

---

## 数据分析

### GET /api/v1/analytics/summary

```json
{
  "sessions_total": 10,
  "sessions_today": 10,
  "messages_total": 28,
  "users_total": 1,
  "open_tickets": 0,
  "ai_resolution_rate": 0.571,
  "transfer_rate": 0.429,
  "satisfaction_avg": null,
  "intent_distribution": [{ "name": "订单查询", "count": 6 }],
  "sentiment_distribution": [{ "name": "neutral", "count": 12 }]
}
```

### GET /api/v1/analytics/sessions

参数:`page`、`page_size`。返回会话列表。

---

## 管理员用户(需 admin)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/admin/users` | 分页用户列表(不返回密码哈希) |
| POST | `/api/v1/admin/users` | 创建用户:username/password/user_type/email/display_name |
| PATCH | `/api/v1/admin/users/{id}` | 调整 user_type / is_active / display_name |
| POST | `/api/v1/admin/users/{id}/reset-password` | 重置密码并 bump token 版本 |

改角色、禁用、改密后,该用户旧 JWT 立即失效(401)。

## 可观测(需 admin)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/observability/overview?days=7` | 运行状态/耗时/Token、失败工具、低置信度、审批分布 |
| GET | `/api/v1/observability/runs?days=7&limit=50` | 最近 Agent 运行 |
| GET | `/api/v1/observability/runs/{run_id}` | 运行详情 + 步骤回放 |
| GET | `/api/v1/observability/cost?days=30` | 按天 Token 成本(本地近似) |

## 健康检查

### GET /health

```json
{ "status": "healthy", "database": true, "redis": true, "redis_configured": true,
  "milvus": true, "checkpointer": "sqlite", "version": "1.0.0" }
```

---

## MCP 工具服务(独立进程)

两个 MCP Server,不属于 `/api/v1`:

| Server | 端口 | 工具 |
| --- | --- | --- |
| knowledge | 8001 | `search_knowledge`、`query_product` |
| aftersales | 8002 | `query_order`、`propose_after_sales_action`、`transfer_human`、`create_ticket` |

### GET http://<mcp-host>:8001/health 与 :8002/health

```json
{ "status": "ok", "service": "after-sales-knowledge", "version": "1.0.0" }
{ "status": "ok", "service": "after-sales-aftersales", "version": "1.0.0" }
```

### POST http://<mcp-host>:8001/mcp 与 :8002/mcp

MCP Streamable HTTP 端点,协议由 MCP SDK 处理。
`user_id` / `session_id` / `user_message` 为后端注入的内部上下文,
不对模型展示;端口不应暴露到公网。

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
| 400 | 请求体解析失败 |
| 404 | 资源不存在 |
| 422 | 参数校验失败 |
| 429 | 触发限流 |
| 500 | 服务内部错误 |

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

发送消息。每会话默认限流 60 次/分钟。

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
  "tool_calls": [{ "tool": "query_order", "success": true }]
}
```

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
  "tools": ["search_knowledge", "query_order", "query_product", "refund", "transfer_human", "create_ticket"]
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

## 订单 / 商品

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| GET | `/order/list` | `user_id`、`status`、`page`、`page_size` |
| GET | `/order/{order_no}` | 订单号 |
| GET | `/product/list` | `keyword`、`category`、分页 |
| GET | `/product/{sku}` | SKU |

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

## 健康检查

### GET /health

```json
{ "status": "healthy", "database": true, "redis": true, "milvus": true, "version": "1.0.0" }
```

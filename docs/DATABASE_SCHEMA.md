# 数据库设计

MySQL 8.0,字符集 `utf8mb4`,存储引擎 InnoDB。ORM 定义位于 `backend/app/models/`。

## ER 关系

```text
users 1 ─── n sessions 1 ─── n messages n ─── 1 intents
  │
  ├── n orders
  └── n tickets

knowledge (独立表,向量主键与 Milvus 中 id 一致)
products  (独立表)
```

## 表清单

| 表 | 模型 | 说明 |
| --- | --- | --- |
| `users` | `User` | 用户(顾客/客服/管理员) |
| `sessions` | `Session` | 会话与状态 |
| `messages` | `Message` | 消息、意图、情感、工具记录 |
| `intents` | `Intent` | 意图字典(定义,非识别记录) |
| `knowledge` | `Knowledge` | 知识库条目 |
| `orders` | `Order` | 订单 |
| `products` | `Product` | 商品 |
| `tickets` | `Ticket` | 工单 |

## 关键字段

### users

`id`、`username`(唯一)、`email`、`phone`、`password_hash`、
`user_type(customer/agent/admin)`、`is_active`、时间戳。
索引:username、phone、email。

### sessions

`id`、`session_id`(UUID,唯一)、`user_id`(FK)、`agent_id`、
`status(active/waiting/transferred/closed)`、`channel`、
`started_at`、`ended_at`、`last_message_at`、`message_count`、`satisfaction_score`。

### messages

`id`、`session_id`(FK)、`sender_type(user/bot/agent)`、`sender_id`、
`content`、`content_type(text/image/voice/file/quick_reply)`、
`intent_id`(FK intents)、`intent_confidence`、`sentiment(positive/neutral/negative)`、
`sentiment_score`、`is_human_transfer`、`is_generated`、`metadata`、`created_at`。

> **实现注意**:`metadata` 是 SQLAlchemy 的保留属性,ORM 中 Python 属性名为 `meta`,
> 通过 `mapped_column("metadata", JSON)` 映射到数据库列,避免声明冲突。

### intents

`id`、`intent_name`、`intent_code`(唯一)、`description`、
`handler_type(rag/tool/transfer/fallback/llm)`、`handler_config`、
`sample_utterances`、`priority`、`is_active`。

启动时从 `IntentService.INTENT_CONFIGS` 自动写入(幂等)。

### knowledge

`id`、`category`、`question`、`answer`、`keywords`、`vector_id`、
`embedding_model`、`hit_count`、`satisfaction_rate`、`is_active`、时间戳。

`vector_id` 默认等于 `id`,对应 Milvus 中向量主键。

### orders

`id`、`order_no`(唯一)、`user_id`(FK)、`status`、`total_amount`、`pay_amount`、
`shipping_address(JSON)`、`receiver_name`、`receiver_phone`、`tracking_no`、
`remark`、`paid_at`、`shipped_at`、`delivered_at`、时间戳。

> 演示数据中 `remark` 用于存商品摘要(文档表结构未包含订单明细表)。

### products

`id`、`sku`(唯一)、`name`、`category`、`brand`、`price`、`original_price`、
`stock`、`sales_count`、`description`、`specifications(JSON)`、`images(JSON)`、
`is_active`、时间戳。

### tickets

`id`、`ticket_no`(唯一)、`session_id`、`user_id`(FK)、
`type(complaint/refund/consult/suggestion/other)`、
`title`、`content`、`status(pending/processing/resolved/closed)`、
`priority(low/normal/high/urgent)`、`assigned_to`、`resolution`、`resolved_at`。

## 种子数据

`app/core/seed.py` 在应用启动时幂等写入:

| 数据 | 数量 |
| --- | --- |
| 演示用户 `demo_customer` | 1 |
| 意图定义 | 15 |
| 商品 | 5 |
| 订单 | 3 |
| 知识库条目 | 12(来自 `knowledge_base/faqs.json`) |

## 迁移

当前使用 `Base.metadata.create_all` 自动建表(开发期)。
生产环境建议引入 Alembic:

```bash
pip install alembic
alembic init migrations
alembic revision --autogenerate -m "init"
alembic upgrade head
```

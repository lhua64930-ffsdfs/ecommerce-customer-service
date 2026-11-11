# 数据库设计

MySQL 8.0,字符集 `utf8mb4`,存储引擎 InnoDB。ORM 定义位于 `backend/app/models/`。

## ER 关系

```text
users 1 ─── n sessions 1 ─── n messages n ─── 1 intents
  │              │
  │              ├── n service_tasks 1 ─── n approvals
  │              │        └── n agent_runs 1 ─── n agent_steps
  │              ├── n verifications
  │              └── n audit_logs
  ├── n orders
  └── n tickets

policy_rules 1 ─── n policy_decisions
approvals n ─── 1 policy_decisions

knowledge (独立表,向量主键与 Milvus 中 id 一致)
products  (独立表)
```

## 表清单

| 表 | 模型 | 说明 |
| --- | --- | --- |
| `users` | `User` | 用户(顾客/客服/管理员) |
| `sessions` | `Session` | 会话与状态 |
| `messages` | `Message` | 消息、意图、情感、工具记录、待审批快照 |
| `intents` | `Intent` | 意图字典(定义,非识别记录) |
| `knowledge` | `Knowledge` | 知识库条目 |
| `orders` | `Order` | 订单 |
| `products` | `Product` | 商品 |
| `tickets` | `Ticket` | 工单 |
| `service_tasks` | `ServiceTask` | 售后事项(任务) |
| `agent_runs` | `AgentRun` | Agent 执行实例 |
| `agent_steps` | `AgentStep` | 执行步骤(模型/工具/策略/审批) |
| `approvals` | `Approval` | 售后审批单 |
| `policy_rules` | `PolicyRule` | 策略规则 |
| `policy_decisions` | `PolicyDecision` | 策略决策审计 |
| `verifications` | `Verification` | 会话级订单核验 |
| `audit_logs` | `AuditLog` | 操作审计 |
| `low_confidence_questions` | `LowConfidenceQuestion` | 低置信度问题池 |
| `qa_extraction_staging` | `QaExtractionStaging` | 对话挖知识暂存(待审) |
| `knowledge_documents` | `KnowledgeDocument` | 文档知识元数据 |
| `knowledge_chunks` | `KnowledgeChunk` | 文档切块片段 |

## 关键字段

### users

`id`、`username`(唯一)、`email`、`phone`、`password_hash`、
`user_type(customer/agent/admin)`、`is_active`、时间戳。
索引:username、phone、email。

### sessions

`id`、`session_id`(UUID,唯一)、`user_id`(FK)、`agent_id`、
`status(active/waiting/transferred/closed)`、`channel`、
`started_at`、`ended_at`、`last_message_at`、`message_count`、`satisfaction_score`、
`summary(JSON: text/upto_message_id)`、`summary_upto_message_id`。

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

### service_tasks

`id`、`task_no`(唯一)、`session_id`(FK)、`user_id`(FK)、`intent_code`、
`task_type(cancel/refund/return/modify)`、
`status(open/pending_approval/executing/completed/rejected/expired/transferred)`、
`target_order_no`、`summary`、`version`、时间戳。
同会话 + 同订单 + 同类型的未完成事项复用。

### agent_runs / agent_steps

`agent_runs`:`run_id`(唯一)、`session_id`(FK)、`task_id`(FK)、`agent_mode`、
`status(running/succeeded/failed/awaiting_approval)`、`total_steps`、
`total_latency_ms`、`total_tokens`、`started_at`、`finished_at`。

`agent_steps`:`run_id`、`seq`、`step_type(model/tool/policy/approval)`、`name`、
`input_json`、`output_json`、`success`、`latency_ms`、`created_at`。

### approvals

`approval_no`(唯一)、`task_id`(FK)、`session_id`(FK)、`user_id`(FK)、
`action(cancel/refund/return/modify)`、`order_no`、`payload`(JSON)、
`policy_decision_id`(FK)、`risk_level(low/medium/high)`、
`status(pending/approved/rejected/executed/expired/cancelled)`、
`requires_verification`、`requires_human`、`decided_by`、`decided_at`、
`executed_at`、`result_json`、时间戳。

### policy_rules / policy_decisions

`policy_rules`:`rule_id`(唯一)、`action`(支持逗号分隔多个动作)、`description`、
`priority`、`conditions`(JSON,AND 组合)、
`decision(allow_auto/needs_confirm/needs_human/deny)`、
`risk_level`、`version`、`is_active`。

`policy_decisions`:`rule_id`、`rule_version`、`action`、`input_json`、
`decision`、`reason`、`created_at`。

### verifications / audit_logs

`verifications`:`session_id`(FK)、`user_id`(FK)、`order_no`、`phone_last4`、
`verified_at`;唯一约束 `(session_id, order_no)`。

`audit_logs`:`user_id`、`session_id`、`action`、`target_type`、`target_id`、
`detail_json`、`created_at`。

### low_confidence_questions / qa_extraction_staging

`low_confidence_questions`:`session_id`、`user_id`、`query`、
`source(retrieval_low_conf/self_check)`、`reason`、`retrieved_snapshot(JSON)`、
`status(pending/approved/discarded)`、`created_at`。

`qa_extraction_staging`:`batch_no`、`source_ref`、`question`、`answer`、
`status(extracted/approved/discarded)`、`created_at`。
LLM 抽取的候选先停在这里,人工采纳后才写入 `knowledge`。

### knowledge_documents / knowledge_chunks

`knowledge_documents`:`title`、`source`、`version`、`status`、时间戳。

`knowledge_chunks`:`document_id`(FK)、`section_path`、`chunk_index`、`content`、
`vector_id`、`is_active`、`created_at`。
文档片段向量主键使用 `10_000_000 + chunk.id`,避免与 FAQ 的 `knowledge.id` 冲突。

## 种子数据

`app/core/seed.py` 在应用启动时幂等写入:

| 数据 | 数量 |
| --- | --- |
| 演示用户 `demo_customer` | 1 |
| 意图定义 | 15 |
| 商品 | 5 |
| 订单 | 4 |
| 知识库条目 | 12(来自 `knowledge_base/faqs.json`) |
| 售后策略规则 | 7(来自 `config/policy_rules.yaml`) |

## 迁移

当前使用 `Base.metadata.create_all` 自动建表(开发期)。
生产环境建议引入 Alembic:

```bash
pip install alembic
alembic init migrations
alembic revision --autogenerate -m "init"
alembic upgrade head
```

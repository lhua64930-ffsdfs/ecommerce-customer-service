# 售后智答 · 可复现演示脚本

> 目标:在 3–5 分钟内,让面试官看到「多步 Agent / fallback / RAG / 转人工 / 数据闭环」。
> 所有命令都在仓库根目录 `after-sales-qa/` 下执行(Git Bash / Linux / macOS)。
> 详细背景见 [ARCHITECTURE.md](ARCHITECTURE.md) 与 [README](../README.md)。

## 0. 演示前准备

### 启动基础设施

```bash
docker compose -f docker/docker-compose.dev.yml up -d
docker compose -f docker/docker-compose.dev.yml ps
```

需要看到 `cs-mysql`、`cs-redis` 为 healthy;Milvus 首次启动需要 60–90 秒。

### 启动后端

```bash
cd backend
# 首次需要:python -m venv venv && venv/Scripts/pip install -r requirements.txt
# 以及:copy .env.example .env
./venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 启动前端(另开终端)

```bash
cd frontend
npm install   # 首次
npm run dev
```

打开 http://localhost:5173。

### 健康检查

```bash
curl -s http://127.0.0.1:8000/health
```

预期:

```json
{
  "status": "healthy",
  "database": true,
  "redis": true,
  "milvus": true,
  "version": "1.0.0"
}
```

> Milvus 为 false 也能演示:RAG 会自动降级关键词检索,订单/转人工不受影响。

### 选择 LLM 模式

| 模式 | 配置 | 订单查询的 `agent_mode` | 用途 |
| --- | --- | --- | --- |
| 真实 LLM | `backend/.env` 配置 `LLM_API_KEY=sk-...` | `multi_step` | 演示 LangGraph 主路径 |
| mock | `LLM_API_KEY` 留空,或 `LLM_PROVIDER=mock` | `single_step_fallback` | 演示 fallback 与离线可用 |

修改 `.env` 后需要重启后端。

> **演示前务必用真实 Key 冒烟一次订单查询**,确认 DeepSeek 会调用 `query_order`。
> 如果模型选择直接回答而不调用工具,图会把「没有工具结果」视为不可用并回退,
> 这是设计内的安全网,但演示主路径时最好提前确认。

---

## 1. 创建会话

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/session \
  -H "Content-Type: application/json" \
  -d "{}"
```

响应(截取):

```json
{
  "session": {
    "session_id": "34a85931b2444f04897391f573870a95",
    "user_id": 1,
    "status": "active"
  },
  "welcome_message": "您好!我是智能客服小e...",
  "quick_replies": ["查订单", "商品咨询", "退款退货", "转人工"]
}
```

把 `session_id` 复制到变量里(下面的命令都用它):

```bash
SESSION_ID="34a85931b2444f04897391f573870a95"
```

---

## 2. 场景 A:订单查询(多步 Agent 主路径)

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"查订单 ORDER20260401001\"}"
```

配置真实 Key 时预期(截取):

```json
{
  "response": "您的订单 ORDER20260401001 当前状态为已支付,待发货...",
  "intent": {
    "intent_code": "order_query",
    "handler_type": "tool",
    "entities": [
      { "type": "order_no", "value": "ORDER20260401001" }
    ]
  },
  "sentiment": "neutral",
  "need_transfer": false,
  "tool_calls": [{ "tool": "query_order", "success": true }],
  "agent_mode": "multi_step"
}
```

**讲解词**:

> 这条请求被识别为 `order_query`,进入 LangGraph:
> 模型节点看到 6 个工具,决定调用 `query_order`;
> 工具节点执行后把订单结果回传给模型;模型再生成最终回复。
> 响应里的 `agent_mode=multi_step` 和 `tool_calls` 就是这条链路的证据。

种子订单:

| 订单号 | 状态 | 用途 |
| --- | --- | --- |
| `ORDER20260401001` | `paid`(已支付,待发货) | 订单查询 / 后续取消场景 |
| `ORDER20260315001` | `shipped`(已发货) | 物流查询 |
| `ORDER20260310005` | `delivered`(已收货) | 退货场景 |

---

## 3. 场景 B:Agent Fallback(LLM 不可用 / 图失败)

### 方式一:直接体验无 Key 模式

把 `backend/.env` 里的 `LLM_API_KEY` 置空(或设置 `LLM_PROVIDER=mock`),重启后端,
再发同样的请求:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"查订单 ORDER20260401001\"}"
```

预期:

```json
{
  "response": "📦 订单详情 ... ORDER20260401001 ...",
  "tool_calls": [{ "tool": "query_order", "success": true }],
  "agent_mode": "single_step_fallback"
}
```

**讲解词**:

> LLM 不可用时,多步图不会勉强运行,而是把同一请求回退给原来的单步 Agent。
> 单步 Agent 用意图识别直接路由到 `query_order`,所以用户仍然能拿到订单。
> `agent_mode=single_step_fallback` 让调用方可以看到这次走的是兜底路径。

### 方式二:跑自动化测试(确定性更强)

```bash
cd backend
./venv/Scripts/python.exe -m pytest tests/api/test_chat_api.py -k "multi_step or falls_back" -v
```

预期:

```text
test_order_query_uses_multi_step_agent PASSED
test_multi_step_transfer_propagates_need_transfer PASSED
test_order_query_falls_back_when_graph_fails PASSED
```

**讲解词**:

> 这里通过 FastAPI dependency override 注入脚本化 Fake ChatModel,
> 第一个测试精确断言图调用了 `query_order`;
> 第二个测试让模型直接抛错,断言同一请求回退单步并返回 200。
> 整个过程不访问真实 DeepSeek。

---

## 4. 场景 C:RAG 知识问答

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"商品可以退换吗\"}"
```

预期(无 Key 时 mock 会直接复用知识库答案):

```json
{
  "response": "根据平台规则:7天内可无理由退换货...",
  "intent": {
    "intent_code": "product_inquiry",
    "handler_type": "rag"
  },
  "agent_mode": "single_step"
}
```

也可以直接调用检索接口,展示向量检索结果:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/knowledge/search \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"退款多久到账\",\"top_k\":3}"
```

预期:

```json
{
  "query": "退款多久到账",
  "results": [
    {
      "id": 11,
      "score": 0.93,
      "category": "退款服务",
      "question": "退款多久到账",
      "answer": "..."
    }
  ]
}
```

**讲解词**:

> 知识入库时用 BGE 中文模型向量化,Milvus 用 COSINE 检索;
> 如果 Milvus 或 Embedding 不可用,会自动降级为关键词 + bigram 检索。
> 当前检索结果已经带 `id / score / category`,但还没在聊天响应里暴露结构化引用,
> 这是下一步 T3 的工作。

---

## 5. 场景 D:投诉 / 转人工

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"太差了我要投诉\"}"
```

预期:

```json
{
  "response": "😔 很抱歉给您带来不愉快的体验...已为您优先转接投诉处理专员...",
  "sentiment": "negative",
  "need_transfer": true,
  "tool_calls": [{ "tool": "transfer_human", "success": true }],
  "agent_mode": "single_step"
}
```

**讲解词**:

> 情感分析识别为 negative,Agent 先加安抚前缀;
> 意图是投诉/转人工,`transfer_human` 更新会话状态并写入 Redis 排队队列。
> 这条路径还是单步 Agent,和多步订单查询形成对比。

---

## 6. 场景 E:订单归属 / 不泄露

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"查订单 ORDER99999999999\"}"
```

预期(无 Key / fallback 时):

```json
{
  "response": "未找到订单号 ORDER99999999999,请确认订单号是否正确",
  "tool_calls": [{ "tool": "query_order", "success": false }],
  "agent_mode": "single_step_fallback"
}
```

**讲解词**:

> 用户身份以会话为准,请求体里的 `user_id` 不会生效;
> `query_order` 查到订单后还会比较 `order.user_id`。
> 订单不存在或不属于当前用户时,只返回统一话术,不泄露订单是否存在。
> 种子数据只有一个演示用户,所以这里用不存在的订单号演示「不泄露」;
> 代码里的归属分支是真实存在的。

---

## 7. 场景 F:数据看板 / 会话记录 / 知识库

浏览器打开:

| 页面 | 地址 | 看点 |
| --- | --- | --- |
| 聊天 | http://localhost:5173/ | 多轮对话、快捷回复、情感提示 |
| 数据看板 | http://localhost:5173/dashboard | 会话/消息/AI 解决率/转人工率、意图与情感分布 |
| 知识库 | http://localhost:5173/knowledge | 增删改查、语义检索、向量索引状态 |
| 会话记录 | http://localhost:5173/sessions | 列表 + 完整对话回放 |

也可以直接用接口:

```bash
curl -s http://127.0.0.1:8000/api/v1/analytics/summary
curl -s "http://127.0.0.1:8000/api/v1/analytics/sessions?page=1&page_size=5"
```

**讲解词**:

> 前端 4 个页面覆盖了「对话 → 数据 → 知识运维 → 会话回放」的闭环;
> 看板指标直接聚合 MySQL 的 messages/sessions 表,不是静态假数据。

---

## 8. 3 分钟演示流程

| 时间 | 动作 | 一句话讲解 |
| --- | --- | --- |
| 0:00 | 打开聊天页 | 电商售后 + RAG + 6 工具 + LangGraph 多步 Agent |
| 0:30 | 场景 A:查订单 | `agent_mode=multi_step`,`tool_calls` 是证据 |
| 1:10 | 场景 B(方式二):跑两个测试 | 多步 + fallback,全程 Fake ChatModel |
| 1:45 | 场景 C:RAG | 意图 `rag`,Milvus 检索,失败降级 |
| 2:15 | 场景 D:投诉 | 负向情感、安抚、转人工 |
| 2:40 | 看板/知识库 | 数据闭环 + 语义检索 |
| 2:55 | 收尾 | 主动说 T2–T5 的限制和优先级 |

如果面试官时间更短,只演示 A + 看板,然后用一句话讲清 fallback。

---

## 9. 演示禁忌

- 不要展示真实 `LLM_API_KEY`、`.env` 内容或带 Key 的终端历史;
- 不要把自己的真实手机号/地址写进数据库,演示数据必须是虚构种子;
- 不要声称已经实现:
  - 复合任务(查订单 → 取消/退货)——T2 未完成;
  - RAG 引用(citations)——T3 未完成;
  - Recall@3/评测报告——T4 未完成;
  - PII 脱敏 / 限流修复——T5 未完成;
  - SSE 流式输出——未实现。
- 不要连续发 60+ 条消息测试限流:当前限流实现有已知 TTL 缺陷,
  可能把会话卡在 429。

---

## 10. 常见问题排查

### 429 请求过于频繁

当前限流键是 `rate:chat:<session_id>`,可以在演示前清理:

```bash
docker exec -it cs-redis redis-cli DEL "rate:chat:$SESSION_ID"
```

> 注意:`INCR + EXPIRE` 每次请求都会刷新 TTL,这是已知缺陷(T5 修复);
> 演示时不要做高频压测。

### 订单查不到

确认种子数据已写入:

```bash
cd backend
./venv/Scripts/python.exe scripts/init_db.py
```

或直接重启后端(启动时会幂等写入种子数据)。

### Milvus 不健康

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
docker logs cs-milvus --tail 100
```

Milvus 首次启动较慢;即使不健康,RAG 也会降级关键词检索,不影响订单/转人工演示。

### 后端连不上 MySQL/Redis

```bash
docker compose -f docker/docker-compose.dev.yml ps
docker exec cs-mysql mysqladmin ping -uroot -proot_password
docker exec cs-redis redis-cli ping
```

确认 `backend/.env` 中的 `DATABASE_URL` / `REDIS_URL` 与 compose 一致。

### 前端请求失败

- 确认后端在 8000 端口;
- 检查浏览器 Network 面板的 CORS/404;
- 前端开发代理配置见 `frontend/vite.config.ts`。

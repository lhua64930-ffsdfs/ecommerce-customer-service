# 售后智答 · 可复现演示脚本

> 目标:在 5 分钟内展示「多步 Agent / 复合任务 / RAG 引用 / 评测 / 转人工 / 数据闭环」。
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

### 打开前端

前端是原生 HTML/CSS/JS,由后端直接托管,不需要单独启动或安装 Node:

浏览器打开 http://127.0.0.1:8000/ 。

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

> Milvus 为 false 也能演示:RAG 会自动降级关键词检索,订单/复合任务/转人工不受影响。

### 选择 LLM 模式

| 模式 | 配置 | 用途 |
| --- | --- | --- |
| 真实 LLM | `backend/.env` 配置 `LLM_API_KEY=sk-...` | 演示多步 Agent、复合任务的完整主路径 |
| mock | `LLM_API_KEY` 留空,或 `LLM_PROVIDER=mock` | 演示单步离线模式、RAG、转人工与离线可用 |

修改 `.env` 后需要重启后端。

> 演示复合任务与多步订单查询时,建议先配置真实 Key 并冒烟一次,
> 确认模型会按预期调用 `query_order` / `propose_after_sales_action`。未配置 Key 时系统走单步离线模式,
> 订单查询、RAG 引用与转人工仍然可用。

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
  "citations": [],
  "pending_approval": null,
  "run_id": "a1b2c3d4e5f6...",
  "agent_mode": "multi_step"
}
```

**讲解词**:

> 这条请求被识别为 `order_query`,进入 LangGraph:
> 模型节点看到只读工具和售后申请工具,决定调用 `query_order`;
> 工具节点执行后把订单结果回传给模型;模型再生成最终回复。
> 响应里的 `agent_mode=multi_step` 和 `tool_calls` 就是这条链路的证据。
> 订单详情中的手机号与地址已经脱敏。

种子订单:

| 订单号 | 状态 | 用途 |
| --- | --- | --- |
| `ORDER20260401001` | `paid`(已支付,待发货) | 订单查询 / 取消审批 |
| `ORDER20260315001` | `shipped`(已发货) | 物流查询 / 退货转人工 |
| `ORDER20260310005` | `delivered`(已收货) | 退货场景 |
| `ORDER20260320001` | `pending`(待支付,¥99) | 低风险自动执行 |

---

## 3. 场景 B:复合任务(查订单 → 提交取消申请 → 核验 → 审批执行)

一条消息里完成查询与取消**申请**。模型不会直接改订单:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"查订单 ORDER20260401001 然后帮我取消\"}"
```

预期(截取):

```json
{
  "response": "已为您提交取消申请...请在确认卡片中确认",
  "tool_calls": [
    { "tool": "query_order", "success": true },
    { "tool": "propose_after_sales_action", "success": true }
  ],
  "pending_approval": {
    "approval_id": "APV...",
    "action": "cancel",
    "order_no": "ORDER20260401001",
    "summary": "取消订单 ORDER20260401001,退款 ¥2699.00 原路退回",
    "risk_level": "medium",
    "status": "pending",
    "requires_verification": true,
    "requires_human": false
  },
  "agent_mode": "multi_step"
}
```

先核验订单(订单号 + 手机后四位),再确认执行:

```bash
APPROVAL_ID="从响应中复制 pending_approval.approval_id"

curl -s -X POST http://127.0.0.1:8000/api/v1/chat/verify-order \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"order_no\":\"ORDER20260401001\",\"phone_last4\":\"1234\"}"

curl -s -X POST http://127.0.0.1:8000/api/v1/chat/approvals/$APPROVAL_ID/approve \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\"}"
```

预期:

```json
{
  "success": true,
  "status": "executed",
  "result": {
    "success": true,
    "message": "已取消订单 ORDER20260401001,退款将在 1-3 个工作日内原路退回",
    "order_status": "cancelled"
  }
}
```

再次调用 approve 会返回 `already_executed`,不会重复执行。

**讲解词**:

> 模型先调用 `query_order` 读取真实状态,再调用 `propose_after_sales_action`
> 生成审批单;它没有直接写库的权限。
> 策略引擎根据订单状态和金额判定:当前是中风险,需要用户确认;
> 用户确认前还必须用订单号 + 手机后四位核验身份。
> 确认后审批服务重新校验状态并执行取消,全过程写入事项、审批、审计和 Agent 步骤。

已发货订单演示退货转人工(高风险需要客服工号):

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"查订单 ORDER20260315001 然后我要退货\"}"
```

响应中的 `pending_approval.requires_human` 为 `true`;核验后调用 approve 时必须带
`"reviewer": "A001"`,否则返回 `require_human_review`。

低风险自动执行演示(待支付 ¥99 订单,核验后由策略自动取消):

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"取消订单 ORDER20260320001\"}"
```

重复演示前恢复种子订单状态:

```bash
cd backend
./venv/Scripts/python.exe scripts/reset_demo_data.py
```

---

## 4. 场景 C:RAG 2.0(混合检索 + 引用 + 证据闸)

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"商品可以退换吗\"}"
```

预期(截取;无 Key 时 mock 会直接复用知识库答案):

```json
{
  "response": "商品支持退换:7天内可无理由退换货...",
  "intent": {
    "intent_code": "after_sale",
    "handler_type": "rag"
  },
  "citations": [
    {
      "id": 1,
      "category": "退换货政策",
      "question": "商品可以退换吗",
      "score": 0.73
    }
  ],
  "evidence_status": "sufficient",
  "agent_mode": "single_step"
}
```

**讲解词**:

> 这条回答走的是 RAG 2.0:向量 + BM25 混合召回,RRF 融合,
> 本地 bge-reranker 精排;证据置信度和自检通过后才生成回答。
> `citations` 会随响应返回并写入消息元数据,前端展示来源标签,
> 历史回放也能看到引用。

### SSE 流式

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/chat/send-stream \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"商品可以退换吗\"}"
```

事件顺序:`meta` → `citations` → 多个 `delta` → `actions` → `done`。
RAG 路径是逐 token 输出,前端有打字机效果。

### RAG 拒答 + 低置信度池

问一个知识库外的问题:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"你们支持火星配送吗\"}"
```

预期:

```json
{
  "response": "抱歉,我暂时没有找到足够可靠的依据来回答这个问题...",
  "citations": [],
  "evidence_status": "insufficient",
  "agent_mode": "single_step"
}
```

**讲解词**:

> 证据闸会计算四个信号(Top1 分、有效证据数、分差、关键条款命中)。
> 低于阈值不生成,直接兜底;问题会进入低置信度池,后续由知识飞轮处理。
> 这比“检索到一点相关内容就硬答”安全得多。

也可以直接调用检索接口,展示混合检索结果:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/knowledge/search \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"退款多久到账\",\"top_k\":3}"
```

---

## 5. 场景 D:RAG 检索评测

```bash
cd backend
./venv/Scripts/python.exe scripts/evaluate_rag.py --strategy all
```

本机实测输出:

```text
RAG 检索策略对照
策略              Recall@1  Recall@3  Recall@5     MRR@5  检索模式
vector            0.9722    1.0000    1.0000    0.9861  vector=36
bm25              0.8056    0.8889    0.8889    0.8380  bm25=36
hybrid            0.8611    0.9444    1.0000    0.9060  hybrid=36
hybrid_rerank     1.0000    1.0000    1.0000    1.0000  hybrid_rerank=36
```

**讲解词**:

> 评测集是固定的「问题 → 期望知识 id」,共 36 条,覆盖 12 个知识条目;
> 脚本分别计算 Recall@1/3/5 和 MRR@5,并对照四种检索策略。
> BM25 单独召回偏弱,直接与向量 RRF 融合会被拖累;
> 加上本地 CrossEncoder 重排后,36 条全部排到第 1 位。
> 这组对照说明重排是必要的,不是“多此一举”。
> 完整实测结果记录在 [RAG_EVAL.md](RAG_EVAL.md)。

---

## 6. 场景 E:投诉 / 转人工

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

---

## 7. 场景 F:订单归属 / PII 脱敏 / 限流

### 订单归属

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"查订单 ORDER99999999999\"}"
```

预期(无 Key / 单步离线模式时):

```json
{
  "response": "未找到订单号 ORDER99999999999,请确认订单号是否正确",
  "tool_calls": [{ "tool": "query_order", "success": false }],
  "agent_mode": "single_step"
}
```

> 用户身份以会话为准,请求体里的 `user_id` 不会生效;
> `query_order` 查到订单后还会比较 `order.user_id`,不泄露他人订单。

### PII 脱敏

订单详情与订单 API 输出的手机号、姓名、详细地址均已脱敏:

```text
张** 138****6789
北京市朝阳区***
```

原始数据保留在 MySQL,供履约与售后流程使用;对话与 API 只暴露脱敏值。

### 限流

每个会话默认 60 次/分钟,Redis Lua 原子滑动窗口计数。超限返回:

```json
{ "detail": "请求过于频繁,请稍后再试" }
```

响应头带 `Retry-After: 60`。窗口滚动后计数自动过期,可执行限流单测验证:

```bash
cd backend
./venv/Scripts/python.exe -m pytest tests/test_rate_limit.py -v
```

如需手动清理某个会话的限流键:

```bash
docker exec -it cs-redis redis-cli DEL "rate:chat:sw:$SESSION_ID"
```

---

## 8. 场景 G:数据看板 / 会话记录 / 知识库

浏览器打开:

| 页面 | 地址 | 看点 |
| --- | --- | --- |
| 聊天 | http://127.0.0.1:8000/ | 多轮对话、引用标签、售后确认卡片、快捷回复、情感提示 |
| 数据看板 | http://127.0.0.1:8000/dashboard | 会话/消息/AI 解决率/转人工率、意图与情感分布 |
| 知识库 | http://127.0.0.1:8000/knowledge | 增删改查、语义检索、知识飞轮待审队列 |
| RAG 评测 | http://127.0.0.1:8000/rag-eval | 四策略 Recall/MRR、无答案拒答率 |
| 会话记录 | http://127.0.0.1:8000/sessions | 列表 + 完整对话回放(含引用与审批状态) |

也可以直接用接口:

```bash
curl -s http://127.0.0.1:8000/api/v1/analytics/summary
curl -s "http://127.0.0.1:8000/api/v1/analytics/sessions?page=1&page_size=5"
```

**讲解词**:

> 前端 7 个页面覆盖了「对话 → 数据 → 知识运维 → 会话回放」的闭环;
> 看板指标直接聚合 MySQL 的 messages/sessions 表,不是静态假数据。

---

## 8.1 场景 H:知识飞轮 + 指代消解

### 指代消解

先查订单,再用短追问:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"查订单 ORDER20260315001\"}"

curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"那物流呢\"}"
```

**讲解词**:

> 第二句没有订单号,指代消解会结合最近对话补全成完整问法;
> mock 模式用规则补订单号,真实 LLM 模式会改写语义。
> 「谢谢」这类纯社交短语会跳过消解,不会被误补成订单查询。

### 知识飞轮

低置信度问题会进入 `low_confidence_questions`。抽取候选:

```bash
cd backend
./venv/Scripts/python.exe scripts/mine_knowledge.py
```

或直接调接口:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/review/mine

curl -s http://127.0.0.1:8000/api/v1/review/queue
```

拿到 `id` 后人工采纳或弃用:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/review/<id>/approve
curl -s -X POST http://127.0.0.1:8000/api/v1/review/<id>/discard
```

**讲解词**:

> 抽取结果只进 `qa_extraction_staging`,不会自动写知识库;
> 因为模型从聊天里归纳的答案可能带具体订单/地址,也可能只是兜底话术。
> 人工采纳后才写入 `knowledge` 并向量化,弃用只改状态,保留审计。
> 前端「知识库 → 知识飞轮 · 待审队列」可以直接操作。

---

## 8.2 场景 I:文档知识 + 机械校验 + 用户反馈

### 文档切块

```bash
cd backend
./venv/Scripts/python.exe scripts/import_documents.py \
  --file ../knowledge_base/after_sales_manual.md \
  --title 售后处理手册
```

然后用文档里的问题提问:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"content\":\"质量问题怎么退换\"}"
```

预期 citations 中出现 `售后处理手册 > 退货与退款 > 质量问题退换`,
引用可以定位到章节片段。

### 机械校验

回答里的订单号/金额/日期必须来自本轮证据;不一致时重写一次,仍不一致则拒答并落池。
可以在 `low_confidence_questions` 里看到 `source=answer_guard` 的记录。

### 用户反馈

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/feedback \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"question\":\"质量问题怎么退换\",\"rating\":\"down\",\"comment\":\"没解决\"}"
```

👎 会进入低置信度池;👍 只记日志。前端每条机器人消息下方有「有帮助 / 没帮助」。

### 评测看板

浏览器打开 http://127.0.0.1:8000/rag-eval,查看四策略 Recall/MRR 与拒答率;
页面下方「后台作业」可以一键重跑检索评测、拒答评测、挖知识、导入手册,并回显日志。

## 8.3 场景 J:MCP 工具服务 + Langfuse 观测

### MCP 工具服务

```bash
# 终端 1:知识/商品 MCP Server(8001)
cd backend
./venv/Scripts/python.exe -m app.mcp knowledge
curl http://127.0.0.1:8001/health

# 终端 2:订单/售后 MCP Server(8002)
./venv/Scripts/python.exe -m app.mcp aftersales
curl http://127.0.0.1:8002/health

# 终端 3:在 backend/.env 设置 MCP_ENABLED=true 与两个 URL 后重启后端
```

发送一条订单查询,回复的 `tool_calls` / `run_steps` 中应出现
`"transport": "mcp"`。停掉 MCP Server 再发一次,只读工具会回退为
`"transport": "local_fallback"`,业务结果不变;写/申请/转人工则返回
`MCP_RESULT_UNKNOWN`,不会重复执行。

MCP 工具清单默认缓存 60 秒:在 Server 侧新增工具后,等缓存过期即会被后端
发现,无需重启客服系统。首次检索若遇到 MCP Server 加载 Embedding/Reranker,
超时上限由 `MCP_TIMEOUT`(默认 45 秒)控制。

### Langfuse 观测

```bash
# 可选:本地自托管 Langfuse(界面 http://localhost:3000)
docker compose -f docker/docker-compose.langfuse.yml up -d

cd backend
# backend/.env(与 compose headless 初始化的 key 一致)
LANGFUSE_PUBLIC_KEY=pk-lf-after-sales-local
LANGFUSE_SECRET_KEY=sk-lf-after-sales-local
LANGFUSE_BASE_URL=http://127.0.0.1:3000
# 或使用 Langfuse Cloud 的 key 与地址
```

重启后端后发一条聊天 / RAG / 订单请求,在 Langfuse 中可看到:

- trace 名称 `after_sales_chat` / `after_sales_stream_chat` 与请求输入;
- `session_id`、`user_id`、tags 与请求耗时;
- LangGraph 模型节点、工具节点的 span(多步路径);
- LLM generation 的模型、token、输入输出与延迟(需配置真实 `LLM_API_KEY`;
  mock 模式下至少能看到根 span)。

未配置三项时所有观测调用 no-op,日志不会出现 Langfuse 初始化信息,
聊天与审批链路不受影响。

---

## 8.4 场景 K:认证 / 中断恢复 / 保留期

### 认证与 RBAC

```bash
# backend/.env: AUTH_ENABLED=true, JWT_SECRET_KEY 至少 32 字节
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_admin","password":"admin123"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -s http://127.0.0.1:8000/api/v1/knowledge/list \
  -H "Authorization: Bearer $TOKEN"
```

不登录访问管理接口返回 401;顾客 token 访问 admin 接口返回 403。

### 订单选择 interrupt / resume

```bash
# 发一条没有订单号的取消请求
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/send \
  -H "Content-Type: application/json" \
  -d '{"session_id":"'$SESSION_ID'","content":"帮我取消订单"}'
# 返回 interrupt.orders + thread_id

curl -s -X POST http://127.0.0.1:8000/api/v1/chat/resume \
  -H "Content-Type: application/json" \
  -d '{"session_id":"'$SESSION_ID'","thread_id":"...","resume":{"type":"select_order","order_no":"ORDER20260401001"}}'
```

resume 后只生成一次售后申请;真正执行仍走核验 + 审批接口。

工单创建同样先暂停,确认后才执行:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/resume \
  -H "Content-Type: application/json" \
  -d '{"session_id":"'$SESSION_ID'","thread_id":"...","resume":{"type":"confirm_ticket","confirmed":true}}'
```

### 保留期试算

```bash
cd backend
./venv/Scripts/python.exe scripts/retention_cleanup.py --dry-run
```

默认 `RETENTION_ENABLED=false`,不会删除任何数据;打开后按
`RETENTION_DAYS_*` 分批清理。

---

## 9. 5 分钟演示流程

| 时间 | 动作 | 一句话讲解 |
| --- | --- | --- |
| 0:00 | 打开聊天页 | 电商售后 + RAG + 只读工具 + 售后申请 + LangGraph 多步 Agent |
| 0:30 | 场景 A:查订单 | `agent_mode=multi_step`,`tool_calls` 是证据 |
| 1:10 | 场景 B:查订单后取消 | 模型只提申请;核验后确认才执行,幂等 |
| 1:50 | 场景 C:RAG 2.0 + SSE | 混合检索 + 重排 + 引用 + 证据闸 |
| 2:20 | 场景 D:四策略评测 | Recall@1/3/5 可复现,重排到 1.0 |
| 2:50 | 场景 E:投诉 | 负向情感、安抚、转人工 |
| 3:20 | 看板/知识库/知识飞轮 | 数据闭环 + 引用留存 + 待审队列 |
| 4:00 | 场景 F:PII / 限流 | 安全工程细节 |
| 4:20 | 场景 J:MCP + Langfuse | 工具协议服务化 + trace 可观测 |
| 4:40 | 收尾 | 架构取舍与扩展方向 |

如果面试官时间更短,只演示 A + B + C + 知识飞轮,然后用一句话讲清评测。

---

## 10. 演示注意事项

- 不要展示真实 `LLM_API_KEY`、`.env` 内容或带 Key 的终端历史;
- 不要把自己的真实手机号/地址写进数据库,演示数据必须是虚构种子;
- 复合任务需要核验订单并确认后才真实修改订单状态;重复演示前执行 `reset_demo_data.py`;
- 首次启动会下载 bge-reranker(约 1GB),演示前先预热一次 RAG 问答;
- 从旧 collection 升级时,先跑 `init_vector_db.py --rebuild`,否则 BM25 会降级;
- 知识飞轮抽取需要真实 LLM;mock 模式返回 0 条,可演示队列 UI 与人工审核流程;
- 高频压测会触发限流;需要时等待窗口滚动或删除对应 Redis key;
- 截图/GIF 使用仓库脚本生成,确保界面与代码版本一致。

---

## 11. 常见问题排查

### 429 请求过于频繁

限流键是 `rate:chat:sw:<session_id>`,等待 60 秒窗口滚动,或:

```bash
docker exec -it cs-redis redis-cli DEL "rate:chat:sw:$SESSION_ID"
```

### 订单查不到

确认种子数据已写入:

```bash
cd backend
./venv/Scripts/python.exe scripts/init_db.py
```

或直接重启后端(启动时会幂等写入种子数据)。

### 复合任务没有取消

- 先看响应里有没有 `pending_approval`:有申请单说明链路正常,只是还没确认;
- 未核验订单时调用 approve 会返回 `require_verification`,先调用 `verify-order`;
- 高风险申请需要 `reviewer` 客服工号,否则返回 `require_human_review`;
- 若订单已发货,策略会拒绝取消并建议退货,这是预期行为。

### RAG 总是拒答

- 确认知识库有对应条目,且 collection 已按 BM25 schema 重建:
  `python scripts/init_vector_db.py --rebuild`;
- 查看 `/health` 的 `milvus` 是否为 true;
- 证据置信度阈值默认 0.5,可在 `.env` 调整 `RAG_EVIDENCE_THRESHOLD`;
- 低置信度问题会进入 `low_confidence_questions`,可在知识飞轮队列查看。

### SSE 没有流式效果

- 确认调用的是 `/api/v1/chat/send-stream`,不是 `/send`;
- 如果经过 Nginx,确认没有缓冲(`X-Accel-Buffering: no` 已设置);
- 浏览器 Network 里应看到 `text/event-stream`,事件按 `meta/delta/...` 逐步出现。

### Milvus 不健康

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
docker logs cs-milvus --tail 100
```

Milvus 首次启动较慢;即使不健康,RAG 也会降级关键词检索,不影响订单/复合任务/转人工演示。

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
- 页面脚本位于 `frontend/static/js/`,静态资源挂在 `/static` 下。

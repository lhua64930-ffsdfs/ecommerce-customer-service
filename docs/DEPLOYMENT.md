# 部署指南

## 1. 环境要求

| 项 | 建议 |
| --- | --- |
| 操作系统 | Windows 10/11、Ubuntu 20.04+、macOS 12+ |
| Docker | Docker Desktop 4.x+(含 Compose v2) |
| 内存 | 8 GB 起,建议 16 GB(Milvus + 向量模型) |
| 磁盘 | 10 GB 可用(镜像 + 模型缓存) |
| Python | 3.10+(开发模式,建议 3.12/3.13) |
| Node.js | 18+(开发模式,建议 20/22) |

## 2. 端口

| 服务 | 端口 |
| --- | --- |
| Nginx(生产入口) | 8080(Windows 默认;Linux 可改回 80) |
| 后端 API | 8000 |
| MCP 工具服务 | 8001 知识/商品、8002 订单/售后(仅内部,不映射宿主机) |
| Langfuse Web(可选自托管) | 3000 |
| 前端开发服务器 | 5173 |
| MySQL | 3306 |
| Redis | 6379 |
| Milvus gRPC | 19530 |
| Milvus 健康检查 | 9091 |

## 3. 开发部署

```bash
# 1) 基础设施
docker compose -f docker/docker-compose.dev.yml up -d

# 2) 后端
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
# 需要跑测试/合成演示 GIF 时:
# pip install -r requirements-dev.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 3) 前端(另开终端)
cd frontend
npm install
npm run dev

# 4) 可选:MCP 工具服务(另开两个终端)
cd backend
venv\Scripts\activate
python -m app.mcp knowledge     # 8001
python -m app.mcp aftersales    # 8002,另开终端
# 然后在 backend/.env 设置 MCP_ENABLED=true,并重启后端
```

访问 http://localhost:5173。健康检查:
http://127.0.0.1:8001/health、http://127.0.0.1:8002/health。

## 4. 生产部署(Docker)

密钥只从环境变量注入,不要写入 `.env` 或 compose 文件。
若 Key 已存放在 `DEEPSEEK_API_KEY`,启动时映射为 `LLM_API_KEY`:

```bash
# Git Bash / Linux / macOS
LLM_API_KEY="$DEEPSEEK_API_KEY" docker compose -f docker/docker-compose.yml up -d --build

# PowerShell
# $env:LLM_API_KEY = $env:DEEPSEEK_API_KEY
# docker compose -f docker/docker-compose.yml up -d --build
```

未提供 Key 时自动使用 mock 模式。

访问 http://localhost:8080,API 文档 http://localhost:8080/docs。
Windows 默认禁止绑定 80 端口,因此映射为 8080;Linux 可将 compose 中 nginx 端口改回 `"80:80"`。

编排会同时启动 `cs-mcp-knowledge`(8001)与 `cs-mcp-aftersales`(8002);
后端分别通过 `http://mcp-knowledge:8001/mcp`、`http://mcp-aftersales:8002/mcp`
调用,端口不映射到宿主机。单台不可用时只跳过该台工具/回退进程内实现。

首次启动后端会:

1. 连接 MySQL 建表;
2. 写入演示数据与售后策略规则;
3. 下载 BGE 向量模型(约 100MB)与 bge-reranker(约 1GB,缓存在 `hf_cache` 卷),
   并向量化知识。

启动时间首次约 3-8 分钟(取决于模型下载),后续约 30 秒。

> 从旧版本升级时,如果 Milvus collection 没有 BM25 `sparse` 字段,
> 需要重建一次:
>
> ```bash
> cd backend
> python scripts/init_vector_db.py --rebuild
> ```

## 5. 环境变量

后端读取 `backend/.env`(开发)或 compose `environment`(容器)。

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `DATABASE_URL` | MySQL 异步连接串 | 本地 cs_user/cs_password |
| `REDIS_URL` | Redis 连接串;留空=不启用(限流走内存、转人工只落 DB) | 空 |
| `LLM_PROVIDER` | `deepseek` / `openai` / `mock` | `deepseek` |
| `LLM_API_KEY` | LLM 密钥;为空自动 mock | 空 |
| `LLM_API_BASE` | OpenAI 兼容地址 | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 模型名 | `deepseek-chat` |
| `EMBEDDING_PROVIDER` | `local` / `openai`(远程 OpenAI 兼容) | `local` |
| `EMBEDDING_API_BASE` | 远程 embedding 地址 | 空 |
| `EMBEDDING_API_KEY` | 远程 embedding Key | 空 |
| `EMBEDDING_MODEL` | 本地/远程向量模型 | `BAAI/bge-small-zh-v1.5` |
| `EMBEDDING_DIM` | 向量维度 | `512` |
| `MILVUS_URI` | Milvus 地址 | `http://127.0.0.1:19530` |
| `MILVUS_COLLECTION` | 集合名 | `knowledge_base` |
| `RAG_VECTOR_RETRY_SECONDS` | 向量/BM25 检索失败后的降级冷却秒数 | `30` |
| `RAG_RETRIEVAL_STRATEGY` | `vector / bm25 / hybrid / hybrid_rerank` | `hybrid_rerank` |
| `RAG_RECALL_TOP_K` | 混合召回候选数 | `20` |
| `RAG_RERANK_TOP_K` | 重排后返回条数 | `5` |
| `RAG_RERANK_MODEL` | 本地重排模型 | `BAAI/bge-reranker-base` |
| `RAG_RERANK_ENABLED` | 是否启用重排 | `true` |
| `RERANK_PROVIDER` | `local` / `openai`(SiliconFlow) | `local` |
| `RERANK_API_BASE` | 远程 rerank 地址 | 空 |
| `RERANK_API_KEY` | 远程 rerank Key | 空 |
| `RAG_EVIDENCE_THRESHOLD` | 证据置信度阈值 | `0.5` |
| `RAG_SELF_CHECK` | 生成前 LLM 自检 | `true` |
| `RAG_SUBQUERY_SPLIT` | 一问多意图拆子句 | `true` |
| `RAG_QUERY_EXPANSION` | Query 扩写 | `true` |
| `HF_ENDPOINT` | HuggingFace 镜像 | `https://hf-mirror.com` |
| `MCP_ENABLED` | Agent 工具是否走独立 MCP Server | `false`(Docker 内默认 `true`) |
| `MCP_KNOWLEDGE_URL` | 知识/商品 MCP Server 地址 | `http://127.0.0.1:8001/mcp` |
| `MCP_AFTERSALES_URL` | 订单/售后 MCP Server 地址 | `http://127.0.0.1:8002/mcp` |
| `MCP_SERVER_HOST` | MCP Server 监听地址 | `127.0.0.1`(Docker 内 `0.0.0.0`) |
| `MCP_KNOWLEDGE_PORT` | 知识/商品 Server 端口 | `8001` |
| `MCP_AFTERSALES_PORT` | 订单/售后 Server 端口 | `8002` |
| `MCP_TIMEOUT` | 单次 MCP 调用超时(秒,含首次模型加载) | `45` |
| `MCP_DISCOVERY_TIMEOUT` | 拉取工具清单超时(秒) | `5` |
| `MCP_TOOL_CACHE_TTL` | 工具清单缓存时间(秒) | `60` |
| `MCP_DYNAMIC_TOOLS` | 是否动态拉取 Server 工具清单 | `true` |
| `MCP_FALLBACK_TO_LOCAL` | 幂等只读工具传输失败时回退本地 | `true` |
| `LANGFUSE_PUBLIC_KEY` | 可选 Langfuse 公钥 | 空(不启用) |
| `LANGFUSE_SECRET_KEY` | 可选 Langfuse 私钥 | 空(不启用) |
| `LANGFUSE_BASE_URL` | Langfuse Cloud 或自建实例地址 | 空(不启用) |
| `LANGFUSE_TRACING_ENVIRONMENT` | Langfuse 环境标签 | `development` |
| `RATE_LIMIT_ENABLED` | 是否启用限流 | `true` |
| `RATE_LIMIT_PER_MINUTE` | 每会话每分钟消息上限(滑动窗口) | `60` |
| `RATE_LIMIT_BURST` | 突发额度(容量 = 每分钟额度 + burst) | `0` |
| `RATE_LIMIT_BACKEND` | `auto` / `memory` / `redis` | `auto` |
| `RATE_LIMIT_MAX_KEYS` | 内存限流最大 key 数,超限清理过期窗口 | `10000` |
| `RATE_LIMIT_MIDDLEWARE_ENABLED` | 可选按客户端 IP 的全局限流中间件 | `false` |
| `REDIS_RETRY_COOLDOWN_SECONDS` | Redis 故障降级冷却秒数 | `30` |
| `CIRCUIT_BREAKER_ENABLED` | chat/embed/rerank 熔断开关 | `true` |
| `CIRCUIT_FAILURE_THRESHOLD` | 熔断失败阈值 | `5` |
| `CIRCUIT_RECOVERY_SECONDS` | 熔断冷却/半开探测秒数 | `30` |
| `AUTH_ENABLED` | 是否保护 `/api/v1/*` | `false` |
| `REGISTRATION_ENABLED` | 是否开放注册 | `true` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 启动时幂等创建管理员(可选) | 空 |
| `SMS_PROVIDER` | 短信通道;`console` 只写日志 | `console` |
| `SMS_CODE_TTL_SECONDS` | 短信验证码有效期 | `300` |
| `SMS_RESEND_SECONDS` | 短信重发间隔 | `60` |
| `SMS_DEBUG_RETURN_CODE` | 本地调试时在响应返回验证码 | `false` |
| `QR_LOGIN_TTL_SECONDS` | 扫码票据有效期 | `120` |
| `JWT_SECRET_KEY` | JWT 签名密钥;开启鉴权时至少 32 字节 | 占位值 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | token 有效期 | `1440` |
| `GRAPH_ORCHESTRATOR_ENABLED` | 是否走确定性路由图(失败回退旧链路) | `true` |
| `CHECKPOINTER_BACKEND` | `sqlite` / `postgres` / `memory` / `none` | `sqlite` |
| `CHECKPOINTER_DB_PATH` | SQLite checkpoint 路径 | `data/checkpoints.sqlite` |
| `CHECKPOINTER_POSTGRES_URL` | 可选 Postgres checkpointer DSN | 空 |
| `CHECKPOINT_TTL_HOURS` | checkpoint 清理阈值 | `24` |
| `SKILLS_ENABLED` | 是否按意图加载 `skills/*.md` | `false` |
| `SKILLS_DIR` | 技能包目录 | `skills` |
| `SUMMARY_TRIGGER_MESSAGES` | 摘要触发的新消息数 | `16` |
| `SEMANTIC_HISTORY_ENABLED` | 是否补捞语义相关历史 | `false` |
| `SEMANTIC_HISTORY_TOP_K` | 语义历史条数 | `3` |
| `RETENTION_ENABLED` | 是否启用数据保留期清理 | `false` |
| `RETENTION_DAYS_*` | 各表保留天数,0=永久 | `0` |
| `RETENTION_BATCH_SIZE` | 清理批大小 | `500` |

> `AUTH_ENABLED=true` 时前端会跳转 `/login`,登录后自动带 Bearer token;
> 演示账号 `demo_admin/admin123`、`demo_customer/demo123`。
>
> Langfuse 为可选观测:三项都配置后启用,记录 LangGraph 节点、LLM generation
> 与意图标签;未配置时完全 no-op,不影响主流程。自托管可直接使用
> `docker/docker-compose.langfuse.yml`(见 5.1),或使用 Langfuse Cloud。
>
> MCP 服务化默认关闭(Docker 编排中默认开启并启动两个 MCP 容器)。本地未启动
> MCP Server 时,`MCP_ENABLED=true` 也不会阻断业务:幂等只读工具会回退进程内
> 实现;写/申请/转人工返回 `MCP_RESULT_UNKNOWN`,不会重复执行。

### 5.1 可选:自托管 Langfuse

```bash
docker compose -f docker/docker-compose.langfuse.yml up -d
# 国内/镜像源:
DOCKER_MIRROR=docker.1ms.run \
MINIO_IMAGE=docker.1ms.run/chainguard/minio:latest \
  docker compose -f docker/docker-compose.langfuse.yml up -d
# 界面:http://localhost:3000
# 默认账号:admin@after-sales.local / after-sales-123
```

本机已实测 Web 健康检查与真实 trace 写入;Docker Desktop 若配置了
`127.0.0.1:7897` 代理,需确保该代理运行或清空代理后再拉镜像。

- 对象存储使用 Chainguard MinIO 镜像,规避官方 MinIO 镜像停止分发的问题;
- compose 通过 `LANGFUSE_INIT_*` headless 初始化组织/项目,默认 key:
  `pk-lf-after-sales-local` / `sk-lf-after-sales-local`;
- 后端 `.env`:

  ```bash
  LANGFUSE_PUBLIC_KEY=pk-lf-after-sales-local
  LANGFUSE_SECRET_KEY=sk-lf-after-sales-local
  LANGFUSE_BASE_URL=http://127.0.0.1:3000
  ```

- 只暴露 Langfuse Web(3000);Postgres / ClickHouse / Redis / MinIO 仅在容器网络内;
- 停止:`docker compose -f docker/docker-compose.langfuse.yml down`;
  清空数据加 `-v`;
- 对外部署前替换 compose 内所有默认密钥(`NEXTAUTH_SECRET`、`SALT`、
  `ENCRYPTION_KEY`、Postgres/MinIO/Redis 密码)。

## 6. 常见问题

### Docker Hub 拉取超时

现象:`dialing registry-1.docker.io ... timeout`。

处理:开启代理并让 Docker Desktop 使用该代理(Settings → Resources → Proxies),
或在 Docker Desktop 配置国内镜像加速。

### MinIO 镜像不可用

现象:`pull access denied for minio/minio`。

原因:MinIO 官方自 2025 年起停止在公共仓库分发镜像。
本项目已改为 **Milvus 本地存储模式**(`COMMON_STORAGETYPE=local`),不再依赖 MinIO。
如必须使用对象存储,可自建 MinIO 或使用云 S3,并在 Milvus 配置中切换。

### BGE 模型下载失败

现象:`Embedding 模型加载失败` / HuggingFace 连接超时。

处理:

1. 确认 `HF_ENDPOINT=https://hf-mirror.com`;
2. 手动下载模型到缓存目录;
3. 或设置 `EMBEDDING_MODEL` 为本地路径。

模型下载失败不阻塞系统:知识检索自动降级为关键词匹配。

### 后端启动但 /health 显示 milvus=false

- 检查 `docker ps` 中 `cs-milvus` 是否 healthy;
- Milvus 首次启动需 60-90 秒;
- 检查 19530 端口是否被占用。

### MCP 工具调用回退本地

现象:日志出现 `MCP 工具 ... 调用失败,回退本地实现`。

处理:

1. 检查 `cs-mcp-knowledge` / `cs-mcp-aftersales` 是否 healthy:
   `docker logs -f cs-mcp-knowledge`、`docker logs -f cs-mcp-aftersales`;
2. 本地开发确认已运行 `python -m app.mcp knowledge` 与
   `python -m app.mcp aftersales`,且两个 URL 指向 8001/8002;
3. `curl http://127.0.0.1:8001/health` 与 `:8002/health` 应返回
   `{"status":"ok"}`;
4. 不需要 MCP 时设置 `MCP_ENABLED=false` 或 `MCP_FALLBACK_TO_LOCAL=true`。

### Langfuse 看不到 trace

1. 确认 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_BASE_URL` 三项都已配置;
2. 容器内能否访问 `LANGFUSE_BASE_URL`;
3. 日志中应出现 `Langfuse 观测已启用`;
4. SDK 批量上报有延迟,可在应用关闭后等待 flush,或查看
   `LANGFUSE_FLUSH_INTERVAL` 配置;
5. 自托管栈检查:`docker compose -f docker/docker-compose.langfuse.yml ps`
   中 web/worker/minio/clickhouse/postgres/redis 是否 healthy,
   `curl http://localhost:3000/api/public/health` 是否返回 200,
   并确认 `.env` 的 key 与 compose 的 `LANGFUSE_INIT_PROJECT_*` 一致。

### MySQL 连接失败

- 确认容器 healthy:`docker exec cs-mysql mysqladmin ping -uroot -proot_password`;
- 确认 `.env` 中 `DATABASE_URL` 的账号密码与 compose 一致;
- 首次启动 MySQL 初始化约 20-30 秒。

### 端口被占用

```bash
netstat -ano | findstr :8000
```

修改启动参数或 compose 端口映射即可。

### 知识库新增后检索不到

- 查看接口返回的 `vector_id` 是否为 `已索引`;
- 执行 `python scripts/init_vector_db.py` 重建向量;
- 检查 Milvus 是否健康。

## 7. 运维命令

```bash
# 查看状态
docker compose -f docker/docker-compose.yml ps

# 查看后端日志
docker logs -f cs-backend

# 重启后端
docker compose -f docker/docker-compose.yml restart backend

# 停止并保留数据
docker compose -f docker/docker-compose.yml down

# 停止并删除数据(谨慎)
docker compose -f docker/docker-compose.yml down -v
```

## 8. 安全建议

- 修改默认数据库密码与示例密钥;
- 生产环境启用 HTTPS(Nginx + 证书);
- 限制 MySQL/Redis/Milvus 端口不对外暴露;
- 对 LLM Key 使用环境变量或密钥管理服务,不要提交到仓库;
- 按部署环境收紧 `ALLOWED_ORIGINS` 白名单。

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
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 3) 前端(另开终端)
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173。

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

首次启动后端会:

1. 连接 MySQL 建表;
2. 写入演示数据;
3. 下载 BGE 向量模型(约 100MB,缓存在 `hf_cache` 卷)并向量化知识。

启动时间首次约 2-5 分钟,后续约 30 秒。

## 5. 环境变量

后端读取 `backend/.env`(开发)或 compose `environment`(容器)。

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `DATABASE_URL` | MySQL 异步连接串 | 本地 cs_user/cs_password |
| `REDIS_URL` | Redis 连接串 | `redis://127.0.0.1:6379/0` |
| `LLM_PROVIDER` | `deepseek` / `openai` / `mock` | `deepseek` |
| `LLM_API_KEY` | LLM 密钥;为空自动 mock | 空 |
| `LLM_API_BASE` | OpenAI 兼容地址 | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 模型名 | `deepseek-chat` |
| `EMBEDDING_MODEL` | 本地向量模型 | `BAAI/bge-small-zh-v1.5` |
| `EMBEDDING_DIM` | 向量维度 | `512` |
| `MILVUS_URI` | Milvus 地址 | `http://127.0.0.1:19530` |
| `MILVUS_COLLECTION` | 集合名 | `knowledge_base` |
| `HF_ENDPOINT` | HuggingFace 镜像 | `https://hf-mirror.com` |
| `JWT_SECRET_KEY` | JWT 密钥(预留) | 需修改 |
| `RATE_LIMIT_PER_MINUTE` | 每会话每分钟消息上限 | `60` |

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

- 修改默认数据库密码与 `JWT_SECRET_KEY`;
- 生产环境启用 HTTPS(Nginx + 证书);
- 为管理接口补充登录鉴权与权限控制;
- 限制 MySQL/Redis/Milvus 端口不对外暴露;
- 对 LLM Key 使用环境变量或密钥管理服务,不要提交到仓库。

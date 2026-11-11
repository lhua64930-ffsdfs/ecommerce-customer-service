"""应用配置。

统一从 backend/.env 读取,所有模块通过 `settings` 单例访问。
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置项(字段名与环境变量名一致,大小写不敏感)。"""

    # ---------- 应用 ----------
    PROJECT_NAME: str = "售后智答"
    VERSION: str = "1.0.0"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

    # ---------- 数据库 ----------
    DATABASE_URL: str = (
        "mysql+aiomysql://cs_user:cs_password@127.0.0.1:3306/"
        "customer_service?charset=utf8mb4"
    )
    # 留空=不启用 Redis(限流走进程内存,转人工队列退化为 DB 审计记录)
    REDIS_URL: str = ""
    REDIS_RETRY_COOLDOWN_SECONDS: int = 30

    # ---------- LLM ----------
    LLM_PROVIDER: str = "deepseek"          # deepseek | openai | mock
    LLM_API_KEY: str = ""
    LLM_API_BASE: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-chat"
    LLM_MAX_TOKENS: int = 2000
    LLM_TEMPERATURE: float = 0.7
    LLM_TIMEOUT: float = 60.0
    LLM_MAX_CONCURRENCY: int = 8            # 同时进行的 LLM 请求上限

    # ---------- Embedding ----------
    EMBEDDING_PROVIDER: str = "local"       # local | openai(SiliconFlow 兼容)
    EMBEDDING_API_BASE: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "BAAI/bge-small-zh-v1.5"
    EMBEDDING_DIM: int = 512
    HF_ENDPOINT: str = "https://hf-mirror.com"

    # ---------- Milvus ----------
    MILVUS_URI: str = "http://127.0.0.1:19530"
    MILVUS_COLLECTION: str = "knowledge_base"
    # 向量检索失败后的降级冷却时间,避免每个请求都重试已宕机的 Milvus
    RAG_VECTOR_RETRY_SECONDS: int = 30

    # ---------- RAG 2.0 检索 ----------
    # vector | bm25 | hybrid | hybrid_rerank
    RAG_RETRIEVAL_STRATEGY: str = "hybrid_rerank"
    RAG_RECALL_TOP_K: int = 20
    RAG_RERANK_TOP_K: int = 5
    RAG_RERANK_MODEL: str = "BAAI/bge-reranker-base"
    RAG_RERANK_ENABLED: bool = True
    # local=本地 CrossEncoder;openai=OpenAI 兼容 rerank API(如 SiliconFlow)
    RERANK_PROVIDER: str = "local"
    RERANK_API_BASE: str = ""
    RERANK_API_KEY: str = ""
    RAG_EVIDENCE_THRESHOLD: float = 0.5
    RAG_SELF_CHECK: bool = True
    RAG_SUBQUERY_SPLIT: bool = True
    RAG_QUERY_EXPANSION: bool = True

    # ---------- 安全 ----------
    # false=本地演示兼容,不做鉴权;true=保护 /api/v1/*,登录/注册放行
    AUTH_ENABLED: bool = False
    REGISTRATION_ENABLED: bool = True
    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD: str = ""
    # 短信/扫码登录(console 仅写日志,便于本地演示)
    SMS_PROVIDER: str = "console"
    SMS_CODE_TTL_SECONDS: int = 300
    SMS_RESEND_SECONDS: int = 60
    SMS_DEBUG_RETURN_CODE: bool = False
    QR_LOGIN_TTL_SECONDS: int = 120
    JWT_SECRET_KEY: str = "please-change-this-secret-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # ---------- 限流 / 会话 ----------
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60
    # 突发额度:每分钟基础额度 + burst
    RATE_LIMIT_BURST: int = 0
    # auto=有 REDIS_URL 用 Redis,否则内存;memory=强制内存;redis=强制 Redis
    RATE_LIMIT_BACKEND: Literal["auto", "memory", "redis"] = "auto"
    RATE_LIMIT_MAX_KEYS: int = 10000
    # 可选:按客户端 IP 的全局中间件(聊天接口已有按会话限流)
    RATE_LIMIT_MIDDLEWARE_ENABLED: bool = False
    SESSION_TTL_SECONDS: int = 60 * 60 * 24

    # ---------- 上游熔断 ----------
    CIRCUIT_BREAKER_ENABLED: bool = True
    CIRCUIT_FAILURE_THRESHOLD: int = 5
    CIRCUIT_RECOVERY_SECONDS: int = 30

    # ---------- 确定性路由图 ----------
    GRAPH_ORCHESTRATOR_ENABLED: bool = True

    # ---------- Skills 运维指令包 ----------
    SKILLS_ENABLED: bool = False
    SKILLS_DIR: str = "skills"
    SKILLS_MAX_CHARS: int = 1500

    # ---------- LangGraph Checkpointer ----------
    # none=不持久化;memory=测试/单机;sqlite=本地默认;postgres=多副本(需额外 DSN)
    CHECKPOINTER_BACKEND: Literal["none", "memory", "sqlite", "postgres"] = "sqlite"
    CHECKPOINTER_DB_PATH: str = "data/checkpoints.sqlite"
    CHECKPOINTER_POSTGRES_URL: str = ""
    CHECKPOINT_TTL_HOURS: int = 24

    # ---------- 会话上下文(摘要 + 语义历史) ----------
    SUMMARY_TRIGGER_MESSAGES: int = 16
    SEMANTIC_HISTORY_ENABLED: bool = False
    SEMANTIC_HISTORY_TOP_K: int = 3
    SEMANTIC_HISTORY_MAX_CANDIDATES: int = 100
    SEMANTIC_HISTORY_MIN_SCORE: float = 0.35
    SEMANTIC_HISTORY_MAX_CHARS: int = 600

    # ---------- 数据保留期(0=永久保留) ----------
    RETENTION_ENABLED: bool = False
    RETENTION_DAYS_MESSAGES: int = 0
    RETENTION_DAYS_SESSIONS: int = 0
    RETENTION_DAYS_LOW_CONF: int = 0
    RETENTION_DAYS_AGENT_RUNS: int = 0
    RETENTION_DAYS_AUDIT: int = 0
    RETENTION_BATCH_SIZE: int = 500
    RETENTION_KEEP_PENDING_LOW_CONF: bool = True

    # ---------- MCP 工具服务化 ----------
    # 开启后 Agent 工具通过独立 MCP Server 调用;连接失败可回退进程内工具
    MCP_ENABLED: bool = False
    # 多 Server:知识/商品、订单/售后分别部署
    MCP_KNOWLEDGE_URL: str = "http://127.0.0.1:8001/mcp"
    MCP_AFTERSALES_URL: str = "http://127.0.0.1:8002/mcp"
    # 本地默认只监听回环;容器内通过 MCP_SERVER_HOST=0.0.0.0 暴露给同网络服务
    MCP_SERVER_HOST: str = "127.0.0.1"
    MCP_KNOWLEDGE_PORT: int = 8001
    MCP_AFTERSALES_PORT: int = 8002
    # 含 MCP Server 首次加载 Embedding/Reranker 的时间
    MCP_TIMEOUT: float = 45.0
    MCP_DISCOVERY_TIMEOUT: float = 5.0
    MCP_TOOL_CACHE_TTL: float = 60.0
    # 动态拉取 Server 工具清单(Server 加工具无需重启后端)
    MCP_DYNAMIC_TOOLS: bool = True
    MCP_FALLBACK_TO_LOCAL: bool = True

    # ---------- 可观测(可选) ----------
    # 配置三项后启用 Langfuse;未配置时完全 no-op
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_BASE_URL: str = ""
    LANGFUSE_TRACING_ENVIRONMENT: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置工厂(pydantic 单例)。"""
    return Settings()


settings = get_settings()

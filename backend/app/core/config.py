"""应用配置。

统一从 backend/.env 读取,所有模块通过 `settings` 单例访问。
"""
from functools import lru_cache

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
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

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
    EMBEDDING_PROVIDER: str = "local"       # local | openai
    EMBEDDING_MODEL: str = "BAAI/bge-small-zh-v1.5"
    EMBEDDING_DIM: int = 512
    HF_ENDPOINT: str = "https://hf-mirror.com"

    # ---------- Milvus ----------
    MILVUS_URI: str = "http://127.0.0.1:19530"
    MILVUS_COLLECTION: str = "knowledge_base"

    # ---------- 安全 ----------
    JWT_SECRET_KEY: str = "please-change-this-secret-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # ---------- 限流 / 会话 ----------
    RATE_LIMIT_PER_MINUTE: int = 60
    SESSION_TTL_SECONDS: int = 60 * 60 * 24

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

"""FastAPI 依赖注入。"""
from app.core.database import get_db

__all__ = ["get_db"]

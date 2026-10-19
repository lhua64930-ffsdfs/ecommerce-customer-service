"""日志工具(基于 loguru)。

用法:
    from app.utils.logger import logger
    logger.info("...")
"""
import sys
from pathlib import Path

from loguru import logger as _logger

# 项目根目录: backend/app/utils/logger.py -> parents[3] = 项目根
LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = _logger

# 控制台输出
logger.remove()
logger.add(
    sys.stdout,
    level="DEBUG",
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    ),
    colorize=True,
)

# 文件输出(按大小轮转,保留 7 天)
logger.add(
    LOG_DIR / "app.log",
    level="INFO",
    rotation="10 MB",
    retention="7 days",
    encoding="utf-8",
    enqueue=True,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} - {message}",
)


def setup_logger(name: str = "app"):
    """兼容文档中 `setup_logger(__name__)` 的调用方式。"""
    return logger.bind(module=name)

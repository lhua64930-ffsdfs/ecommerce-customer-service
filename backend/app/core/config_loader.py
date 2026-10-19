"""业务配置文件加载器(YAML)。

与 `.env` 的分工:
- .env:环境相关(密钥、连接串),不进 Git;
- config/*.yaml:业务配置(人设、检索参数、转人工策略),可提交共享。

加载失败时返回空字典并记录日志,不影响应用启动。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.utils.logger import logger

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


@lru_cache(maxsize=16)
def load_config(name: str) -> dict[str, Any]:
    """按名称加载 config/<name>.yaml(带缓存)。"""
    path = CONFIG_DIR / f"{name}.yaml"
    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        logger.warning("配置文件不存在: {}", path)
    except yaml.YAMLError as exc:
        logger.error("配置文件格式错误 [{}]: {}", path, exc)
    return {}

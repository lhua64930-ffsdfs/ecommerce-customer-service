"""短信发送:console 模式只写日志,便于本地/测试环境。"""
from __future__ import annotations

from app.core.config import settings
from app.utils.logger import logger


class SmsError(RuntimeError):
    """短信发送失败。"""


async def send_login_code(phone: str, code: str) -> None:
    provider = (settings.SMS_PROVIDER or "console").lower()
    if provider == "console":
        logger.info("SMS login code phone={} code={}", phone, code)
        return
    raise SmsError(f"不支持的 SMS_PROVIDER: {settings.SMS_PROVIDER}")

"""PII 脱敏工具:手机号、收件人姓名、收货地址。

用于把订单工具输出与订单 API 响应转成可展示的脱敏形式。
原始数据仍保留在数据库中,供履约与售后流程使用。
"""
from __future__ import annotations

from typing import Any

MASK = "***"


def mask_phone(phone: str | None) -> str:
    """手机号脱敏:保留前 3 位与后 4 位,例如 ``138****6789``。"""
    value = str(phone or "").strip()
    if not value:
        return ""
    if len(value) >= 8:
        return f"{value[:3]}{'*' * (len(value) - 7)}{value[-4:]}"
    if len(value) >= 3:
        return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"
    return "*" * len(value)


def mask_name(name: str | None) -> str:
    """姓名脱敏:保留姓氏,其余用 ``*`` 代替,例如 ``张**``。"""
    value = str(name or "").strip()
    if not value:
        return ""
    if len(value) == 1:
        return "*"
    return f"{value[0]}{'*' * (len(value) - 1)}"


def mask_address(address: Any) -> str:
    """收货地址脱敏。

    - 结构化地址(dict):保留省/市,详细地址只保留前 3 个字符;
    - 字符串地址:最多保留前 6 个字符,且不超过原长度的一半。

    例如 ``{"province": "北京市", "city": "北京市", "detail": "朝阳区建国路88号"}``
    输出 ``北京市朝阳区***``。
    """
    if isinstance(address, dict):
        province = str(address.get("province", "") or "")
        city = str(address.get("city", "") or "")
        detail = str(address.get("detail", "") or "")
        region = province + ("" if city == province else city)
        if not detail:
            return region
        return f"{region}{detail[:3]}{MASK}"

    value = str(address or "").strip()
    if not value:
        return ""
    if len(value) <= 2:
        return MASK
    # 最多保留前 6 个字符,且不超过原长度的一半,避免短地址被完整展示
    keep = min(6, len(value) // 2)
    return f"{value[:keep]}{MASK}"

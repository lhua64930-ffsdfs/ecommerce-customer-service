"""JWT 与口令散列。"""
from __future__ import annotations

from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_and_verify() -> None:
    stored = hash_password("demo123")
    assert stored != "demo123"
    assert verify_password("demo123", stored) is True
    assert verify_password("wrong", stored) is False


def test_token_roundtrip_and_tamper() -> None:
    token = create_token(7, "demo_customer", ["customer"])
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "7"
    assert payload["roles"] == ["customer"]

    head, body, signature = token.split(".")
    assert decode_token(f"{head}.{body}.{signature[:-1]}x") is None


def test_expired_token_is_rejected() -> None:
    token = create_token(7, "demo_customer", ["customer"], expire_minutes=-1)
    assert decode_token(token) is None

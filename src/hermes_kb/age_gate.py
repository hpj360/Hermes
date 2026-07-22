"""年龄门签名 cookie 工具（A1-3）。"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import HTTPException, Request, status

from hermes_kb.config import get_settings

COOKIE_NAME = "age_verified"
COOKIE_TTL_DAYS = 30


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_age_cookie_value() -> str:
    """生成签名 cookie 值。"""
    settings = get_settings()
    payload = json.dumps(
        {"confirmed": True, "exp": int(time.time()) + COOKIE_TTL_DAYS * 86400}
    )
    sig = _sign(payload, settings.jwt_secret)
    # 拼接格式：payload|sig
    return f"{payload}|{sig}"


def verify_age_cookie(value: str | None) -> bool:
    """校验 cookie 值是否有效签名且未过期。"""
    if not value or "|" not in value:
        return False
    settings = get_settings()
    payload_str, sig = value.rsplit("|", 1)
    expected_sig = _sign(payload_str, settings.jwt_secret)
    if not hmac.compare_digest(sig, expected_sig):
        return False
    try:
        payload: dict[str, Any] = json.loads(payload_str)
    except Exception:
        return False
    if not payload.get("confirmed"):
        return False
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return False
    return True


async def require_age_gate(request: Request) -> None:
    """FastAPI 依赖：校验年龄门 cookie。

    age_gate_enabled=False 时跳过。
    """
    settings = get_settings()
    if not settings.age_gate_enabled:
        return
    cookie_value = request.cookies.get(COOKIE_NAME)
    if not verify_age_cookie(cookie_value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="age verification required",
        )

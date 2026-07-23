"""共享依赖：JWT 工具、认证、年龄门、RAG/Import 服务获取。

- ``jwt_encode`` / ``jwt_decode``：HS256 JWT（无外部依赖）。
- ``require_auth``：校验 Bearer JWT（未启用认证时放行）。
- ``require_age_gate``：从 :mod:`hermes_kb.age_gate` 重导出，便于路由统一从
  ``hermes_kb.api.deps`` 导入认证类依赖。
- ``get_rag`` / ``get_importer``：从 ``app.state`` 取应用级服务实例（实例在
  ``create_app()`` 中创建，保证每个 app 拥有独立实例，避免跨测试 settings 污染）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

from fastapi import HTTPException, Request, status

from hermes_kb.age_gate import require_age_gate  # noqa: F401  re-export
from hermes_kb.config import get_settings
from hermes_kb.rag import ImportService, RAGEngine

# ---------------------------------------------------------------------------
# JWT 工具（HS256，无外部依赖）
# ---------------------------------------------------------------------------
def _b64e(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return urlsafe_b64decode(s + pad)


def jwt_encode(payload: dict[str, Any], secret: str, ttl_hours: int = 24) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    body = {**payload, "iat": now, "exp": now + ttl_hours * 3600}
    h = _b64e(json.dumps(header, separators=(",", ":")).encode())
    p = _b64e(json.dumps(body, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64e(sig)}"


def jwt_decode(token: str, secret: str) -> dict[str, Any] | None:
    """解码并校验 JWT。失败返回 None。"""
    try:
        h, p, s = token.split(".")
    except ValueError:
        return None
    signing_input = f"{h}.{p}".encode()
    expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    try:
        actual = _b64d(s)
    except Exception:
        return None
    if not hmac.compare_digest(expected, actual):
        return None
    try:
        body = json.loads(_b64d(p).decode())
    except Exception:
        return None
    if body.get("exp", 0) < int(time.time()):
        return None
    return body


# ---------------------------------------------------------------------------
# 认证依赖
# ---------------------------------------------------------------------------
async def require_auth(request: Request) -> dict[str, Any] | None:
    """若启用认证，校验 JWT；未启用时直接放行。"""
    settings = get_settings()
    if not settings.auth_enabled:
        return None
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
        )
    token = auth[7:].strip()
    payload = jwt_decode(token, settings.jwt_secret)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证令牌无效或已过期",
        )
    return payload


# ---------------------------------------------------------------------------
# 应用级服务依赖（实例在 create_app() 中创建并挂到 app.state）
# ---------------------------------------------------------------------------
def get_rag(request: Request) -> RAGEngine:
    return request.app.state.rag


def get_importer(request: Request) -> ImportService:
    return request.app.state.importer

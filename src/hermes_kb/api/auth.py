"""认证与年龄门端点（M1-07 / M1-08）。"""
from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from hermes_kb.age_gate import (
    COOKIE_NAME,
    COOKIE_TTL_DAYS,
    make_age_cookie_value,
    verify_age_cookie,
)
from hermes_kb.api.deps import jwt_encode, require_auth
from hermes_kb.config import get_settings
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["auth"])


class LoginReq(BaseModel):
    password: str = Field(..., max_length=200)


class AgeGateReq(BaseModel):
    confirmed: bool


@router.post("/auth/login")
async def login(req: LoginReq) -> dict[str, Any]:
    settings = get_settings()
    if not settings.auth_enabled:
        return {
            "token": "",
            "auth_enabled": False,
            "message": "认证未启用",
        }
    # 单用户密码校验
    if not settings.auth_password:
        raise HTTPException(
            status_code=500,
            detail="服务端未配置认证密码（KB_AUTH_PASSWORD）",
        )
    if not hmac.compare_digest(req.password, settings.auth_password):
        raise HTTPException(status_code=401, detail="密码错误")
    token = jwt_encode(
        {"sub": settings.auth_username, "role": "admin"},
        settings.jwt_secret,
        ttl_hours=settings.jwt_ttl_hours,
    )
    return {
        "token": token,
        "auth_enabled": True,
        "username": settings.auth_username,
        "expires_in": settings.jwt_ttl_hours * 3600,
    }


@router.get("/auth/me")
async def me(payload: dict[str, Any] | None = Depends(require_auth)) -> dict[str, Any]:
    settings = get_settings()
    return {
        "auth_enabled": settings.auth_enabled,
        "username": (payload or {}).get("sub") if payload else None,
        "exp": (payload or {}).get("exp") if payload else None,
    }


@router.post("/age-gate/confirm")
async def age_gate_confirm(req: AgeGateReq, response: Response) -> dict[str, Any]:
    settings = get_settings()
    if req.confirmed:
        response.set_cookie(
            key=COOKIE_NAME,
            value=make_age_cookie_value(),
            max_age=COOKIE_TTL_DAYS * 86400,
            httponly=True,
            samesite="strict",
            secure=settings.cookie_secure,  # P2-5: 生产 HTTPS 通过 KB_COOKIE_SECURE=true 启用
        )
    return {
        "confirmed": bool(req.confirmed),
        "age_gate_enabled": settings.age_gate_enabled,
        "message": "已确认成年" if req.confirmed else "未确认",
    }


@router.get("/age-gate/status")
async def age_gate_status(request: Request) -> dict[str, Any]:
    settings = get_settings()
    confirmed = verify_age_cookie(request.cookies.get(COOKIE_NAME))
    return {
        "age_gate_enabled": settings.age_gate_enabled,
        "confirmed": confirmed,
        "message": "本站内容含酒类知识，未满 18 岁请勿访问"
        if settings.age_gate_enabled
        else "年龄门未启用",
    }

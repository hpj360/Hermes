"""配置安全校验测试（A1-1）。"""
from __future__ import annotations

import os

import pytest


def _clear_env(monkeypatch):
    """清掉相关 env，避免外部污染。"""
    for k in (
        "KB_AUTH_ENABLED",
        "KB_JWT_SECRET",
        "KB_AUTH_PASSWORD",
        "KB_USERNAME",
    ):
        monkeypatch.delenv(k, raising=False)


def test_auth_disabled_allows_default_secret(monkeypatch):
    """auth_enabled=False 时默认 secret 不报错（开发态）。"""
    _clear_env(monkeypatch)
    from hermes_kb.config import Settings, reset_settings

    reset_settings()
    # 默认 auth_enabled=False，应允许默认 secret
    s = Settings()
    assert s.auth_enabled is False
    assert "default-secret" in s.jwt_secret


def test_auth_enabled_with_default_secret_raises(monkeypatch):
    """auth_enabled=True 且 secret 仍是默认值时必须报错。"""
    _clear_env(monkeypatch)
    monkeypatch.setenv("KB_AUTH_ENABLED", "true")
    from hermes_kb.config import Settings, reset_settings

    reset_settings()
    with pytest.raises(RuntimeError, match="jwt_secret"):
        Settings()


def test_auth_enabled_with_empty_secret_raises(monkeypatch):
    """auth_enabled=True 且 secret 为空字符串时必须报错。"""
    _clear_env(monkeypatch)
    monkeypatch.setenv("KB_AUTH_ENABLED", "true")
    monkeypatch.setenv("KB_JWT_SECRET", "")
    from hermes_kb.config import Settings, reset_settings

    reset_settings()
    with pytest.raises(RuntimeError, match="jwt_secret"):
        Settings()


def test_auth_enabled_with_real_secret_ok(monkeypatch):
    """auth_enabled=True 且 secret 已改成非默认值时正常。"""
    _clear_env(monkeypatch)
    monkeypatch.setenv("KB_AUTH_ENABLED", "true")
    monkeypatch.setenv("KB_JWT_SECRET", "a-real-production-secret-xxx-yyy")
    from hermes_kb.config import Settings, reset_settings

    reset_settings()
    s = Settings()
    assert s.auth_enabled is True
    assert s.jwt_secret == "a-real-production-secret-xxx-yyy"

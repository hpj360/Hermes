"""年龄门后端校验测试（A1-3）。"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _make_app(auth_enabled=False, age_gate_enabled=True):
    from hermes_kb.app import create_app
    from hermes_kb.config import override_settings, reset_settings

    reset_settings()
    override_settings(
        auth_enabled=auth_enabled,
        age_gate_enabled=age_gate_enabled,
        jwt_secret="test-age-gate-secret-xxx",
    )
    return create_app()


def test_age_gate_confirm_sets_cookie():
    """确认成年后应下发 HttpOnly cookie。"""
    app = _make_app()
    client = TestClient(app)
    resp = client.post("/api/age-gate/confirm", json={"confirmed": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmed"] is True
    # 必须设置 cookie
    cookies = resp.headers.get("set-cookie", "")
    assert "age_verified=" in cookies
    assert "HttpOnly" in cookies
    assert "samesite=strict" in cookies.lower() or "SameSite=Strict" in cookies


def test_age_gate_protected_api_rejects_without_cookie():
    """未确认年龄直接调 /api/ask 应返回 403。"""
    app = _make_app()
    client = TestClient(app)
    # 不带 cookie
    resp = client.post("/api/ask", json={"query": "金酒"})
    assert resp.status_code == 403
    body = resp.json()
    assert "age" in body.get("detail", "").lower() or "age" in str(body).lower()


def test_age_gate_protected_api_accepts_with_cookie():
    """确认成年拿到 cookie 后调 /api/ask 应通过年龄门。"""
    app = _make_app()
    client = TestClient(app)
    # 先确认
    resp = client.post("/api/age-gate/confirm", json={"confirmed": True})
    assert resp.status_code == 200
    # cookie 自动保留在 client
    resp = client.post("/api/ask", json={"query": "金酒"})
    # 不应因年龄门被拒（可能因 LLM 不可用返回 200 mock 或 500，但不是 403 age gate）
    assert resp.status_code != 403


def test_age_gate_disabled_skips_check():
    """age_gate_enabled=False 时不校验。"""
    app = _make_app(age_gate_enabled=False)
    client = TestClient(app)
    resp = client.post("/api/ask", json={"query": "金酒"})
    assert resp.status_code != 403


def test_age_gate_status_reads_cookie():
    """/api/age-gate/status 应返回当前确认状态。"""
    app = _make_app()
    client = TestClient(app)
    # 未确认
    resp = client.get("/api/age-gate/status")
    assert resp.status_code == 200
    assert resp.json()["confirmed"] is False
    # 确认后
    client.post("/api/age-gate/confirm", json={"confirmed": True})
    resp = client.get("/api/age-gate/status")
    assert resp.status_code == 200
    assert resp.json()["confirmed"] is True


def test_age_gate_forged_cookie_rejected():
    """伪造的 cookie 值应被拒绝。"""
    app = _make_app()
    client = TestClient(app)
    # 伪造 cookie（用错误 secret 签名）
    client.cookies.set("age_verified", "invalid-forged-token")
    resp = client.post("/api/ask", json={"query": "金酒"})
    assert resp.status_code == 403


def test_age_gate_lab_endpoints_protected():
    """实验室端点 /api/lab/* 也应受年龄门保护。"""
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/lab/match?ingredients=gin")
    assert resp.status_code == 403

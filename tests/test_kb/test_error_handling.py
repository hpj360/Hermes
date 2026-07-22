"""异常处理器安全测试（A1-2）。"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _make_app_with_debug(debug: bool):
    from hermes_kb.app import create_app
    from hermes_kb.config import override_settings, reset_settings

    reset_settings()
    override_settings(debug=debug, auth_enabled=False)
    return create_app()


def _register_raising_route(app, path: str, endpoint):
    """注册测试路由，并置于 router 最前，避免被 create_app 末尾的静态文件
    catch-all mount（web/dist 存在时挂载在 /）吞掉返回 404。"""
    app.add_api_route(path, endpoint, methods=["GET"])
    # 将刚追加到末尾的路由移到最前
    app.router.routes.insert(0, app.router.routes.pop())


def test_generic_exception_production_mode_hides_detail():
    """生产模式：500 响应不应包含 str(exc)。"""
    app = _make_app_with_debug(debug=False)
    # 注入一个会抛 Exception 的路由
    from fastapi import Request

    async def _raise_internal():
        raise RuntimeError("DB_CONNECTION_STRING=postgres://secret@host:5432")

    _register_raising_route(app, "/__test_raise_internal", _raise_internal)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/__test_raise_internal")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"] == "internal"
    # detail 不应包含敏感的连接串
    assert "postgres://secret" not in body.get("detail", "")
    assert "DB_CONNECTION_STRING" not in body.get("detail", "")
    # 应包含 correlation_id
    assert "correlation_id" in body
    assert len(body["correlation_id"]) == 8


def test_generic_exception_dev_mode_shows_detail():
    """开发模式：500 响应保留 str(exc) 便于排查。"""
    app = _make_app_with_debug(debug=True)
    from fastapi import Request

    async def _raise_internal():
        raise RuntimeError("DB_CONNECTION_STRING=postgres://secret@host:5432")

    _register_raising_route(app, "/__test_raise_internal_dev", _raise_internal)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/__test_raise_internal_dev")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"] == "internal"
    # 开发模式下应能看到 detail
    assert "DB_CONNECTION_STRING" in body["detail"]
    assert "correlation_id" in body


def test_value_error_keeps_400_with_detail():
    """ValueError 仍应返回 400 + 业务 detail。"""
    app = _make_app_with_debug(debug=False)
    from fastapi import Request

    async def _raise_value_error():
        raise ValueError("document title cannot be empty")

    _register_raising_route(app, "/__test_raise_value_error", _raise_value_error)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/__test_raise_value_error")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "bad_request"
    assert body["detail"] == "document title cannot be empty"

"""U1b: FastAPI gateway unifying the workbench API under one service surface.

Architecture (PRD §5, D1/D3):
* **Single service surface** — one uvicorn process on one port. The workbench
  ``ThreadingHTTPServer`` is NOT started here; its handler logic is reused
  through a thin bridge so the 60+ existing JSON routes keep working without a
  mechanical rewrite. SSE streams are re-implemented as native
  ``StreamingResponse`` (they cannot go through the request/response bridge).
* **Single auth** — one Bearer token (``HERMES_API_TOKEN``, constant-time
  compare, fallback to legacy ``OPENCLAW_GATEWAY_TOKEN``) guards both ``/wb/*``
  and ``/api/*``. ``/health`` stays public.
* **Scheduler runs here** — the lifespan starts the scheduler center (recovery
  + worker pool + cron), making the gateway the single scheduling runtime.

The bridge reuses the exact handler classes from ``server.py`` by simulating
the tiny http.server request surface they rely on (``headers``, ``rfile``,
``wfile``, ``path``), capturing each response instead of writing to a socket.
"""

from __future__ import annotations

import io
import json
import re
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from hermes.workbench import server as wb_server
from hermes.workbench.errors import NotFoundError, WorkbenchError, status_code_for

__all__ = ["create_app"]

# Paths that never require a token (health + static + root).
_PUBLIC_PREFIXES = ("/health", "/assets/", "/")


class _Capture:
    """Captures the response produced by a bridge-invoked handler."""

    def __init__(self) -> None:
        self.status: int = 200
        self.body: bytes = b""
        self.content_type: str = "application/json; charset=utf-8"


class _BridgeHandler(wb_server.DashboardHandler):
    """Mimics the http.server request surface for ``DashboardHandler`` methods.

    Subclasses ``DashboardHandler`` so handler helper methods (``_todos()``,
    ``_read_json_body()``, ``_query_params()``, ...) resolve, while overriding
    every socket-facing helper to capture the response instead.
    """

    # -- socket-facing surface (capture instead of writing to a socket) -------

    def __init__(self, path: str, headers: dict[str, str], body: bytes, capture: _Capture) -> None:
        self.path = path
        # 基类声明的 headers 是 http.client.Message；桥接层用 dict 模拟其
        # .get() 接口（duck-typing），运行时不变，仅以 cast 通过静态检查。
        self.headers = cast(Any, headers)
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.client_address = ("127.0.0.1", 0)
        self.command = "GET"
        self._capture = capture

    def _send_json(self, status: int, obj: Any) -> None:
        self._capture.status = status
        self._capture.body = json.dumps(obj, ensure_ascii=False).encode("utf-8")

    def _send_no_content(self) -> None:
        self._capture.status = 204
        self._capture.body = b""

    def _send_text(self, status: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        self._capture.status = status
        self._capture.body = text.encode("utf-8")
        self._capture.content_type = content_type

    def _send_cors_headers(self) -> None:
        pass

    def send_response(self, status: int, message: str | None = None) -> None:
        self._capture.status = status

    def send_header(self, keyword: str, value: str) -> None:
        pass

    def end_headers(self) -> None:
        pass

    def _check_auth(self) -> bool:
        # Auth is enforced at the FastAPI middleware level; bridge is internal.
        return True

    def _read_json_body(self) -> Any:
        raw = self.rfile.read()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            from hermes.workbench.errors import ValidationError

            raise ValidationError(f"invalid JSON body: {e}") from e

    def _query_params(self) -> dict[str, str]:
        from urllib.parse import parse_qs, urlsplit

        parsed = parse_qs(urlsplit(self.path).query)
        return {k: v[0] for k, v in parsed.items() if v}

    def _parse_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


def _dispatch(path: str, method: str, headers: dict[str, str], body: bytes) -> _Capture:
    """Match the path against the workbench route table and run the handler."""
    path_only = re.split(r"[?#]", path, maxsplit=1)[0]
    for route_method, pattern, handler_name in wb_server._ROUTES:
        if route_method != method:
            continue
        m = re.match(pattern, path_only)
        if m is None:
            continue
        capture = _Capture()
        bridge = _BridgeHandler(path, headers, body, capture)
        # Attach the real handler methods to the bridge instance.
        cls = wb_server.DashboardHandler
        try:
            getattr(cls, handler_name)(bridge, **m.groupdict())
        except WorkbenchError as e:
            capture.status = status_code_for(e)
            capture.body = json.dumps({"error": str(e), "type": type(e).__name__}).encode("utf-8")
        except Exception as e:  # noqa: BLE001 - boundary
            capture.status = 500
            capture.body = json.dumps({"error": str(e), "type": type(e).__name__}).encode("utf-8")
        return capture
    raise NotFoundError(f"route not found: {method} {path}")


def _sse_jobs() -> Any:
    """Native SSE for job status via the StatusBus (blocking read off thread)."""

    # 生成器补返回类型注解（SSE 事件流逐帧 yield str）
    def gen() -> Iterator[str]:
        import queue as _queue

        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        bus = center.status_bus
        q = bus.subscribe()
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = q.get(timeout=15.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except _queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _sse_episodes() -> Any:
    """Native SSE polling episodes feed."""

    # 生成器补返回类型注解（SSE 事件流逐帧 yield str）
    def gen() -> Iterator[str]:
        import time

        from hermes.workbench.cli import _make_memory

        memory = _make_memory()
        yield ": connected\n\n"
        while True:
            try:
                episodes = memory.list_episodes(kind="loop", limit=20)
                payload = json.dumps([e.__dict__ for e in episodes], ensure_ascii=False)
                yield f"data: {payload}\n\n"
            except Exception:  # noqa: BLE001
                yield ": heartbeat\n\n"
            time.sleep(15.0)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _make_auth_middleware(app: FastAPI, token: str | None) -> None:
    """Apply Bearer-token enforcement to /wb/* and /api/* (not public paths)."""

    @app.middleware("http")
    async def auth(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if not token:
            return await call_next(request)
        if path.startswith(_PUBLIC_PREFIXES) and not path.startswith(("/wb/", "/api/")):
            return await call_next(request)
        authz = request.headers.get("Authorization", "")
        if authz.startswith("Bearer ") and secrets.compare_digest(authz[7:], token):
            return await call_next(request)
        return JSONResponse({"error": "unauthorized", "type": "AuthError"}, status_code=401)


def create_app(state_dir: Path | None = None) -> FastAPI:
    """Build the unified gateway FastAPI app.

    Mounts:
      /wb/*   — workbench routes (bridge reuse + native SSE)
      /api/*  — content_team business routes
      /       — React SPA (apps/web/dist) when present
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        stats = center.start()
        print(f"[gateway] scheduler started: requeued={stats['requeued']} abandoned={stats['abandoned']}")

        # D2: content_team 的发布/采集 cron 也由本网关进程驱动，共享同一
        # JobStore/队列；content_team 自身不再持有独立调度中心。
        cron_shutdown = None
        try:
            from hermes.content_team.triggers import init_cron_scheduler, shutdown_cron_scheduler

            init_cron_scheduler()
            cron_shutdown = shutdown_cron_scheduler
        except Exception as exc:  # noqa: BLE001
            print(f"[gateway] content_team cron unavailable: {exc}")

        yield

        if cron_shutdown is not None:
            try:
                cron_shutdown()
            except Exception:  # noqa: BLE001
                pass
        center.stop()

    app = FastAPI(title="Hermes Workbench Gateway", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth
    from hermes.config import get_settings

    settings = get_settings()
    token = getattr(settings, "hermes_api_token", None) or getattr(settings, "openclaw_gateway_token", None)
    _make_auth_middleware(app, token)

    # content_team routes
    try:
        from hermes.content_team.api.router import api_router

        app.include_router(api_router)
    except Exception as exc:  # noqa: BLE001
        print(f"[gateway] content_team router unavailable: {exc}")

    # Native SSE (must be registered before the catch-all /wb route)
    @app.get("/wb/stream/jobs")
    async def wb_stream_jobs():  # type: ignore[no-untyped-def]
        return _sse_jobs()

    @app.get("/wb/stream/episodes")
    async def wb_stream_episodes():  # type: ignore[no-untyped-def]
        return _sse_episodes()

    # Workbench bridge catch-all
    @app.api_route("/wb/{path:path}", methods=["GET", "POST", "DELETE", "PUT", "PATCH"])
    async def wb_bridge(path: str, request: Request):  # type: ignore[no-untyped-def]
        from urllib.parse import urlsplit

        method = request.method
        raw_path = f"/{path}"
        query = urlsplit(str(request.url)).query
        if query:
            raw_path = f"{raw_path}?{query}"
        body = await request.body()
        headers = {k: v for k, v in request.headers.items()}
        capture = _dispatch(raw_path, method, headers, body)
        content_type = capture.content_type
        return JSONResponse(
            content=json.loads(capture.body) if capture.body else None,
            status_code=capture.status,
            media_type=content_type,
        )

    # Health (public, but delegated to the workbench handler for consistency)
    @app.get("/health")
    async def health():  # type: ignore[no-untyped-def]
        capture = _dispatch("/health", "GET", {}, b"")
        return JSONResponse(
            content=json.loads(capture.body) if capture.body else None,
            status_code=capture.status,
        )

    # Feishu bot inbox webhook (C3) --------------------------------------
    @app.post("/feishu/events")
    async def feishu_events(request: Request):  # type: ignore[no-untyped-def]
        """Feishu event subscription webhook (bot inbox ingestion).

        Handles ``url_verification`` challenge echo and ``im.message.receive_v1``
        events. When ``FEISHU_VERIFICATION_TOKEN`` is set, the ``X-Lark-Signature``
        is verified (HMAC-SHA256 over timestamp+nonce+body). This endpoint needs
        a public URL (tunnel) — the no-tunnel local path is
        ``hermes workbench feishu-inbox`` (lark-cli long connection).
        """
        import hashlib
        import hmac as _hmac

        from hermes.config import get_settings as _get_settings

        raw = await request.body()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        # URL verification handshake
        if payload.get("type") == "url_verification":
            return JSONResponse({"challenge": payload.get("challenge", "")})

        # Signature verification (best-effort when token configured)
        settings = _get_settings()
        verification_token = getattr(settings, "feishu_verification_token", None)
        if verification_token:
            ts = request.headers.get("X-Lark-Request-Timestamp", "")
            nonce = request.headers.get("X-Lark-Request-Nonce", "")
            sign = request.headers.get("X-Lark-Signature", "")
            to_sign = f"{ts}{nonce}{raw.decode('utf-8', 'replace')}"
            expected = _hmac.new(
                verification_token.encode("utf-8"),
                to_sign.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if not sign or not _hmac.compare_digest(sign, expected):
                return JSONResponse({"error": "unauthorized"}, status_code=401)

        # Ingest the message event (Feishu nests the payload under "event").
        from hermes.workbench.capture import CaptureService
        from hermes.workbench.cli import _make_notes_dir, _make_todo_store
        from hermes.workbench.feishu_inbox import FeishuInboxService

        event_obj = payload.get("event") or payload
        svc = FeishuInboxService(CaptureService(_make_todo_store(), _make_notes_dir()))
        try:
            result = svc.ingest(event_obj)
        except Exception as exc:  # noqa: BLE001 - never break the webhook
            return JSONResponse({"error": str(exc)}, status_code=500)
        if result is None:
            return JSONResponse({"skipped": True}, status_code=200)
        return JSONResponse({"skipped": False, "result": result}, status_code=201)

    # SPA static
    dist = (Path(__file__).resolve().parents[3] / "apps" / "web" / "dist")
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        async def index():  # type: ignore[no-untyped-def]
            return FileResponse(dist / "index.html")

        @app.get("/{path:path}")
        async def spa_fallback(path: str):  # type: ignore[no-untyped-def]
            candidate = dist / path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


def run_gateway(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the gateway with uvicorn (blocking). Convenience for scripts/bat.

    Wires rotating file logging under ``HERMES_DATA_DIR/logs/gateway.log``
    (5 MB × 5) so a long-running service never grows an unbounded log.
    """
    import logging
    import os
    from pathlib import Path as _Path

    from hermes.logging import setup_logging

    data_dir = os.environ.get("HERMES_DATA_DIR") or str(_Path(__file__).resolve().parents[3] / "data")
    log_path = _Path(data_dir) / "logs" / "gateway.log"
    setup_logging(level=os.environ.get("HERMES_LOG_LEVEL", "INFO"), log_file=log_path)
    logging.getLogger("hermes.workbench.gateway").info(
        "gateway starting on http://%s:%s (log: %s)", host, port, log_path
    )

    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, log_level="info")

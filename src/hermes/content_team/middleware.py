"""FastAPI middleware for trace_id injection."""

from __future__ import annotations

from typing import Any

from .observability import generate_trace_id, log_event, with_trace

try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    _ASGI_AVAILABLE = True
except ImportError:  # starlette/fastapi 未安装时降级，保证模块仍可导入
    _ASGI_AVAILABLE = False
    BaseHTTPMiddleware = None  # type: ignore[assignment, misc]
    Request = Any  # type: ignore[assignment, misc]
    Response = Any  # type: ignore[assignment, misc]


TRACE_ID_HEADER = "X-Trace-Id"


if _ASGI_AVAILABLE:

    class TraceIdMiddleware(BaseHTTPMiddleware):  # type: ignore[misc]
        """为每个请求注入 trace_id 的 ASGI 中间件。

        - 优先复用客户端 ``X-Trace-Id`` 请求头，缺失时自动生成
        - 在请求生命周期内绑定 trace_id 到日志上下文
        - 在响应头回写 ``X-Trace-Id`` 便于链路追踪
        - 记录 request_start / request_end 结构化事件
        """

        async def dispatch(
            self, request: Request, call_next: Any
        ) -> Response:
            trace_id = request.headers.get(TRACE_ID_HEADER) or generate_trace_id()
            method = request.method
            path = request.url.path
            with with_trace(trace_id, method=method, path=path):
                log_event("request_start", f"{method} {path}")
                response = await call_next(request)
                response.headers[TRACE_ID_HEADER] = trace_id
                log_event(
                    "request_end",
                    f"{method} {path}",
                    status=response.status_code,
                )
                return response

else:

    class TraceIdMiddleware:  # type: ignore[no-redef]
        """FastAPI/Starlette 未安装时的占位类。

        模块仍可导入；实例化时抛出 RuntimeError 提示先安装依赖，
        避免在未安装 FastAPI 的环境里静默失效。
        """

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError(
                "TraceIdMiddleware 依赖 starlette/fastapi，请先安装后再使用"
            )

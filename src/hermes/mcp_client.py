"""Generic MCP (Model Context Protocol) client for Hermes.

与 :mod:`hermes.mcp` 的关系：
- ``hermes.mcp`` 提供 GitHub 专用 REST 客户端（读多写少、幂等、软降级）。
- 本模块是 **协议级通用客户端**，用于消费任意 MCP server（stdio / HTTP），
  例如 Open Design（open-design.ai）的设计生成工具集。

设计原则（沿用 hermes.mcp 的 Harness 工程约束）：
- 读多写少：tools/list 等读方法充足；写操作（tools/call）由工具自身保证
  幂等，本客户端仅负责传输与全量审计。
- 软降级：任何失败返回 ``{"success": False, "error": ...}``，不向调用方抛异常。
- 全量审计：每个请求写入 workbench audit store（server=server_name）。
- 不引入新依赖：stdio 走 subprocess，HTTP 走 urllib，与存量代码同栈。

协议（JSON-RPC 2.0 over stdio / HTTP）：
- initialize 握手（protocolVersion/capabilities/clientInfo）
- ``notifications/initialized``
- ``tools/list`` / ``tools/call``
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger("hermes.mcp_client")

# MCP 协议版本（2025-03-26 为目前主流 server 实现的 baseline）。
PROTOCOL_VERSION = "2025-03-26"

# 单次请求默认超时（秒）。超时属于软失败：返回 success=False。
DEFAULT_TIMEOUT = 30.0

# 配置文件名（与 Claude Code / Open Design 的 servers 结构对齐）。
MCP_CONFIG_NAME = "mcp.json"


class MCPConfigError(ValueError):
    """MCP 配置缺失或格式错误。"""


def default_mcp_config_path() -> Path:
    """返回默认 mcp.json 路径（可用 HERMES_MCP_CONFIG 覆盖）。"""
    env = os.environ.get("HERMES_MCP_CONFIG", "").strip()
    if env:
        return Path(env)
    # 与 Settings._project_root() 保持一致：优先数据目录，回退源码树。
    from hermes.config import get_settings

    settings = get_settings()
    return Path(settings.hermes_state_dir).parent / MCP_CONFIG_NAME


def load_mcp_config(path: str | Path | None = None) -> dict[str, Any]:
    """加载 mcp.json。

    结构（与 Open Design/Claude 惯例对齐）：:

        {
          "servers": {
            "open-design": {"command": "od", "args": ["mcp", "server"], "env": {}},
            "remote":     {"url": "https://...", "headers": {"Authorization": "..."}}
          }
        }

    每个 server 条目必须提供 ``command``（stdio）或 ``url``（HTTP）二者之一。
    缺失/损坏返回空配置（不抛异常），由调用方决定如何提示。
    """
    path = Path(path) if path else default_mcp_config_path()
    if not path.exists():
        logger.debug("MCP config not found: %s", path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("MCP config unreadable (%s): %s", path, e)
        return {}
    servers = data.get("servers", {}) if isinstance(data, dict) else {}
    if not isinstance(servers, dict):
        logger.warning("MCP config 'servers' is not an object: %s", path)
        return {}
    return {k: v for k, v in servers.items() if isinstance(v, dict)}


def _redact_env(env: dict[str, str] | None) -> dict[str, str] | None:
    """拷贝 env 但排除 API key 类变量（避免审计日志泄露密钥）。"""
    if not env:
        return None
    sensitive = ("key", "token", "secret", "password", "credential")
    return {k: v for k, v in env.items() if not any(s in k.lower() for s in sensitive)}


class StdioTransport:
    """通过子进程 stdio 与 MCP server 通信（行分隔 JSON）。"""

    def __init__(self, command: str, args: list[str], env: dict[str, Any] | None = None) -> None:
        self.command = command
        self.args = list(args)
        self.env = env
        self._proc: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._closed = False

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        proc_env = os.environ.copy()
        proc_env.update({k: str(v) for k, v in (self.env or {}).items()})
        self._proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=proc_env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._reader_thread = threading.Thread(
            target=self._read_loop, name=f"mcp-stdio-{self.command}", daemon=True
        )
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, name=f"mcp-stderr-{self.command}", daemon=True
        )
        self._stderr_thread.start()

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for raw in self._proc.stdout:
            line = raw.strip()
            if line:
                self._lines.put(line)
        self._lines.put(None)  # type: ignore[arg-type]  # EOF 哨兵

    def _stderr_loop(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        for raw in self._proc.stderr:
            self._stderr_lines.append(raw.rstrip("\n"))

    def send(self, payload: dict[str, Any]) -> None:
        """写入一个 JSON-RPC 消息（不做等待）。"""
        if not self.alive:
            raise RuntimeError("MCP server process is not running")
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def wait_response(self, request_id: int, timeout: float) -> dict[str, Any]:
        """读取直到返回指定 id 的响应。超时或进程退出抛 TimeoutError/RuntimeError。"""
        deadline = _deadline(timeout)
        while True:
            remaining = deadline - _now()
            if remaining <= 0:
                raise TimeoutError(f"MCP request {request_id} timed out after {timeout}s")
            try:
                line = self._lines.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if line is None:  # EOF：进程已退出
                if not self.alive:
                    raise RuntimeError(
                        f"MCP server exited early (code={self._proc.returncode}); "
                        f"stderr={self.stderr_tail()}"
                    )
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("MCP server emitted malformed JSON: %r", line[:200])
                continue
            # 只接受 jsonrpc 响应；notification（无 id）与 server 主动请求一律跳过。
            if not isinstance(msg, dict) or msg.get("id") != request_id:
                continue
            return msg

    def stderr_tail(self, n: int = 5) -> str:
        return " | ".join(self._stderr_lines[-n:])

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._proc is not None:
            try:
                if self.alive and self._proc.stdin is not None:
                    self._proc.stdin.close()
                self._proc.terminate()
            except OSError:
                pass
        for th in (self._reader_thread, self._stderr_thread):
            if th is not None:
                th.join(timeout=1.0)


class HTTPTransport:
    """通过 Streamable HTTP POST 与 MCP server 通信。"""

    def __init__(
        self, url: str, headers: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        self.url = url
        self.headers = {k: str(v) for k, v in (headers or {}).items()}
        self.timeout = timeout

    def request(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        headers.update(self.headers)
        req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001 — 软降级，不向上抛
            raise RuntimeError(f"HTTP MCP request failed: {e}") from e
        # 兼容两种响应体：单个 JSON 或 SSE 格式（逐个 data: 行解析）。
        if "data:" in body:
            for line in body.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    try:
                        # json.loads 返回 Any，按 JSON-RPC 契约 cast 为 dict
                        return cast(dict[str, Any], json.loads(line[len("data:"):].strip()))
                    except json.JSONDecodeError:
                        continue
        try:
            return cast(dict[str, Any], json.loads(body))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"MCP server returned non-JSON body: {e}") from e

    def send(self, payload: dict[str, Any]) -> None:
        """发送一个消息（如 notification）并忽略响应——HTTP 是请求-响应模型，
        通知类消息 server 可能返回空 body/202，解析失败属正常，应忽略。"""
        try:
            self.request(payload, timeout=5.0)
        except RuntimeError:
            logger.debug(
                "MCP notification '%s' send failed (ignored)",
                payload.get("method"),
            )

    def close(self) -> None:
        return


class MCPClient:
    """通用 MCP 客户端：initialize 握手 + tools/list + tools/call。

    用法::

        client = MCPClient("open-design", {"command": "od", "args": ["mcp", "server"]})
        try:
            client.connect()
            tools = client.list_tools()
            result = client.call_tool("generate", {"prompt": "..."})
        finally:
            client.close()
    """

    def __init__(
        self,
        server_name: str,
        config: dict[str, Any],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.server_name = server_name
        self.config = config
        self.timeout = timeout
        self._transport: StdioTransport | HTTPTransport | None = None
        self._next_id = 0
        self._initialized = False

    # -- 生命周期 ---------------------------------------------------------

    def connect(self) -> None:
        """启动传输并完成 initialize 握手。失败抛异常（由调用方软降级）。"""
        command = self.config.get("command")
        url = self.config.get("url")
        if command:
            self._transport = StdioTransport(
                str(command),
                [str(a) for a in self.config.get("args", [])],
                self.config.get("env"),
            )
            self._transport.start()
        elif url:
            self._transport = HTTPTransport(
                str(url), self.config.get("headers"), timeout=self.timeout
            )
        else:
            raise MCPConfigError(
                f"MCP server '{self.server_name}' needs 'command' (stdio) or 'url' (HTTP)"
            )
        self._handshake()

    def _handshake(self) -> None:
        resp = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "hermes", "version": "0.6.0"},
            },
        )
        norm = self._normalize(resp)
        if not norm.get("success"):
            raise RuntimeError(f"initialize failed: {norm.get('error')}")
        # 通知 server 初始化完成（fire-and-forget）。
        # connect() 刚完成传输装配，_handshake 仅由 connect() 调用，
        # 此处必非 None；与 _request 内的判 None 模式保持一致。
        assert self._transport is not None
        self._transport.send(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        self._initialized = True

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        self._initialized = False

    # -- 内部传输 ---------------------------------------------------------

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        assert self._transport is not None
        try:
            if isinstance(self._transport, StdioTransport):
                self._transport.send(payload)
                return self._transport.wait_response(request_id, self.timeout)
            return self._transport.request(payload, timeout=self.timeout)
        except (TimeoutError, RuntimeError, OSError) as e:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"message": str(e)}}

    @staticmethod
    def _normalize(msg: dict[str, Any]) -> dict[str, Any]:
        """把 JSON-RPC 消息规范化为 success/error 结构（软降级契约）。"""
        if msg.get("error") is not None:
            err = msg["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            return {"success": False, "error": str(message or "unknown error")}
        result = msg.get("result", {})
        if not isinstance(result, dict):
            result = {"value": result}
        # 工具执行错误：MCP 约定 result.isError=true 表示业务级失败。
        is_error = bool(result.get("isError"))
        return {"success": not is_error, "result": result, "isError": is_error}

    # -- 公开 API ----------------------------------------------------------

    def ping(self) -> dict[str, Any]:
        """连通性检查：已完成握手即为可达（不进审计，供 CLI 快速探测）。"""
        if not self._initialized:
            return {"success": False, "error": "client not initialized (call connect first)"}
        return {"success": True, "initialized": True}

    def list_tools(self) -> dict[str, Any]:
        """列出 server 暴露的工具。返回 success=False + error 表示软失败。"""
        msg = self._request("tools/list", {})
        norm = self._normalize(msg)
        self._record("tools.list", {}, norm["success"], norm.get("error", ""))
        return norm

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用工具。写操作由工具自身保证幂等；此处记录全量审计。"""
        msg = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        norm = self._normalize(msg)
        self._record("tools.call", {"name": name}, norm["success"], norm.get("error", ""))
        return norm

    # -- 审计 --------------------------------------------------------------

    def _record(self, method: str, args: dict[str, Any], success: bool, error: str) -> None:
        _record_audit(self.server_name, method, args, success, error)


# 可注入审计实现（供测试替换）。None 时走 workbench audit store。
_audit_impl = None


def _record_audit(
    server_name: str, method: str, args: dict[str, Any], success: bool, error: str
) -> None:
    """写入一条审计记录；落盘失败仅告警，不阻断主流程。"""
    try:
        if _audit_impl is not None:
            _audit_impl(server_name, method, success, args, error)
            return
        from hermes.workbench.audit import default_audit_store

        default_audit_store().record(
            server=server_name, method=method, success=success, args=args, error=error
        )
    except Exception:  # noqa: BLE001 — 审计落盘失败不得阻断主流程
        logger.warning(
            "failed to persist MCP audit record for %s.%s", server_name, method
        )


# -- 辅助 ---------------------------------------------------------------


def _now() -> float:
    import time

    return time.monotonic()


def _deadline(timeout: float) -> float:
    return _now() + timeout

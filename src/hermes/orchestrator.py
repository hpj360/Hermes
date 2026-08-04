"""Sub-Agent orchestration layer for Hermes.

This module implements the control-plane approach: Hermes orchestrates
agent execution through the OpenClaw Gateway API (or falls back to
guidance mode when the gateway is unavailable).

Key components:
- OpenClawClient: HTTP client wrapping the Gateway API
- AgentTask: Dataclass describing a sub-agent task
- Orchestrator: Fan-out/fan-in execution coordinator
"""

from __future__ import annotations

import fnmatch
import http.client
import json
import logging
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from hermes.config import get_settings
from hermes.tool_recovery import analyze_failures, format_recovery_section

logger = logging.getLogger("hermes.orchestrator")

# Structured failure protocol markers emitted by checker.md templates.
# Checkers are asked to append a JSON block so the orchestrator can extract
# normalized (file, type) failure keys instead of guessing from free text.
_FAILURES_BLOCK_RE = re.compile(
    r"<!--\s*failures:json\s*-->\s*(\{.*?\})\s*<!--\s*/failures\s*-->",
    re.DOTALL,
)


def _parse_structured_failures(checker_result: str, role: str) -> list[str]:
    """Extract failure items from a checker report.

    Prefers the structured ``<!-- failures:json -->`` protocol block: returns
    normalized ``"file|type"`` keys (without line numbers) so stop-rule set
    comparison survives line-number drift when a builder edits earlier lines.

    Falls back to a single verbatim item ``"<role>: <first non-empty line>"``
    when no structured block is present — this never guesses which lines are
    failures (the old ``"file:"/".py:"`` heuristic is removed).
    """
    match = _FAILURES_BLOCK_RE.search(checker_result)
    if match:
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            data = {}
        failures = data.get("failures") or []
        items: list[str] = []
        for f in failures:
            if not isinstance(f, dict):
                continue
            file = str(f.get("file", "")).strip()
            ftype = str(f.get("type", "")).strip()
            # Normalize to "file|type" — drop line numbers deliberately.
            key = f"{file}|{ftype}" if file or ftype else ""
            if key:
                items.append(f"{role}: {key}")
        if items:
            return items
    # Fallback: verbatim first meaningful line, prefixed with role. No guessing.
    for line in checker_result.splitlines():
        stripped = line.strip()
        if stripped and "ALL GREEN" not in stripped.upper():
            return [f"{role}: {stripped}"]
    return [f"{role}: [UNPARSEABLE FAILURE]"]


# MCP 工具按角色分舱白名单（P0 安全提升）。
# 铁律：builder 只能读 GitHub 不能写（create_pr/post_pr_comment 被拦截），
# 防止 builder 绕过 reviewer 人工检查直接合并代码。
# checker/synthesizer 不需要任何 MCP 工具。
# 格式："{server}.{method}"，如 "github.create_pr"。
ROLE_MCP_WHITELIST: dict[str, list[str]] = {
    # builder: 只读 GitHub（查 PR/issue 做上下文），禁止写操作
    "builder": ["github.get_pr", "github.list_prs", "github.get_issue"],
    # checker 系列: 无 MCP（只跑本地 lint/type/test）
    "checker": [],
    "checker_lint": [],
    "checker_type": [],
    "checker_test": [],
    # synthesizer: 无 MCP（只汇总文本）
    "synthesizer": [],
}


def _get_role_whitelist(role: str) -> list[str] | None:
    """获取角色默认 MCP 白名单。未匹配的角色返回 None（不限制）。"""
    if role in ROLE_MCP_WHITELIST:
        return ROLE_MCP_WHITELIST[role]
    # perspective_* 等动态角色：前缀匹配
    for prefix, whitelist in ROLE_MCP_WHITELIST.items():
        if role.startswith(prefix):
            return whitelist
    return None


@dataclass
class AgentTask:
    """A task to be dispatched to a sub-agent."""

    role: str
    agent_file: str | None = None
    task_description: str = ""
    context: str = ""
    check_type: str | None = None
    parallel: bool = False
    session_id: str | None = None
    result: str | None = None
    status: str = "pending"  # pending, running, completed, failed
    tokens_used: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    # MCP 工具白名单：None=不限制（向后兼容），[]=禁止所有 MCP，非空=只允许列出的工具。
    # fan_out 时若为 None，自动按 role 填充 ROLE_MCP_WHITELIST 默认值。
    allowed_mcp_tools: list[str] | None = None
    # fan_in 审计后填充：检测到的违规 MCP 工具调用列表。
    mcp_violations: list[str] = field(default_factory=list)
    # P1: 单 agent token 上限。fan_in 时若 tokens_used > token_limit 标记 failed。
    # 0 = 不限制（向后兼容）。默认 50000（约 $0.15 GPT-4 单次）。
    token_limit: int = 50000
    # Stage 6: L3 denylist 路径强制执行。由 runner 从 LOOP_PATTERNS 注入。
    # 非空时 fan_in 审计 Write/Edit 工具调用的 path 参数，命中 denylist
    # pattern 即记 path_violation，aggregate_results 强制 builder failed。
    # 空 list = 不限制（向后兼容）；仅对有 Write 权限的 role（builder 等）生效。
    denylist: list[str] = field(default_factory=list)
    # fan_in 审计后填充：检测到的违规文件路径写入操作列表。
    path_violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "agent_file": self.agent_file,
            "task_description": self.task_description,
            "check_type": self.check_type,
            "parallel": self.parallel,
            "session_id": self.session_id,
            "result": self.result,
            "status": self.status,
            "tokens_used": self.tokens_used,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "allowed_mcp_tools": self.allowed_mcp_tools,
            "mcp_violations": self.mcp_violations,
            "token_limit": self.token_limit,
            "denylist": self.denylist,
            "path_violations": self.path_violations,
        }


@dataclass
class RoundResult:
    """Aggregated result of a loop round."""

    round_num: int
    tasks: list[AgentTask] = field(default_factory=list)
    all_passed: bool = False
    failure_items: list[str] = field(default_factory=list)
    total_tokens: int = 0
    summary: str = ""
    checker_report: str = ""
    # P2 可观测性：本轮检测到的 MCP 工具角色违规调用总数
    role_violation_count: int = 0
    # P2 multi-agent 协作评估指标：本轮 sub-agent 协作的结构化诊断。
    # 字段说明（由 _compute_collaboration_metrics 填充）：
    #   token_by_role: dict[role, int] - 每个 role 本轮消耗的 token（效率归因）
    #   failure_attribution: "builder" | "checker" | "mixed" | "none"
    #     - builder: builder 自身 failed（如 token 熔断 / 超时 / 输出无效）
    #     - checker: builder 完成但 checker 报告失败（修复未达标）
    #     - mixed: 既有 builder 失败也有 checker 失败
    #     - none: 全部通过
    #   checker_builder_agreement: bool - checker 是否认同 builder 的成功声明
    #     True=checker ALL GREEN / False=checker FAILED / None=无 checker 或 builder 已 failed
    #   roles_completed: int - 本轮 status=completed 的 role 数
    #   roles_failed: int - 本轮 status=failed 的 role 数
    collaboration_metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_num": self.round_num,
            "tasks": [t.to_dict() for t in self.tasks],
            "all_passed": self.all_passed,
            "failure_items": self.failure_items,
            "total_tokens": self.total_tokens,
            "summary": self.summary,
            "checker_report": self.checker_report,
            "role_violation_count": self.role_violation_count,
            "collaboration_metrics": self.collaboration_metrics,
        }


class OpenClawClient:
    """HTTP client for the OpenClaw Gateway API.

    The Gateway provides subagent.spawn(), sessions_send(), sessions_history()
    and related endpoints. When the gateway is unavailable, all operations
    gracefully degrade to return None / empty results.
    """

    def __init__(self, port: int | None = None, token: str | None = None) -> None:
        settings = get_settings()
        self.port = port or settings.openclaw_gateway_port
        self.token = token or settings.openclaw_gateway_token or ""
        self.base_url = f"http://localhost:{self.port}"

    def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any] | None:
        """Make an HTTP request to the gateway. Returns None on failure."""
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "hermes-orchestrator",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                return resp_data
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            OSError,
            json.JSONDecodeError,
            http.client.HTTPException,  # BadStatusLine, IncompleteRead, RemoteDisconnected
            socket.timeout,
        ) as exc:
            logger.debug("Gateway request failed: %s %s -> %s", method, path, exc)
            return None

    def health_check(self) -> bool:
        """Check if the gateway is reachable."""
        result = self._request("GET", "/api/health", timeout=5.0)
        return result is not None

    def spawn_agent(
        self,
        agent_file: str | None,
        task: str,
        context: str = "",
        model: str | None = None,
        isolated: bool = True,
        allowed_tools: list[str] | None = None,
        denylist: list[str] | None = None,
    ) -> str | None:
        """Spawn a sub-agent and return its session ID.

        Args:
            agent_file: Path to the agent definition .md file (e.g., builder.md)
            task: Task description to send to the agent
            context: Additional context (e.g., previous checker report)
            model: Override model (default: gateway's primary model)
            isolated: Whether to run in an isolated session
            allowed_tools: MCP 工具白名单（P0 分舱）。None=不限制；
                空列表=禁止所有 MCP；非空=只允许列出的工具。Gateway 可据此
                在 sub-agent 侧强制限制工具权限。
            denylist: L3 路径黑名单（Stage 6 安全强制执行）。非空时传入
                Gateway payload，Gateway 可在 sub-agent 侧拦截 Write/Edit 对
                受保护路径的修改。None 或空 = 不限制。Hermes 侧另有事后
                审计兜底（_audit_path_violations）。

        Returns:
            Session ID string, or None if the gateway is unavailable.
        """
        agent_content = ""
        if agent_file:
            agent_path = Path(agent_file)
            if agent_path.exists():
                agent_content = agent_path.read_text(encoding="utf-8")

        payload: dict[str, Any] = {
            "task": task,
            "context": context,
            "isolated": isolated,
        }
        if agent_content:
            payload["agent_definition"] = agent_content
        if model:
            payload["model"] = model
        if allowed_tools is not None:
            payload["allowed_tools"] = allowed_tools
        if denylist:  # Stage 6: 前向兼容——Gateway 支持则强制执行，不支持则忽略
            payload["denylist"] = denylist

        result = self._request("POST", "/api/subagent/spawn", data=payload, timeout=60.0)
        if result and "session_id" in result:
            session_id: str = result["session_id"]
            return session_id
        return None

    def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve messages from a session."""
        result = self._request("GET", f"/api/sessions/{session_id}/messages")
        if result and "messages" in result:
            messages: list[dict[str, Any]] = result["messages"]
            return messages
        return []

    def wait_for_completion(
        self,
        session_id: str,
        timeout: float = 300.0,
        poll_interval: float = 5.0,
    ) -> dict[str, Any] | None:
        """Poll a session until it completes or times out.

        Returns the final session state, or None on failure.
        """
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self._request("GET", f"/api/sessions/{session_id}", timeout=10.0)
            if result is None:
                return None
            status = result.get("status", "unknown")
            if status in ("completed", "failed", "error"):
                return result
            time.sleep(poll_interval)

        logger.warning("Session %s timed out after %.0fs", session_id, timeout)
        return None

    def send_message(self, session_id: str, message: str) -> bool:
        """Send a follow-up message to an existing session."""
        result = self._request(
            "POST",
            f"/api/sessions/{session_id}/send",
            data={"message": message},
        )
        return result is not None and result.get("ok", False)


class Orchestrator:
    """Fan-out/fan-in orchestrator for sub-agent execution.

    Coordinates parallel and sequential agent execution, aggregates results,
    and enforces the "don't filter" principle for checker reports.
    """

    def __init__(self, client: OpenClawClient | None = None) -> None:
        self.client = client or OpenClawClient()

    def is_available(self) -> bool:
        """Check if the orchestrator can actually execute agents."""
        return self.client.health_check()

    def fan_out(self, tasks: list[AgentTask]) -> list[AgentTask]:
        """Spawn all tasks (parallel ones simultaneously, sequential in order).

        Updates each task's session_id and status.
        P0: 自动按角色填充 MCP 工具白名单并传入 Gateway payload。
        """
        parallel_tasks = [t for t in tasks if t.parallel]
        sequential_tasks = [t for t in tasks if not t.parallel]

        # Spawn parallel tasks
        for task in parallel_tasks:
            self._prepare_and_spawn(task)

        # Spawn sequential tasks (only after previous sequential completes)
        for task in sequential_tasks:
            self._prepare_and_spawn(task)

        return tasks

    def _prepare_and_spawn(self, task: AgentTask) -> None:
        """填充默认白名单并 spawn 单个 task（P0 分舱 + Stage 6 denylist）。"""
        # 白名单未显式指定时，按角色填充默认值
        if task.allowed_mcp_tools is None:
            task.allowed_mcp_tools = _get_role_whitelist(task.role)

        task.started_at = datetime.now(timezone.utc).isoformat()
        task.status = "running"
        session_id = self.client.spawn_agent(
            agent_file=task.agent_file,
            task=task.task_description,
            context=task.context,
            allowed_tools=task.allowed_mcp_tools,
            denylist=task.denylist or None,
        )
        task.session_id = session_id
        if session_id is None:
            task.status = "failed"
            task.result = "Gateway unavailable"
        logger.info(
            "Spawned agent: %s -> session=%s (allowed_mcp_tools=%s)",
            task.role, session_id, task.allowed_mcp_tools,
        )

    def fan_in(self, tasks: list[AgentTask], timeout: float = 300.0) -> list[AgentTask]:
        """Wait for all spawned tasks to complete and collect results.

        Updates each task's result, status, and tokens_used.
        P0: 完成后审计 MCP 工具调用，检测角色越权。
        """
        for task in tasks:
            if task.status == "failed" or task.session_id is None:
                continue

            result = self.client.wait_for_completion(task.session_id, timeout=timeout)
            task.completed_at = datetime.now(timezone.utc).isoformat()

            if result is None:
                task.status = "failed"
                task.result = "Timeout or gateway error"
            else:
                task.status = "completed" if result.get("status") == "completed" else "failed"
                messages = self.client.get_session_messages(task.session_id)
                # Extract the last assistant message as the result
                assistant_msgs = [
                    m for m in messages if m.get("role") == "assistant"
                ]
                if assistant_msgs:
                    task.result = assistant_msgs[-1].get("content", "")
                else:
                    task.result = result.get("output", "")
                task.tokens_used = result.get("tokens_used", 0)
                # P1: token 上限熔断检查
                # token_limit > 0 时启用；超限即标记 failed，防止单 agent 烧光预算。
                # 由 _check_token_limit 集中处理，便于复用与测试覆盖。
                self._check_token_limit(task)
                # P0: 审计 MCP 工具调用违规
                self._audit_mcp_violations(task, messages)
                # Stage 6: 审计 denylist 路径违规（L3 安全强制执行）
                self._audit_path_violations(task, messages)

        return tasks

    @staticmethod
    def _check_token_limit(task: AgentTask) -> None:
        """检查单 agent token 使用是否超限。

        P1 熔断机制：超限时将 status 由 completed 改为 failed，
        并填充 result 提示。token_limit <= 0 表示不限制（向后兼容）。
        """
        if task.token_limit <= 0:
            return  # 不限制
        if task.tokens_used > task.token_limit:
            original_status = task.status
            task.status = "failed"
            task.result = (
                f"Token limit exceeded: used {task.tokens_used}, "
                f"limit {task.token_limit} (prior status={original_status})"
            )
            logger.warning(
                "Token 熔断: role=%s session=%s used=%d limit=%d",
                task.role, task.session_id, task.tokens_used, task.token_limit,
            )

    @staticmethod
    def _audit_mcp_violations(task: AgentTask, messages: list[dict[str, Any]]) -> None:
        """扫描 session 消息，检测 sub-agent 是否调用了不在白名单的 MCP 工具。

        检测两种信号：
        1. message 中的 tool_calls 字段（OpenAI 格式：function.name）
        2. message content 中的 "github.<method>" 模式（兜底，防 Gateway 不返回 tool_calls）

        发现违规则填充 task.mcp_violations，不强制改 status（由 aggregate_results 聚合）。
        """
        if task.allowed_mcp_tools is None:
            return  # 无白名单 = 不限制，跳过审计

        whitelist = set(task.allowed_mcp_tools)
        violations: list[str] = []

        for msg in messages:
            # 信号 1: tool_calls 字段（标准 OpenAI 格式）
            tool_calls = msg.get("tool_calls") or []
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                func = tc.get("function") or {}
                name = str(func.get("name", ""))
                if name and not name.startswith("mcp_"):
                    # 非 mcp_ 前缀的工具不审计（如内置 Read/Write）
                    continue
                if name and name not in whitelist:
                    violations.append(name)

            # 信号 2: content 中的 "github.<method>" 模式（兜底）
            content = str(msg.get("content", ""))
            for match in re.finditer(r"\bgithub\.(get_pr|get_issue|list_prs|post_pr_comment|create_pr)\b", content):
                tool = match.group(0)
                if tool not in whitelist:
                    violations.append(tool)

        task.mcp_violations = violations
        if violations:
            logger.warning(
                "MCP 违规: role=%s 调用了未授权工具 %s (白名单=%s)",
                task.role, violations, task.allowed_mcp_tools,
            )

    @staticmethod
    def _matches_denylist(path: str, denylist: list[str]) -> str | None:
        """检查文件路径是否命中 denylist pattern。

        匹配语义（与 LOOP_PATTERNS 中 denylist 的声明对齐）：
        - "auth/" → 目录前缀匹配（路径以 auth/ 开头或包含 /auth/）
        - ".env" → 精确文件名匹配（basename 等于 .env）
        - "*.key" → glob 后缀匹配（fnmatch）
        - "CHANGELOG.md" → 精确文件名匹配

        返回命中的 pattern（便于审计日志），未命中返回 None。
        """
        if not path or not denylist:
            return None
        # 规范化：统一用 / 分隔，去除前导 ./（注意不能用 lstrip——它是字符类剥离，
        # 会把 ".env" 错误地剥成 "env"）。只剥离字面量 "./" 前缀。
        clean = path.replace("\\", "/")
        if clean.startswith("./"):
            clean = clean[2:]
        pure = PurePosixPath(clean)
        basename = pure.name
        full = str(pure)

        for pattern in denylist:
            if not pattern:
                continue
            # 目录前缀：pattern 以 / 结尾（如 "auth/"）
            if pattern.endswith("/"):
                prefix = pattern.rstrip("/")
                if full == prefix or full.startswith(prefix + "/") or f"/{prefix}/" in f"/{full}":
                    return pattern
                continue
            # glob：pattern 含 * 或 ?（如 "*.key"）
            if "*" in pattern or "?" in pattern:
                if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(full, pattern):
                    return pattern
                continue
            # 精确匹配：basename 或 full 等于 pattern（如 ".env", "CHANGELOG.md"）
            if basename == pattern or full == pattern:
                return pattern
        return None

    @staticmethod
    def _audit_path_violations(task: AgentTask, messages: list[dict[str, Any]]) -> None:
        """扫描 session 消息中 Write/Edit 类工具调用，检查路径是否命中 denylist。

        Stage 6 L3 安全强制执行：builder 等有 Write 权限的 role 若修改了
        denylist 保护的路径（auth/ payment/ security/ .env *.key），
        记录 path_violation。aggregate_results 据此强制 builder failed。

        检测信号：
        1. tool_calls 中的 Write/Edit/MultiEdit 调用，解析 file_path/path 参数
        2. content 中 "<function=name>" + 路径模式（兜底，防 Gateway 不返回 tool_calls）

        仅当 task.denylist 非空时审计（空 = 不限制，向后兼容）。
        """
        if not task.denylist:
            return  # 无 denylist = 不限制，跳过审计

        # 只审计有 Write 权限的 role（builder / synthesizer / perspective_*）
        # checker 系列无 Write 权限（MCP 白名单已限制），跳过以省开销
        if task.role.startswith("checker"):
            return

        violations: list[str] = []
        # Write/Edit 类工具名集合（匹配内置工具 +可能的变体）
        write_tools = {"write", "edit", "multiedit", "str_replace_editor", "create_file"}

        for msg in messages:
            # 信号 1: tool_calls 字段
            tool_calls = msg.get("tool_calls") or []
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                func = tc.get("function") or {}
                name = str(func.get("name", "")).lower()
                if not name:
                    continue
                # 只看 Write/Edit 类工具（Read/Grep/Glob 不审计）
                tool_basename = name.split(".")[-1]  # 处理 "mcp_xx.write" 形式
                if tool_basename not in write_tools and name not in write_tools:
                    continue
                # 解析 path 参数（多种可能字段名）
                args_raw = func.get("arguments")
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw)
                    except (json.JSONDecodeError, ValueError):
                        args = {}
                elif isinstance(args_raw, dict):
                    args = args_raw
                else:
                    args = {}
                path = (
                    args.get("file_path") or args.get("path")
                    or args.get("filename") or ""
                )
                if not isinstance(path, str):
                    path = str(path)
                hit = Orchestrator._matches_denylist(path, task.denylist)
                if hit:
                    violations.append(f"{name}: {path} (matched: {hit})")

            # 信号 2: content 中的 Write/Edit 路径（兜底）
            content = str(msg.get("content", ""))
            # 匹配 "Write" / "Edit" 工具调用块中出现的路径
            for match in re.finditer(
                r"\b(?:Write|Edit|MultiEdit|create_file)\b[^\n]*?['\"]([^'\"]+\.(?:py|js|ts|md|json|env|key|yml|yaml|toml|cfg|sh|txt))['\"]",
                content,
            ):
                path = match.group(1)
                hit = Orchestrator._matches_denylist(path, task.denylist)
                if hit:
                    violations.append(f"content-path: {path} (matched: {hit})")

        task.path_violations = violations
        if violations:
            logger.warning(
                "路径违规: role=%s 修改了受保护路径 %s (denylist=%s)",
                task.role, violations, task.denylist,
            )

    def aggregate_results(
        self,
        tasks: list[AgentTask],
        round_num: int,
    ) -> RoundResult:
        """Aggregate task results into a RoundResult.

        Applies the "don't filter" principle: checker reports are passed
        through verbatim, not interpreted or summarized.

        Failure extraction uses a structured protocol — checker.md templates
        ask the checker to emit a JSON block:
            <!-- failures:json -->
            {"passed": false, "failures": [{"file": "src/a.py", "line": 42, "type": "ImportError"}]}
            <!-- /failures -->
        When present, failures are parsed into normalized ``(file, type)``
        keys so stop-rule set comparison survives line-number drift (a builder
        editing an earlier line shifts line numbers without changing the
        underlying failure). When absent, the checker's full report is used
        as a single failure item (no heuristic line-guessing).
        """
        total_tokens = sum(t.tokens_used for t in tasks)

        # Collect checker reports (verbatim, no filtering)
        checker_reports: list[str] = []
        failure_items: list[str] = []
        all_passed = True

        # P2 协作指标采集：分角色追踪 builder/checker 失败信号
        builder_failed = False
        checker_failed_signal = False  # 任何 checker 输出非 ALL GREEN
        checker_passed_signal = False  # 任何 checker 输出 ALL GREEN
        token_by_role: dict[str, int] = {}
        roles_completed = 0
        roles_failed = 0

        for task in tasks:
            # P2: token 归因 + role 计数（所有 role 都参与）
            token_by_role[task.role] = token_by_role.get(task.role, 0) + task.tokens_used
            if task.status == "completed":
                roles_completed += 1
            elif task.status == "failed":
                roles_failed += 1

            if task.role.startswith("checker") or task.role == "checker":
                # Red line: never report success without checker output.
                if not task.result:
                    all_passed = False
                    checker_failed_signal = True
                    checker_reports.append(
                        f"### {task.role}\n[CHECKER PRODUCED NO OUTPUT]"
                    )
                    failure_items.append(f"{task.role}: [NO OUTPUT]")
                    continue
                checker_reports.append(f"### {task.role}\n{task.result}")
                result_upper = task.result.upper()
                if "ALL GREEN" in result_upper:
                    # Explicit success signal from this checker (protocol, not interpretation).
                    checker_passed_signal = True
                    continue
                # Any non-empty, non-ALL-GREEN checker output is a failure.
                all_passed = False
                checker_failed_signal = True
                # Prefer structured failure protocol; fall back to verbatim report.
                structured = _parse_structured_failures(task.result, task.role)
                failure_items.extend(structured)
            elif task.role == "builder":
                # Stage 6: denylist 路径违规 → 强制 failed（安全红线）
                if task.path_violations:
                    all_passed = False
                    builder_failed = True
                    for pv in task.path_violations:
                        failure_items.append(f"builder: DENYLIST VIOLATION — {pv}")
                if task.status == "failed":
                    all_passed = False
                    builder_failed = True

        # If no checker tasks, use builder status
        checker_tasks = [t for t in tasks if t.role.startswith("checker")]
        if not checker_tasks:
            all_passed = all(t.status == "completed" for t in tasks)

        # P2: 统计 MCP 角色违规调用总数
        role_violation_count = sum(len(t.mcp_violations) for t in tasks)
        # Stage 6: 统计 denylist 路径违规总数
        path_violation_count = sum(len(t.path_violations) for t in tasks)

        # P2: 计算协作评估指标
        collaboration_metrics = self._compute_collaboration_metrics(
            builder_failed=builder_failed,
            checker_failed_signal=checker_failed_signal,
            checker_passed_signal=checker_passed_signal,
            has_checker=bool(checker_tasks),
            token_by_role=token_by_role,
            roles_completed=roles_completed,
            roles_failed=roles_failed,
            role_violation_count=role_violation_count,
        )

        checker_report = "\n\n".join(checker_reports) if checker_reports else ""
        summary_parts = [f"Round {round_num}: {len(tasks)} agents executed"]
        summary_parts.append(f"Status: {'ALL GREEN' if all_passed else 'FAILED'}")
        summary_parts.append(f"Tokens: {total_tokens:,}")
        if failure_items:
            summary_parts.append(f"Failures: {len(failure_items)}")
        if role_violation_count:
            summary_parts.append(f"MCP violations: {role_violation_count}")
        if path_violation_count:
            summary_parts.append(f"Path violations: {path_violation_count}")
        attribution = collaboration_metrics.get("failure_attribution", "none")
        if attribution != "none":
            summary_parts.append(f"Attribution: {attribution}")
        summary = " | ".join(summary_parts)

        # 工具自愈：分析失败模式，附加恢复建议。
        # 关键原则："不过滤"原则不变——原始失败信息原样保留在 failure_items 中，
        # 恢复建议只作为附加内容追加到 summary 末尾，帮 builder 下一轮避免重复踩坑。
        if failure_items:
            diagnostics = analyze_failures(failure_items)
            recovery_section = format_recovery_section(diagnostics)
            if recovery_section:
                summary = f"{summary}\n{recovery_section}"

        return RoundResult(
            round_num=round_num,
            tasks=tasks,
            all_passed=all_passed,
            failure_items=failure_items,
            total_tokens=total_tokens,
            summary=summary,
            checker_report=checker_report,
            role_violation_count=role_violation_count,
            collaboration_metrics=collaboration_metrics,
        )

    @staticmethod
    def _compute_collaboration_metrics(
        *,
        builder_failed: bool,
        checker_failed_signal: bool,
        checker_passed_signal: bool,
        has_checker: bool,
        token_by_role: dict[str, int],
        roles_completed: int,
        roles_failed: int,
        role_violation_count: int,
    ) -> dict[str, Any]:
        """计算 multi-agent 协作评估指标。

        设计原则（第一性原理）：
        - 指标必须可观测且可归因：不能只报"失败了"，要报"谁导致失败"。
        - failure_attribution 互斥分类：builder / checker / mixed / none。
          - builder 自身 failed（如 token 熔断）→ "builder"
          - builder 完成但 checker 报失败 → "checker"（修复未达标）
          - 两者都有失败信号 → "mixed"
          - 全部通过 → "none"
        - checker_builder_agreement 三态：True/False/None。
          None 表示无 checker 或 builder 已 failed（无法判断 agreement）。
        """
        # failure_attribution 互斥判定
        if builder_failed and checker_failed_signal:
            attribution = "mixed"
        elif builder_failed:
            attribution = "builder"
        elif checker_failed_signal:
            attribution = "checker"
        else:
            attribution = "none"

        # checker_builder_agreement：只在 builder 成功 + 有 checker 时才有意义
        if not has_checker or builder_failed:
            agreement: bool | None = None
        else:
            # checker 全部 ALL GREEN 才算 agree；任何一个非 ALL GREEN 即 disagree
            agreement = checker_passed_signal and not checker_failed_signal

        return {
            "token_by_role": dict(token_by_role),
            "failure_attribution": attribution,
            "checker_builder_agreement": agreement,
            "roles_completed": roles_completed,
            "roles_failed": roles_failed,
            "role_violation_count": role_violation_count,
        }

    def run_builder_checker_round(
        self,
        loop_dir: Path,
        round_num: int,
        builder_task: str,
        checker_context: str = "",
        parallel_checks: bool = True,
        denylist: list[str] | None = None,
    ) -> RoundResult:
        """Execute one builder-checker round.

        1. Spawn builder with the task
        2. Wait for builder to complete
        3. Spawn checker(s) to verify (parallel if enabled)
        4. Aggregate results (don't filter checker report)

        Stage 6: denylist 非空时注入 builder AgentTask，fan_in 审计 Write/Edit
        路径违规，命中受保护路径（auth/ payment/ security/ .env *.key）强制
        builder failed。checker 无 Write 权限，不注入 denylist。
        """
        builder_file = str(loop_dir / "builder.md")
        checker_file = str(loop_dir / "checker.md")

        # Phase 1: Builder
        builder = AgentTask(
            role="builder",
            agent_file=builder_file,
            task_description=builder_task,
            context=checker_context,  # Previous checker report (raw, unfiltered)
            parallel=False,
            denylist=denylist or [],
        )

        tasks = [builder]
        self.fan_out(tasks)
        self.fan_in(tasks, timeout=600.0)

        if builder.status == "failed":
            return self.aggregate_results(tasks, round_num)

        # Phase 2: Checker(s)
        if parallel_checks:
            checker_tasks = [
                AgentTask(
                    role="checker_lint",
                    agent_file=checker_file,
                    task_description="Run lint checks only. Report ALL GREEN or FAILED with details.",
                    context=f"Check type: lint\nProject: {loop_dir}",
                    parallel=True,
                    check_type="lint",
                ),
                AgentTask(
                    role="checker_type",
                    agent_file=checker_file,
                    task_description="Run type checks only (tsc/mypy). Report ALL GREEN or FAILED with details.",
                    context=f"Check type: typecheck\nProject: {loop_dir}",
                    parallel=True,
                    check_type="typecheck",
                ),
                AgentTask(
                    role="checker_test",
                    agent_file=checker_file,
                    task_description="Run tests only. Report ALL GREEN or FAILED with details.",
                    context=f"Check type: test\nProject: {loop_dir}",
                    parallel=True,
                    check_type="test",
                ),
            ]
        else:
            checker_tasks = [
                AgentTask(
                    role="checker",
                    agent_file=checker_file,
                    task_description="Run ALL checks (lint, typecheck, test). Report ALL GREEN or FAILED with details.",
                    context=f"Project: {loop_dir}",
                    parallel=False,
                ),
            ]

        self.fan_out(checker_tasks)
        self.fan_in(checker_tasks, timeout=300.0)

        all_tasks = [builder] + checker_tasks
        return self.aggregate_results(all_tasks, round_num)

    def run_parallel_perspectives(
        self,
        loop_dir: Path,
        round_num: int,
        subject: str,
        perspectives: list[dict[str, str]],
    ) -> RoundResult:
        """借鉴 ai-berkshire：N 个 perspective agent 并行分析，synthesizer 汇总。

        与 run_builder_checker_round 的区别：
        - 无 builder 阶段，全部 perspective agent parallel=True 同消息 spawn
        - synthesizer 在所有 perspective 完成后串行执行，读取全部结果汇总
        - 产出 deliverable（summary.md），含 <!-- conclusion: --> 标记

        Args:
            loop_dir: Loop 工作目录（含 perspective.md / summary.md）
            round_num: 当前轮次
            subject: 分析标的描述
            perspectives: [{"role": "perspective_1", "lens": "护城河视角"}, ...]
        """
        perspective_file = str(loop_dir / "perspective.md")
        summary_file = str(loop_dir / "summary.md")

        # Phase 1: N 个 perspective agent 并行（fan-out）
        perspective_tasks: list[AgentTask] = []
        for p in perspectives:
            role = p.get("role", "perspective")
            lens = p.get("lens", "通用视角")
            perspective_tasks.append(AgentTask(
                role=role,
                agent_file=perspective_file,
                task_description=(
                    f"分析标的：{subject}\n\n"
                    f"你的视角：{lens}\n\n"
                    "按 perspective.md 的汇报格式输出分析结果，"
                    "包含 Bull/Bear 各 3-5 条，以及至少 2 条 <!-- claim: --> 断言。"
                ),
                parallel=True,
            ))

        self.fan_out(perspective_tasks)
        self.fan_in(perspective_tasks, timeout=300.0)

        # Phase 2: synthesizer 串行汇总（fan-out 单任务）
        # 把所有 perspective 结果拼接为 context
        perspective_results: list[str] = []
        for task in perspective_tasks:
            result_text = task.result or "[NO OUTPUT]"
            perspective_results.append(f"### {task.role}\n{result_text}")

        synthesizer_context = (
            f"分析标的：{subject}\n\n"
            "以下是各视角 agent 的分析结果：\n\n"
            + "\n\n".join(perspective_results)
        )

        synthesizer = AgentTask(
            role="synthesizer",
            agent_file=summary_file,
            task_description=(
                "汇总以下各视角分析结果，写入 summary.md 文件。"
                "必须包含 <!-- conclusion: --> 标记给出明确结论。"
            ),
            context=synthesizer_context,
            parallel=False,
        )

        self.fan_out([synthesizer])
        self.fan_in([synthesizer], timeout=300.0)

        all_tasks = perspective_tasks + [synthesizer]
        return self.aggregate_results(all_tasks, round_num)

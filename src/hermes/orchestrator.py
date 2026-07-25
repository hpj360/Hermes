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

import http.client
import json
import logging
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes.config import get_settings

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
        """填充默认白名单并 spawn 单个 task（P0 分舱）。"""
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

        for task in tasks:
            if task.role.startswith("checker") or task.role == "checker":
                # Red line: never report success without checker output.
                if not task.result:
                    all_passed = False
                    checker_reports.append(
                        f"### {task.role}\n[CHECKER PRODUCED NO OUTPUT]"
                    )
                    failure_items.append(f"{task.role}: [NO OUTPUT]")
                    continue
                checker_reports.append(f"### {task.role}\n{task.result}")
                result_upper = task.result.upper()
                if "ALL GREEN" in result_upper:
                    # Explicit success signal from this checker (protocol, not interpretation).
                    continue
                # Any non-empty, non-ALL-GREEN checker output is a failure.
                all_passed = False
                # Prefer structured failure protocol; fall back to verbatim report.
                structured = _parse_structured_failures(task.result, task.role)
                failure_items.extend(structured)
            elif task.role == "builder":
                if task.status == "failed":
                    all_passed = False

        # If no checker tasks, use builder status
        checker_tasks = [t for t in tasks if t.role.startswith("checker")]
        if not checker_tasks:
            all_passed = all(t.status == "completed" for t in tasks)

        # P2: 统计 MCP 角色违规调用总数
        role_violation_count = sum(len(t.mcp_violations) for t in tasks)

        checker_report = "\n\n".join(checker_reports) if checker_reports else ""
        summary_parts = [f"Round {round_num}: {len(tasks)} agents executed"]
        summary_parts.append(f"Status: {'ALL GREEN' if all_passed else 'FAILED'}")
        summary_parts.append(f"Tokens: {total_tokens:,}")
        if failure_items:
            summary_parts.append(f"Failures: {len(failure_items)}")
        if role_violation_count:
            summary_parts.append(f"MCP violations: {role_violation_count}")
        summary = " | ".join(summary_parts)

        return RoundResult(
            round_num=round_num,
            tasks=tasks,
            all_passed=all_passed,
            failure_items=failure_items,
            total_tokens=total_tokens,
            summary=summary,
            checker_report=checker_report,
            role_violation_count=role_violation_count,
        )

    def run_builder_checker_round(
        self,
        loop_dir: Path,
        round_num: int,
        builder_task: str,
        checker_context: str = "",
        parallel_checks: bool = True,
    ) -> RoundResult:
        """Execute one builder-checker round.

        1. Spawn builder with the task
        2. Wait for builder to complete
        3. Spawn checker(s) to verify (parallel if enabled)
        4. Aggregate results (don't filter checker report)
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

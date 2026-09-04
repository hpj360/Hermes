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

import hashlib
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
from hermes.path_policy import matches_denylist
from hermes.presets import apply_prompt_sections, merged_presets, resolve_preset
# Structured failure protocol 解析已下沉到 hermes.rubric（单一事实源）：
# fan-in 审计与 Rubric 评分共用同一实现，语义漂移结构性杜绝。
from hermes.rubric import parse_structured_failures as _parse_structured_failures
from hermes.rubric import score_reports as _score_reports
from hermes.tool_recovery import analyze_failures, format_recovery_section
from hermes.trajectory import TrajectoryDesyncError, TrajectoryLogger
from hermes.workbench.errors import ValidationError

logger = logging.getLogger("hermes.orchestrator")


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


def _role_model(role: str) -> str | None:
    """P0-3: 按 role 映射差异化模型（配置化，空 = 回退默认模型）。

    checker* 前缀匹配；builder 与 perspective_*（对抗性审查角色，能力
    需求与 builder 相当）走 builder 模型；其余未知角色不覆盖。
    """
    s = get_settings()
    if role.startswith("checker"):
        return s.hermes_llm_model_checker or None
    if role == "builder" or role.startswith("perspective"):
        return s.hermes_llm_model_builder or None
    if role == "synthesizer":
        return s.hermes_llm_model_synthesizer or None
    return None


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
    # Stage 2 (ADR-0018)：能力面收窄。
    # preset: 命名的 AgentPreset；tools: 内置工具白名单（None=不限制）；
    # model: 模型覆盖；isolated: 是否隔离会话（默认 True，与旧 spawn_agent 一致）。
    preset: str | None = None
    tools: list[str] | None = None
    model: str | None = None
    isolated: bool = True
    # fan_in 审计后填充：检测到的越权内置工具调用列表。
    tool_violations: list[str] = field(default_factory=list)
    # ADR-0017：本轮轮次号（轨迹事件关联键，写入 to_dict 与 dispatch 事件）。
    round_num: int = 0
    # ADR-0017：transient 轨迹关联键（不进 to_dict、不入 Gateway payload）。
    trajectory_request_seq: int | None = field(default=None, repr=False, compare=False)

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
            "preset": self.preset,
            "tools": self.tools,
            "model": self.model,
            "isolated": self.isolated,
            "tool_violations": self.tool_violations,
            "round_num": self.round_num,
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
    # P1-A 评估资产化：本轮 checker 报告按版本化 Rubric 的加权评分
    # （final_score ∈ [0,1] + per-metric 证据 + rubric 版本）。
    # None 表示本轮无 checker 报告可评。
    rubric_score: dict[str, Any] | None = None

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
            "rubric_score": self.rubric_score,
        }


def _build_spawn_payload(
    task: AgentTask, preset: Any = None
) -> dict[str, Any]:
    """Build the Gateway ``/api/subagent/spawn`` payload from a task.

    This is the single construction point for the dispatch payload (ADR-0017):
    any field that affects the model's upstream context must be assembled here
    so the trajectory snapshot and the dispatched payload can never diverge.
    ``preset`` (the *resolved* preset, if any) contributes prompt sections to
    ``agent_definition``.
    """
    agent_content = ""
    if task.agent_file:
        agent_path = Path(task.agent_file)
        if agent_path.exists():
            agent_content = agent_path.read_text(encoding="utf-8")

    if preset is not None and preset.prompt_sections:
        agent_content = apply_prompt_sections(agent_content, preset)

    payload: dict[str, Any] = {
        "task": task.task_description,
        "context": task.context,
        "isolated": task.isolated,
    }
    if agent_content:
        payload["agent_definition"] = agent_content
    if task.model:
        payload["model"] = task.model
    if task.allowed_mcp_tools is not None:
        payload["allowed_tools"] = task.allowed_mcp_tools
    if task.tools is not None:
        payload["allowed_builtin_tools"] = task.tools
    if task.denylist:
        payload["denylist"] = task.denylist
    return payload


def _agent_file_sha256(agent_file: str | None) -> str | None:
    """Return the sha256 of an agent file's raw content (for trajectory verify).

    Used by the dispatch trajectory to let offline verification distinguish the
    original agent file (unchanged by preset prompt_sections) from the final
    ``agent_definition`` that is dispatched.
    """
    if not agent_file:
        return None
    path = Path(agent_file)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        task_obj = AgentTask(
            role="legacy",
            agent_file=agent_file,
            task_description=task,
            context=context,
            model=model,
            isolated=isolated,
            allowed_mcp_tools=allowed_tools,
            denylist=list(denylist) if denylist else [],
        )
        payload = _build_spawn_payload(task_obj)
        return self.spawn_payload(payload)

    def spawn_payload(self, payload: dict[str, Any]) -> str | None:
        """Spawn a sub-agent from an already-built payload dict.

        Returns the session ID, or None if the gateway is unavailable. This is
        the single HTTP entry point for dispatch (ADR-0017); ``spawn_agent``
        delegates here after building the payload.
        """
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

    def check_session(self, session_id: str) -> dict[str, Any] | None:
        """Single non-blocking status probe for a session.

        steering 轮询路径（P2 轮内 steering）使用：每次只发一次 GET，
        把"等待"拆成可插入指令的小片段。返回原始 session 状态 dict，
        网关不可达返回 None（与 wait_for_completion 的失败语义一致）。
        """
        return self._request("GET", f"/api/sessions/{session_id}", timeout=10.0)

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


# ---------------------------------------------------------------------------
# P2 轮内 steering（借鉴 NousResearch hermes-agent v0.21 live steering）
# ---------------------------------------------------------------------------


@dataclass
class SteeringCommand:
    """一条下达给运行中子 Agent 的指令。

    action 语义：
    - ``message``：中途纠偏——把 text 注入运行中的 session（不影响状态机）
    - ``stop``：提前止损——中断等待，保留部分结果（task.status="stopped"）
    """

    action: str  # "message" | "stop"
    text: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if self.action not in ("message", "stop"):
            raise ValueError(f"invalid steering action: {self.action!r}")


# steering 轮询间隔（秒）。测试可 monkeypatch 缩短。
STEERING_POLL_INTERVAL = 2.0


class SteeringController:
    """fan_out 之后、fan_in 等待期间的中途指挥通道。

    外部（CLI / 路由 / 人）在另一个线程调用 steer()/stop() 下达指令；
    fan_in 的 steering 轮询在每个 poll 间隙 pop 并执行。

    key 寻址：指令按 key 排队。fan_out 之后 task.session_id 已知，
    精确寻址用 session_id；派发前（session_id 未知）可用
    ``role:<role>`` 广播键——fan_in 会先查 session_id 队列，再查
    role 队列。线程安全。
    """

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._commands: dict[str, list[SteeringCommand]] = {}

    @staticmethod
    def role_key(role: str) -> str:
        """派发前寻址用的 role 广播键（session_id 未知时）。"""
        return f"role:{role}"

    def steer(self, key: str, text: str, reason: str = "") -> None:
        """对运行中的子 Agent 注入中途纠偏消息。"""
        self._enqueue(key, SteeringCommand("message", text=text, reason=reason))

    def stop(self, key: str, reason: str = "") -> None:
        """提前停止子 Agent，保留部分结果。"""
        self._enqueue(key, SteeringCommand("stop", reason=reason))

    def _enqueue(self, key: str, cmd: SteeringCommand) -> None:
        with self._lock:
            self._commands.setdefault(key, []).append(cmd)

    def pop(self, *keys: str) -> SteeringCommand | None:
        """按优先级取出第一条指令（FIFO），无指令返回 None。

        多个 key（如 session_id 精确键 + role 广播键）按顺序探测，
        先到先得。
        """
        with self._lock:
            for key in keys:
                queue = self._commands.get(key)
                if queue:
                    cmd = queue.pop(0)
                    if not queue:
                        del self._commands[key]
                    return cmd
            return None


class Orchestrator:
    """Fan-out/fan-in orchestrator for sub-agent execution.

    Coordinates parallel and sequential agent execution, aggregates results,
    and enforces the "don't filter" principle for checker reports.
    """

    def __init__(
        self,
        client: OpenClawClient | None = None,
        trajectory: TrajectoryLogger | None = None,
    ) -> None:
        self.client = client or OpenClawClient()
        self.trajectory = trajectory

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
        """解析 preset、构造 payload、写轨迹并 spawn 单个 task。

        P0 分舱（MCP 白名单）+ Stage 2 preset 收窄（ADR-0018）+
        Stage 6 denylist + ADR-0017 派发轨迹不变量。
        """
        # Stage 2: 先解析 preset（显式字段 > preset > 角色默认）
        try:
            resolved_preset = resolve_preset(task, merged_presets())
        except ValidationError as exc:
            task.started_at = datetime.now(timezone.utc).isoformat()
            task.status = "failed"
            task.result = f"preset resolution failed: {exc}"
            logger.warning("Preset resolution failed for role=%s: %s", task.role, exc)
            # 未发生派发，不写 dispatch 轨迹（避免产生无配对 request 的孤儿 result）
            return

        # 白名单仍未指定时，按角色填充默认值
        if task.allowed_mcp_tools is None:
            task.allowed_mcp_tools = _get_role_whitelist(task.role)

        # P0-3: preset 也未指定 model 时，按角色映射差异化模型。
        # 优先级：显式 task.model > preset.model > 角色映射（> 网关默认）。
        if task.model is None:
            task.model = _role_model(task.role)

        task.started_at = datetime.now(timezone.utc).isoformat()
        task.status = "running"

        payload = _build_spawn_payload(task, preset=resolved_preset)

        # ADR-0017: 记录派发快照 + 可重建校验（fail loud）
        if self.trajectory is not None:
            try:
                request_seq = self.trajectory.record(
                    "dispatch/request",
                    {
                        "role": task.role,
                        "round_num": task.round_num,
                        "agent_file": task.agent_file,
                        "agent_file_sha256": _agent_file_sha256(task.agent_file),
                        "payload": payload,
                    },
                )
                task.trajectory_request_seq = request_seq
                self.trajectory.assert_reconstructable(request_seq, payload)
            except (TrajectoryDesyncError, OSError) as exc:
                task.status = "failed"
                task.result = f"trajectory invariant failed: {exc}"
                logger.warning(
                    "Trajectory invariant failed for role=%s: %s", task.role, exc
                )
                self._record_dispatch_result(task, None, "failed", 0)
                return

        session_id = self.client.spawn_payload(payload)
        task.session_id = session_id
        if session_id is None:
            task.status = "failed"
            task.result = "Gateway unavailable"
            self._record_dispatch_result(task, None, "failed", 0)
        logger.info(
            "Spawned agent: %s -> session=%s (allowed_mcp_tools=%s, tools=%s)",
            task.role, session_id, task.allowed_mcp_tools, task.tools,
        )

    def _record_dispatch_result(
        self,
        task: AgentTask,
        session_id: str | None,
        status: str,
        tokens_used: int,
    ) -> None:
        """补记 dispatch/result 轨迹事件（失败路径同样记录，保证配对完备）。"""
        if self.trajectory is None:
            return
        try:
            self.trajectory.record(
                "dispatch/result",
                {
                    "request_seq": task.trajectory_request_seq,
                    "role": task.role,
                    "round_num": task.round_num,
                    "session_id": session_id,
                    "status": status,
                    "tokens_used": tokens_used,
                    "completed_at": task.completed_at,
                },
            )
        except OSError:
            logger.warning("Failed to record dispatch/result for role=%s", task.role)

    def fan_in(
        self,
        tasks: list[AgentTask],
        timeout: float = 300.0,
        steering: SteeringController | None = None,
    ) -> list[AgentTask]:
        """Wait for all spawned tasks to complete and collect results.

        Updates each task's result, status, and tokens_used.
        P0: 完成后审计 MCP 工具调用，检测角色越权。
        ADR-0017: 完成后补记 dispatch/result 轨迹事件。
        P2 轮内 steering：steering 非空时改用分片轮询等待，poll 间隙
        消费 SteeringController 指令（message 中途纠偏 / stop 提前止损
        保留部分结果）。默认 None 走原阻塞等待路径，行为不变。
        """
        for task in tasks:
            if task.status == "failed" or task.session_id is None:
                continue

            if steering is None:
                result = self.client.wait_for_completion(
                    task.session_id, timeout=timeout
                )
                self._collect_task_result(task, result)
            else:
                self._fan_in_with_steering(task, timeout, steering)

        return tasks

    def _fan_in_with_steering(
        self,
        task: AgentTask,
        timeout: float,
        steering: SteeringController,
    ) -> None:
        """分片轮询等待单个 task，poll 间隙消费 steering 指令。

        与 wait_for_completion 的差异：单次探测失败（网关瞬断）不立即
        放弃，而是继续轮询到 deadline——中途指令的送达窗口因此更长。
        """
        import time

        assert task.session_id is not None  # fan_in 已过滤 None
        deadline = time.monotonic() + timeout
        stop_reason = ""
        result: dict[str, Any] | None = None
        while True:
            result = self.client.check_session(task.session_id)
            if (
                result is not None
                and result.get("status") in ("completed", "failed", "error")
            ):
                break
            cmd = steering.pop(
                task.session_id, SteeringController.role_key(task.role)
            )
            if cmd is not None:
                if cmd.action == "stop":
                    stop_reason = cmd.reason or "no reason given"
                    logger.info(
                        "Steering stop: role=%s session=%s reason=%s",
                        task.role, task.session_id, stop_reason,
                    )
                    break
                if self.client.send_message(task.session_id, cmd.text):
                    logger.info(
                        "Steering message delivered: role=%s session=%s",
                        task.role, task.session_id,
                    )
                else:
                    logger.warning(
                        "Steering message delivery failed: role=%s session=%s",
                        task.role, task.session_id,
                    )
            if time.monotonic() >= deadline:
                result = None
                break
            time.sleep(STEERING_POLL_INTERVAL)
        self._collect_task_result(task, result, stop_reason=stop_reason)

    def _collect_task_result(
        self,
        task: AgentTask,
        result: dict[str, Any] | None,
        stop_reason: str = "",
    ) -> None:
        """从网关终态收集单个 task 的结果（含 steering 停止路径）。

        stop_reason 非空表示被 steering 提前停止：保留部分结果（最后的
        assistant 消息）+ 停止原因，status 标记为 "stopped"。部分消息
        同样过 L3 三重审计——部分结果不等于免检。
        """
        assert task.session_id is not None  # fan_in 已过滤 None
        task.completed_at = datetime.now(timezone.utc).isoformat()

        if stop_reason:
            task.status = "stopped"
            messages = self.client.get_session_messages(task.session_id)
            assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
            partial = (
                assistant_msgs[-1].get("content", "") if assistant_msgs else ""
            )
            task.result = f"[STOPPED BY STEERING: {stop_reason}]\n{partial}"
            task.tokens_used = 0
            self._audit_mcp_violations(task, messages)
            self._audit_builtin_tool_violations(task, messages)
            self._audit_path_violations(task, messages)
            self._record_dispatch_result(task, task.session_id, "stopped", 0)
            return

        if result is None:
            task.status = "failed"
            task.result = "Timeout or gateway error"
            self._record_dispatch_result(task, task.session_id, "failed", 0)
            return

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
        # Stage 2: 审计内置工具越权（ADR-0018 兜底审计）
        self._audit_builtin_tool_violations(task, messages)
        # Stage 6: 审计 denylist 路径违规（L3 安全强制执行）
        self._audit_path_violations(task, messages)
        self._record_dispatch_result(
            task, task.session_id, task.status, task.tokens_used
        )

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
    def _audit_builtin_tool_violations(
        task: AgentTask, messages: list[dict[str, Any]]
    ) -> None:
        """扫描 session 消息，检测 sub-agent 是否调用了 preset 之外的**内置**工具。

        ADR-0018 兜底审计：preset 的 ``tools``（内置工具白名单）传入 Gateway
        是前向兼容的；Gateway 不支持时由本审计在 fan_in 兜底。只审计非 ``mcp_``
        前缀的 tool_calls（``mcp_`` 由 :meth:`_audit_mcp_violations` 负责）。
        """
        if task.tools is None:
            return  # 无内置工具白名单 = 不限制，跳过审计

        whitelist = set(task.tools)
        violations: list[str] = []
        for msg in messages:
            tool_calls = msg.get("tool_calls") or []
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                func = tc.get("function") or {}
                name = str(func.get("name", ""))
                if not name:
                    continue
                if name.startswith("mcp_"):
                    continue  # MCP 工具走 MCP 审计
                if name not in whitelist:
                    violations.append(name)

        task.tool_violations = violations
        if violations:
            logger.warning(
                "内置工具违规: role=%s 调用了未授权工具 %s (tools=%s)",
                task.role, violations, task.tools,
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

        实现委托 :func:`hermes.path_policy.matches_denylist`（单一事实源），
        与 gepa_redteam 红队回归共用同一实现，杜绝语义漂移。
        """
        return matches_denylist(path, denylist)

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
        # P1-A: role → raw report，供 Rubric 加权评分（评分用原始文本，
        # 不含 fan-in 拼接的 "### role" 头，避免污染结构化协议解析）
        reports_by_role: dict[str, str] = {}
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
                reports_by_role[task.role] = task.result
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
        # Stage 2: 统计内置工具越权调用总数（ADR-0018 兜底审计，计入 summary 可见）
        tool_violation_count = sum(len(t.tool_violations) for t in tasks)

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
        if tool_violation_count:
            summary_parts.append(f"Tool violations: {tool_violation_count}")
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

        # P1-A 评估资产化：对本轮 checker 报告按版本化 Rubric 加权评分。
        # 有 checker 报告才评分（无 checker 的 round 维持 None，不伪造分数）。
        rubric_score_dict: dict[str, Any] | None = None
        if reports_by_role:
            rubric_score_dict = _score_reports(reports_by_role).to_dict()

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
            rubric_score=rubric_score_dict,
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

    def steer(self, task: AgentTask, message: str) -> bool:
        """对运行中的子 Agent 注入中途纠偏消息（直达网关，不经队列）。

        适用于 fan_in(steering=...) 轮询路径之外的即时纠偏——队列化
        指令由 fan_in 消费；本方法立即送达。网关不可达返回 False。
        """
        if task.session_id is None:
            return False
        return self.client.send_message(task.session_id, message)

    def run_builder_checker_round(
        self,
        loop_dir: Path,
        round_num: int,
        builder_task: str,
        checker_context: str = "",
        parallel_checks: bool = True,
        denylist: list[str] | None = None,
        steering: SteeringController | None = None,
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
            round_num=round_num,
        )

        tasks = [builder]
        self.fan_out(tasks)
        self.fan_in(tasks, timeout=600.0, steering=steering)

        # steering 止损（"stopped"）与失败同样跳过 checker——用户已主动
        # 放弃本轮，继续 spawn checker 只会烧预算。
        if builder.status in ("failed", "stopped"):
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
                    round_num=round_num,
                ),
                AgentTask(
                    role="checker_type",
                    agent_file=checker_file,
                    task_description="Run type checks only (tsc/mypy). Report ALL GREEN or FAILED with details.",
                    context=f"Check type: typecheck\nProject: {loop_dir}",
                    parallel=True,
                    check_type="typecheck",
                    round_num=round_num,
                ),
                AgentTask(
                    role="checker_test",
                    agent_file=checker_file,
                    task_description="Run tests only. Report ALL GREEN or FAILED with details.",
                    context=f"Check type: test\nProject: {loop_dir}",
                    parallel=True,
                    check_type="test",
                    round_num=round_num,
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
                    round_num=round_num,
                ),
            ]

        self.fan_out(checker_tasks)
        self.fan_in(checker_tasks, timeout=300.0, steering=steering)

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
                round_num=round_num,
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
            round_num=round_num,
        )

        self.fan_out([synthesizer])
        self.fan_in([synthesizer], timeout=300.0)

        all_tasks = perspective_tasks + [synthesizer]
        return self.aggregate_results(all_tasks, round_num)

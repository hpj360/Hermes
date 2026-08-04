"""工具自愈：分析工具调用失败模式，提供诊断和恢复建议。

借鉴 Hermes Agent v0.20.0 的 "Tools that fix themselves" 能力，
适配为控制平面层的失败诊断模块。不直接执行工具，
而是分析 sub-agent 报告的工具失败，给出可操作的恢复建议。

集成点：orchestrator.aggregate_results 在聚合结果时调用 analyze_failures，
将恢复建议附加到 failure_items 中，帮 builder 下一轮避免重复踩坑。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FailurePattern:
    """已知失败模式定义。

    Attributes:
        pattern_id: 稳定标识符（如 "terminal_output_truncated"）。
        name: 人类可读名称。
        description: 失败模式的一句话描述。
        signals: 正则表达式列表，任一命中即判定该模式匹配（大小写不敏感）。
        recovery_hint: 可操作的恢复建议文本。
        severity: 严重程度，"high" / "medium" / "low"。
    """

    pattern_id: str
    name: str
    description: str
    signals: list[str]
    recovery_hint: str
    severity: str


@dataclass
class FailureDiagnostic:
    """单条失败项的诊断结果。

    Attributes:
        original_error: 原始失败文本（原样保留，不修改）。
        matched_pattern: 命中的失败模式；未匹配任何模式时为 None。
        recovery_hint: 恢复建议。命中模式时取自 matched_pattern.recovery_hint；
            未命中时为空字符串。
        is_retryable: 是否可自动重试。需人工介入或权限变更的模式为 False。
    """

    original_error: str
    matched_pattern: FailurePattern | None
    recovery_hint: str
    is_retryable: bool


# 严重程度排序权重：数值越小优先级越高。
SEVERITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}

# 不可自动重试的模式：需要人工审批或权限变更，重试只会重复失败。
# denylist_violation 需人工审批；permission_denied 需提权或改权限。
_NON_RETRYABLE_PATTERNS: frozenset[str] = frozenset(
    {"denylist_violation", "permission_denied"}
)


# 内置失败模式列表。
# 顺序约定：high 优先在前，且 file_not_found 排在 search_zero_matches 之前，
# 避免 "No such file or directory" 被 search_zero_matches 的 "no such file"
# 信号抢先匹配（前者 high，后者 low，语义不同）。
FAILURE_PATTERNS: list[FailurePattern] = [
    FailurePattern(
        pattern_id="terminal_output_truncated",
        name="终端输出被截断",
        description="命令输出超过上限被截断，builder 拿到不完整结果。",
        signals=["truncated", "output too long", "max output exceeded", "stdout limit"],
        recovery_hint=(
            "输出被截断。建议：1) 用 `head -N` / `tail -N` 限制输出行数；"
            "2) 重定向到文件后用 Read 工具读取；3) 用 grep 过滤关键行"
        ),
        severity="high",
    ),
    FailurePattern(
        pattern_id="file_not_found",
        name="文件不存在",
        description="引用的文件路径不存在。",
        signals=[
            "No such file or directory",
            "FileNotFoundError",
            "cannot find",
            "does not exist",
        ],
        recovery_hint=(
            "文件不存在。建议：1) 用 `ls` 确认路径；"
            "2) 检查工作目录（`pwd`）；3) 用 Glob 搜索文件名"
        ),
        severity="high",
    ),
    FailurePattern(
        pattern_id="permission_denied",
        name="权限不足",
        description="操作因权限不足被拒绝。",
        signals=["Permission denied", "Operation not permitted", "access denied"],
        recovery_hint=(
            "权限不足。建议：1) 检查文件权限 `ls -la`；"
            "2) 确认是否需要 sudo；3) 检查文件是否被其他进程锁定"
        ),
        severity="high",
    ),
    FailurePattern(
        pattern_id="import_error",
        name="导入失败",
        description="Python 模块导入失败。",
        signals=["ImportError", "ModuleNotFoundError", "No module named"],
        recovery_hint=(
            "导入失败。建议：1) 确认依赖已安装 `pip install`；"
            "2) 检查 PYTHONPATH；3) 确认模块名拼写"
        ),
        severity="high",
    ),
    FailurePattern(
        pattern_id="syntax_error",
        name="语法错误",
        description="代码存在语法错误。",
        signals=["SyntaxError", "syntax error", "unexpected token", "invalid syntax"],
        recovery_hint=(
            "语法错误。建议：1) 检查行号附近的代码；"
            "2) 用 `python -m py_compile <file>` 验证；3) 检查括号/引号匹配"
        ),
        severity="high",
    ),
    FailurePattern(
        pattern_id="denylist_violation",
        name="命中 denylist",
        description="尝试修改受 denylist 保护的路径。",
        signals=["DENYLIST VIOLATION", "denylist", "protected path"],
        recovery_hint=(
            "命中 denylist。建议：1) 该路径受保护，不可修改；"
            "2) 调整方案避开受保护路径；3) 如确需修改，请人工审批"
        ),
        severity="high",
    ),
    FailurePattern(
        pattern_id="patch_whitespace_mismatch",
        name="空白字符不匹配",
        description="编辑操作的缩进/空白与文件实际不一致。",
        signals=["whitespace", "indentation", "unexpected indent", "tab.*space", "space.*tab"],
        recovery_hint=(
            "空白字符不匹配。建议：1) 检查文件用的是 tab 还是空格；"
            "2) 用 `cat -A <file>` 查看不可见字符；3) 匹配文件实际的缩进风格"
        ),
        severity="medium",
    ),
    FailurePattern(
        pattern_id="patch_already_applied",
        name="编辑可能已应用",
        description="编辑操作的目标内容已存在或已应用。",
        signals=["already applied", "no changes", "already exists", "redefinition"],
        recovery_hint=(
            "编辑可能已应用。建议：1) 用 `git diff` 确认当前状态；"
            "2) 若已应用，视为成功跳过；3) 检查是否有重复的编辑操作"
        ),
        severity="medium",
    ),
    FailurePattern(
        pattern_id="command_timeout",
        name="命令超时",
        description="命令执行超过时限被终止。",
        signals=["timeout", "timed out", "TimeoutExpired"],
        recovery_hint=(
            "命令超时。建议：1) 增加 timeout 参数；"
            "2) 拆分长任务为多个短步骤；3) 用后台执行 `&` + 等待"
        ),
        severity="medium",
    ),
    FailurePattern(
        pattern_id="type_error",
        name="类型错误",
        description="函数调用存在类型不匹配。",
        signals=["TypeError", "type mismatch", "argument.*type", "unexpected keyword"],
        recovery_hint=(
            "类型错误。建议：1) 检查函数签名；"
            "2) 用 `type()` 确认变量类型；3) 检查 mypy 类型标注"
        ),
        severity="medium",
    ),
    FailurePattern(
        pattern_id="network_error",
        name="网络错误",
        description="网络连接失败。",
        signals=[
            "ConnectionError",
            "ConnectionRefused",
            "Network is unreachable",
            "TLS",
            "SSL",
            "handshake",
        ],
        recovery_hint=(
            "网络错误。建议：1) 确认服务是否运行；"
            "2) 检查端口和地址；3) 检查防火墙/代理设置"
        ),
        severity="medium",
    ),
    FailurePattern(
        pattern_id="search_zero_matches",
        name="搜索零匹配",
        description="搜索/Grep 未返回任何结果。",
        signals=["no matches", "0 results", "not found", "no such file", "empty result"],
        recovery_hint=(
            "搜索零匹配。建议：1) 检查搜索路径是否正确；"
            "2) 用更宽泛的 pattern；3) 用 `ls` 确认目录结构；4) 检查大小写"
        ),
        severity="low",
    ),
]


def _match_pattern(error_text: str) -> FailurePattern | None:
    """对单条错误文本按 FAILURE_PATTERNS 顺序匹配，返回首个命中的模式。

    匹配大小写不敏感。返回 None 表示未命中任何已知模式。
    """
    for pattern in FAILURE_PATTERNS:
        for signal in pattern.signals:
            if re.search(signal, error_text, re.IGNORECASE):
                return pattern
    return None


def analyze_failures(
    failure_items: list[str],
    tool_calls: list[dict[str, Any]] | None = None,
) -> list[FailureDiagnostic]:
    """分析失败项，匹配已知失败模式，返回诊断列表（含恢复建议）。

    遵循"不过滤"原则：原始失败文本原样保留在 original_error 中，
    本函数只附加诊断与建议，不修改也不丢弃任何失败项。

    Args:
        failure_items: 失败文本列表（通常来自 aggregate_results 聚合）。
        tool_calls: 可选的 sub-agent 工具调用记录。若提供且包含 ``error``
            或 ``result`` 字段，其文本也会并入分析（用于补充 failure_items
            未覆盖的失败信号）。默认 None 时仅分析 failure_items。

    Returns:
        诊断列表，长度与待分析文本数量一致；未匹配的项 matched_pattern=None。
    """
    # 合并待分析文本：failure_items 为主，tool_calls 中的错误字段为补充。
    texts: list[str] = list(failure_items)
    if tool_calls:
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            for key in ("error", "result"):
                val = tc.get(key)
                if isinstance(val, str) and val.strip():
                    texts.append(val)

    diagnostics: list[FailureDiagnostic] = []
    for text in texts:
        matched = _match_pattern(text)
        if matched is None:
            diagnostics.append(
                FailureDiagnostic(
                    original_error=text,
                    matched_pattern=None,
                    recovery_hint="",
                    is_retryable=False,
                )
            )
        else:
            diagnostics.append(
                FailureDiagnostic(
                    original_error=text,
                    matched_pattern=matched,
                    recovery_hint=matched.recovery_hint,
                    is_retryable=matched.pattern_id not in _NON_RETRYABLE_PATTERNS,
                )
            )
    return diagnostics


def get_recovery_hints(diagnostics: list[FailureDiagnostic]) -> list[str]:
    """从诊断列表提取去重的恢复建议，按 severity 排序（high 在前）。

    只提取命中模式的诊断（matched_pattern 非 None）。未命中的诊断不产生建议。
    去重保持首次出现的顺序，排序后 high 优先于 medium 优先于 low。
    """
    # 收集命中模式的诊断，按 severity 排序（stable sort 保留同 severity 内的首次顺序）。
    matched = [d for d in diagnostics if d.matched_pattern is not None]
    matched.sort(
        key=lambda d: SEVERITY_RANK.get(d.matched_pattern.severity, 99)  # type: ignore[union-attr]
    )

    seen: set[str] = set()
    hints: list[str] = []
    for d in matched:
        hint = d.recovery_hint
        if hint and hint not in seen:
            seen.add(hint)
            hints.append(hint)
    return hints


def format_recovery_section(diagnostics: list[FailureDiagnostic]) -> str:
    """将诊断格式化为 markdown 段落，附加到 builder 报告。

    无命中模式时返回空字符串（调用方据此决定是否附加）。
    输出按 severity 排序，每条含 severity 标签、模式名与恢复建议。
    同一失败模式多次命中只输出一条（按 pattern_id 去重），避免建议噪声。
    """
    matched = [d for d in diagnostics if d.matched_pattern is not None]
    if not matched:
        return ""

    matched.sort(
        key=lambda d: SEVERITY_RANK.get(d.matched_pattern.severity, 99)  # type: ignore[union-attr]
    )

    lines: list[str] = ["## 工具失败恢复建议", ""]
    seen_patterns: set[str] = set()
    for d in matched:
        pattern = d.matched_pattern
        assert pattern is not None  # 上方已过滤， narrowing 给类型检查器
        if pattern.pattern_id in seen_patterns:
            continue
        seen_patterns.add(pattern.pattern_id)
        severity_tag = pattern.severity.upper()
        lines.append(f"- **[{severity_tag}] {pattern.pattern_id}**: {d.recovery_hint}")
    return "\n".join(lines)


__all__ = [
    "FailurePattern",
    "FailureDiagnostic",
    "FAILURE_PATTERNS",
    "SEVERITY_RANK",
    "analyze_failures",
    "get_recovery_hints",
    "format_recovery_section",
]

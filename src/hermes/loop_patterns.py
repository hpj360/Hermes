"""Loop patterns and declarative constants for Loop Engineering.

从 loop.py 拆出的**静态定义层**：pattern 注册表、七条停止规则、
报告格式标准、红线与编排器规则。无状态、无 IO，可被任何层安全 import。

拆分动机（见 loop.py 顶部模块说明）：loop.py 曾同时承担四种职责
（常量定义 / 状态机 / 审计 / GEPA 接线），2273 行成为维护瓶颈。
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class LoopStage(str, Enum):
    L1_REPORT = "l1_report"
    L2_ASSIST = "l2_assist"
    L3_AUTONOMOUS = "l3_autonomous"


class LoopStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    NEEDS_HUMAN = "needs_human"
    COMPLETED = "completed"
    BUDGET_EXCEEDED = "budget_exceeded"
    ERROR = "error"


LOOP_PATTERNS: dict[str, dict[str, Any]] = {
    "daily-triage": {
        "name": "Daily Triage",
        "description": "每天扫描问题、分类优先级、报告High Priority/Watch List/Noise",
        "execution_status": "scaffolding_only",  # 生成脚手架，运行走 guidance 模式
        "default_stage": LoopStage.L1_REPORT,
        "l1_capability": "只报告，不修改",
        "l2_capability": "小步自动修复，Verifier独立验证",
        "l3_capability": "无人值守修复+PR（需要denylist）",
        "denylist": ["auth/", "payment/", "security/"],
        "max_rounds": 3,
        "sub_agents": [
            {"role": "scanner", "agent_file": None, "parallel": False},
        ],
    },
    "knowledge-hygiene": {
        "name": "Knowledge Hygiene",
        "description": "定期清理知识库：过期文档、重复skill、intent debt检测、偿还三笔债",
        "execution_status": "implemented",  # runner._run_knowledge_hygiene 实际执行
        "default_stage": LoopStage.L1_REPORT,
        "l1_capability": "只报告：过期文档、重复skill、缺失的项目约定",
        "l2_capability": "更新时间戳、标记重复、整理索引",
        "l3_capability": "（不建议自动删除）提示用户确认后清理",
        "denylist": [],
        "max_rounds": 2,
        "sub_agents": [
            {"role": "manifest_scanner", "agent_file": None, "parallel": True},
            {"role": "skill_scanner", "agent_file": None, "parallel": True},
            {"role": "knowledge_scanner", "agent_file": None, "parallel": True},
        ],
    },
    "ci-sweeper": {
        "name": "CI Sweeper",
        "description": "监控CI失败，尝试分类和修复flaky test",
        "execution_status": "implemented",  # P0: diagnosing-bugs skill 填充 builder
        "default_stage": LoopStage.L1_REPORT,
        "l1_capability": "报告CI失败列表",
        "l2_capability": "尝试修复明显问题，跑测试验证",
        "l3_capability": "自动提交修复PR",
        "denylist": ["auth/", "payment/"],
        "max_rounds": 3,
        "sub_agents": [
            {"role": "ci_monitor", "agent_file": None, "parallel": False},
            {"role": "builder", "agent_file": "skills/diagnosing-bugs/SKILL.md", "parallel": False},
            {"role": "checker", "agent_file": "checker.md", "parallel": False},
        ],
    },
    "pr-babysitter": {
        "name": "PR Babysitter",
        "description": "盯PR状态，检查CI，提醒reviewer，处理反馈",
        "execution_status": "implemented",  # P0: code-review skill 填充 review 能力
        "default_stage": LoopStage.L1_REPORT,
        "l1_capability": "报告PR状态和CI结果",
        "l2_capability": "回应review评论，修复小问题",
        "l3_capability": "自动merge（需严格条件）",
        "denylist": [],
        "max_rounds": 5,
        "sub_agents": [
            {"role": "pr_monitor", "agent_file": None, "parallel": False},
            {"role": "reviewer_standards", "agent_file": "skills/code-review/SKILL.md", "parallel": True},
            {"role": "reviewer_spec", "agent_file": "skills/code-review/SKILL.md", "parallel": True},
        ],
    },
    "issue-triage": {
        # 对应 Cobus Greyling loop-engineering 7 套工作流中的 "Issue Triage"。
        # 设计目标：把"积压 Issue 太乱"这类持续但低风险任务系统化。
        # 默认 L1：只分类/打标，不修改代码；升级到 L2 可关闭明显重复/无效 issue。
        "name": "Issue Triage",
        "description": "扫描未分配/无标签的 issue，按优先级分类，建议标签/负责人，关闭明显无效项",
        "execution_status": "implemented",  # P0: triage skill 填充分诊能力
        "default_stage": LoopStage.L1_REPORT,
        "l1_capability": "报告未分类 issue 列表 + 推荐标签/优先级 + 疑似重复项",
        "l2_capability": "为 issue 打标签/分配人，关闭明显重复或已超时的 stale issue",
        "l3_capability": "无人值守自动分诊 + 周报（需denylist保护安全敏感issue）",
        "denylist": ["label:security", "label:auth-bypass", "*P0*"],
        "max_rounds": 3,
        "sub_agents": [
            {"role": "issue_scanner", "agent_file": "skills/triage/SKILL.md", "parallel": False},
            {"role": "duplicate_detector", "agent_file": "skills/triage/SKILL.md", "parallel": True},
            {"role": "label_suggester", "agent_file": "skills/triage/SKILL.md", "parallel": True},
        ],
    },
    "changelog-draft": {
        # 对应 Cobus Greyling loop-engineering 7 套工作流中的 "Changelog Drafter"。
        # 设计目标：把"发布前翻几十条 commit 写 changelog"自动化。
        # 默认 L1：基于 git log 自动生成 changelog 草稿；L2 可自动追加到 CHANGELOG.md。
        "name": "Changelog Drafter",
        "description": "扫描自上次 release 以来的 commits/PRs，按 conventional commits 分类生成 CHANGELOG 草稿",
        "execution_status": "scaffolding_only",
        "default_stage": LoopStage.L1_REPORT,
        "l1_capability": "生成草稿写入 STATE.md 的 Changelog Draft 段（不修改 CHANGELOG.md）",
        "l2_capability": "将草稿自动追加到 CHANGELOG.md 的 [Unreleased] 段（人类review后commit）",
        "l3_capability": "无人值守：自动 bump version + commit CHANGELOG.md（需严格tag/分支保护）",
        "denylist": ["CHANGELOG.md"],  # L2 默认追加到段内；L3 须人工触发 tag
        "max_rounds": 2,
        "sub_agents": [
            {"role": "commit_classifier", "agent_file": None, "parallel": False},
            {"role": "pr_summarizer", "agent_file": None, "parallel": True},
        ],
    },
    "multi-perspective": {
        # 借鉴 ai-berkshire 的多视角并行框架：N 个 Agent 从不同视角并行分析
        # 同一标的，Team Lead（synthesizer）汇总成报告。适合分析类任务（非修复类）。
        "name": "Multi-Perspective Analysis",
        "description": "N 个 Agent 从不同视角并行分析同一标的，synthesizer 汇总成报告。适合分析类任务",
        "execution_status": "implemented",  # runner._run_multi_perspective 实际执行
        "default_stage": LoopStage.L2_ASSIST,
        "l1_capability": "各视角只读分析，汇总报告（不修改代码）",
        "l2_capability": "各视角并行分析 + synthesizer 综合结论（含明确评级）",
        "l3_capability": "无人值守并行分析 + 自动归档（需 denylist 保护敏感路径）",
        "denylist": ["auth/", "payment/", "security/", ".env", "*.key"],
        "max_rounds": 2,  # 分析类任务通常 1 轮即出报告，2 轮兜底
        "generates_agents": True,  # 生成 perspective.md + summary.md 模板
        "sub_agents": [
            {"role": "perspective_1", "agent_file": "perspective.md", "parallel": True},
            {"role": "perspective_2", "agent_file": "perspective.md", "parallel": True},
            {"role": "perspective_3", "agent_file": "perspective.md", "parallel": True},
            {"role": "synthesizer", "agent_file": "summary.md", "parallel": False},
        ],
    },
    "builder-checker": {
        "name": "Builder/Checker Loop",
        "description": "写代码和查代码拆成两个Agent，编排器循环调度，查到全绿为止。三文件模式：builder.md + checker.md + loop编排器",
        "execution_status": "implemented",  # runner._run_builder_checker 实际执行
        "default_stage": LoopStage.L2_ASSIST,
        "l1_capability": "builder只读分析，checker只报告（不修改）",
        "l2_capability": "builder写代码，checker跑检查，循环到ALL GREEN或停止条件触发",
        "l3_capability": "无人值守循环+自动提PR（需denylist和严格停止规则）",
        "denylist": ["auth/", "payment/", "security/", ".env", "*.key"],
        "max_rounds": 5,
        "generates_agents": True,
        "sub_agents": [
            {"role": "builder", "agent_file": "builder.md", "parallel": False},
            {"role": "checker_lint", "agent_file": "checker.md", "parallel": True, "check_type": "lint"},
            {"role": "checker_type", "agent_file": "checker.md", "parallel": True, "check_type": "typecheck"},
            {"role": "checker_test", "agent_file": "checker.md", "parallel": True, "check_type": "test"},
        ],
    },
}


# ── Stop rules (七条停止条件) ─────────────────────────────────────────
#
# 设计原则（第一性原理）：
# - 规则应互斥：每个停止场景只归一类，避免遮蔽。
# - 评估顺序 = STOP_RULES 列表顺序 = 诊断优先级（最具体诊断优先）。
# - ALL GREEN 实为成功条件（非停止），列为首条便于统一查阅，action=stop_success。
# - budget_exceeded 与 rounds_exhausted 同属"资源耗尽"，列入规则保证可发现性
#   （实际由 record_round 状态机处理，check_stop_rules 不重复检查）。
#
# 互斥条件（regression / same_failure_twice / no_progress 三者不重叠）：
#   regression        : new ≠ ∅ AND overlap ≠ ∅      （改相关代码引入新失败）
#   same_failure_twice: new = ∅ AND overlap ≠ ∅ AND count未减 （纯重复）
#   no_progress       : new ≠ ∅ AND overlap = ∅ AND fixed ≠ ∅ AND count未减 （全换）

STOP_RULES: list[dict[str, Any]] = [
    {
        "id": "all_green",
        "name": "ALL GREEN",
        "description": "所有检查通过（成功条件，非停止）。停止，附上每项检查的通过证明。",
        "action": "stop_success",
        # 经验D：成功条件，硬性
        "hard_gate": True,
    },
    {
        "id": "rounds_exhausted",
        "name": "轮次用尽",
        "description": "达到轮次上限。停止，报告仍失败的项、每轮尝试了什么、为什么没成功。",
        "action": "stop_escalate",
        # 经验D：资源耗尽必须停
        "hard_gate": True,
    },
    {
        "id": "budget_exceeded",
        "name": "预算耗尽",
        "description": "token 预算用尽。停止，报告已消耗预算与剩余失败项（由 record_round 状态机处理）。",
        "action": "stop_escalate",
        "hard_gate": True,
    },
    {
        "id": "beyond_capability",
        "name": "疑似超出能力边界",
        "description": "builder反复尝试但失败原因涉及它无法访问的外部依赖或环境问题。停止，报告阻塞点。",
        "action": "stop_escalate",
        # 经验D：外部问题无法继续
        "hard_gate": True,
    },
    {
        "id": "regression",
        "name": "回归",
        "description": "修复导致之前通过的检查失败（引入新失败且有重复失败）。停止，说明改了什么导致了回归。",
        "action": "stop_escalate",
        # 经验D：改坏了必须停
        "hard_gate": True,
    },
    {
        "id": "same_failure_twice",
        "name": "同一失败连续两轮",
        "description": "builder在猜，不是在修（纯重复，无新失败引入）。停止，升级给人。",
        "action": "stop_escalate",
        # 经验D：在猜必须停
        "hard_gate": True,
    },
    {
        "id": "no_progress",
        "name": "无实质进展",
        "description": "连续2轮失败项数量没有减少且失败集合完全更换。停止，可能任务范围过大，需要拆分成更小的子任务。",
        "action": "stop_escalate",
        # 经验D：可能只是任务大，拆分后可继续（软门禁）
        "hard_gate": False,
    },
]


# ── Report format standards (报告格式标准) ─────────────────────────────

BUILDER_REPORT_FORMAT = """## Builder 汇报格式
修改完成后，先本地跑一遍 checker 会执行的命令，确认通过再汇报。

汇报格式：
  改了什么：<一句话>
  修改文件：<file1>, <file2>, ...
  本地检查结果：<通过/失败>
"""

CHECKER_REPORT_FORMAT = """## Checker 报告格式

全部通过时：
  ALL GREEN
  然后逐项列出每项检查的名称和通过证明（如 "test: 848 passed, 0 failed"）。
  不要只说全过了。

任何失败时：
  FAILED
  然后逐条列出：
    file:line - 什么坏了 - 哪个检查抓到的

  如果同一文件有多个失败，合并列出。如果多个失败可能是同一根因，标注疑似同源。

  报告末尾必须附上结构化失败协议块（供编排器解析，便于跨轮次比对同一失败）：
    <!-- failures:json -->
    {"passed": false, "failures": [{"file": "src/auth.py", "line": 42, "type": "ImportError"}]}
    <!-- /failures -->

  说明：file 是失败文件路径（不含行号以免行号漂移误判），type 是错误类型/检查名。
  全部通过时输出 {"passed": true, "failures": []}。
"""

# ── Red lines (红线) ───────────────────────────────────────────────────

BUILDER_RED_LINES = [
    "绝不弱化测试来让它通过。修代码，不是修测试。",
    "绝不通过删除、注释、跳过失败的检查来达到通过。",
    "绝不在没有跑过检查的情况下声称已修复。",
    "不要顺手重构不相关的代码。每一行多余改动都可能引入新问题。",
]

CHECKER_RED_LINES = [
    "绝不意译失败信息。复制真实错误输出的关键行。",
    "绝不因为看起来是小问题而省略失败项。",
    "绝不自己尝试修复。你只负责报告，修复是builder的事。",
    "绝不修改自己的工具白名单来获得Write/Edit权限。",
]

ORCHESTRATOR_RULES = [
    "把checker的完整失败报告原样转发给builder，不要自己解读或过滤。",
    "builder需要原始错误信息（行号、堆栈轨迹、中间输出）来定位根因。",
    "每轮开始时公开声明 'Cycle N/最大轮次'。",
    "如果同一失败连续出现两次，停止循环。",
    "如果修复导致之前通过的检查失败，停止循环。",
]

"""Loop Engineering support for Hermes.

Implements the Loop Engineering pattern from cobusgreyling/loop-engineering:
- Loop scaffolding (STATE.md, loop-budget.md, LOOP.md)
- Loop state tracking across runs
- L1/L2/L3 staged autonomy
- Loop readiness audit
- Maker/Checker separation guidance
- Built-in patterns (daily-triage, knowledge-hygiene)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
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
        "default_stage": LoopStage.L1_REPORT,
        "l1_capability": "只报告，不修改",
        "l2_capability": "小步自动修复，Verifier独立验证",
        "l3_capability": "无人值守修复+PR（需要denylist）",
        "denylist": ["auth/", "payment/", "security/"],
        "max_rounds": 3,
    },
    "knowledge-hygiene": {
        "name": "Knowledge Hygiene",
        "description": "定期清理知识库：过期文档、重复skill、intent debt检测、偿还三笔债",
        "default_stage": LoopStage.L1_REPORT,
        "l1_capability": "只报告：过期文档、重复skill、缺失的项目约定",
        "l2_capability": "更新时间戳、标记重复、整理索引",
        "l3_capability": "（不建议自动删除）提示用户确认后清理",
        "denylist": [],
        "max_rounds": 2,
    },
    "ci-sweeper": {
        "name": "CI Sweeper",
        "description": "监控CI失败，尝试分类和修复flaky test",
        "default_stage": LoopStage.L1_REPORT,
        "l1_capability": "报告CI失败列表",
        "l2_capability": "尝试修复明显问题，跑测试验证",
        "l3_capability": "自动提交修复PR",
        "denylist": ["auth/", "payment/"],
        "max_rounds": 3,
    },
    "pr-babysitter": {
        "name": "PR Babysitter",
        "description": "盯PR状态，检查CI，提醒reviewer，处理反馈",
        "default_stage": LoopStage.L1_REPORT,
        "l1_capability": "报告PR状态和CI结果",
        "l2_capability": "回应review评论，修复小问题",
        "l3_capability": "自动merge（需严格条件）",
        "denylist": [],
        "max_rounds": 5,
    },
}


@dataclass
class LoopRound:
    round_num: int
    timestamp: str
    action: str
    result_summary: str
    verifier_result: str
    passed: bool
    next_action: str


@dataclass
class LoopState:
    name: str
    pattern: str
    stage: LoopStage
    status: LoopStatus
    config_path: Path
    state_path: Path
    budget_path: Path
    created_at: str
    last_run: str | None = None
    current_round: int = 0
    max_rounds: int = 5
    rounds: list[LoopRound] = field(default_factory=list)
    budget_used_tokens: int = 0
    budget_limit_tokens: int = 500000
    high_priority_items: list[str] = field(default_factory=list)
    watch_list: list[str] = field(default_factory=list)
    noise_items: list[str] = field(default_factory=list)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def loops_dir() -> Path:
    return _project_root() / ".loops"


def _loop_config_path(name: str) -> Path:
    return loops_dir() / name / "LOOP.md"


def _loop_state_path(name: str) -> Path:
    return loops_dir() / name / "STATE.md"


def _loop_budget_path(name: str) -> Path:
    return loops_dir() / name / "loop-budget.md"


def _loop_meta_path(name: str) -> Path:
    return loops_dir() / name / "meta.json"


def _ensure_loops_dir() -> None:
    loops_dir().mkdir(parents=True, exist_ok=True)


def list_loops() -> list[LoopState]:
    _ensure_loops_dir()
    result: list[LoopState] = []
    if not loops_dir().exists():
        return result
    for entry in sorted(loops_dir().iterdir()):
        if entry.is_dir() and (entry / "meta.json").exists():
            try:
                meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
                state = _load_loop_meta(meta, entry.name)
                if state:
                    result.append(state)
            except (json.JSONDecodeError, OSError):
                continue
    return result


def _load_loop_meta(meta: dict[str, Any], name: str) -> LoopState | None:
    loop_dir = loops_dir() / name
    return LoopState(
        name=name,
        pattern=meta.get("pattern", "custom"),
        stage=LoopStage(meta.get("stage", LoopStage.L1_REPORT.value)),
        status=LoopStatus(meta.get("status", LoopStatus.IDLE.value)),
        config_path=loop_dir / "LOOP.md",
        state_path=loop_dir / "STATE.md",
        budget_path=loop_dir / "loop-budget.md",
        created_at=meta.get("created_at", ""),
        last_run=meta.get("last_run"),
        current_round=meta.get("current_round", 0),
        max_rounds=meta.get("max_rounds", 5),
        budget_used_tokens=meta.get("budget_used_tokens", 0),
        budget_limit_tokens=meta.get("budget_limit_tokens", 500000),
        high_priority_items=meta.get("high_priority_items", []),
        watch_list=meta.get("watch_list", []),
        noise_items=meta.get("noise_items", []),
    )


def _save_loop_meta(state: LoopState) -> None:
    _ensure_loops_dir()
    loop_dir = loops_dir() / state.name
    loop_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "pattern": state.pattern,
        "stage": state.stage.value,
        "status": state.status.value,
        "created_at": state.created_at,
        "last_run": state.last_run,
        "current_round": state.current_round,
        "max_rounds": state.max_rounds,
        "budget_used_tokens": state.budget_used_tokens,
        "budget_limit_tokens": state.budget_limit_tokens,
        "high_priority_items": state.high_priority_items,
        "watch_list": state.watch_list,
        "noise_items": state.noise_items,
    }
    (loop_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def init_loop(name: str, pattern: str = "custom") -> dict[str, Any]:
    _ensure_loops_dir()
    loop_dir = loops_dir() / name

    if loop_dir.exists():
        return {"success": False, "error": f"Loop '{name}' already exists"}

    pattern_info = LOOP_PATTERNS.get(pattern, {})
    now = datetime.now(timezone.utc).isoformat()
    default_stage = pattern_info.get("default_stage", LoopStage.L1_REPORT)
    max_rounds = pattern_info.get("max_rounds", 5)
    budget_limit = pattern_info.get("budget_limit_tokens", 500000)

    loop_dir.mkdir(parents=True, exist_ok=True)

    loop_md = f"""# Loop: {name}

## Pattern
{pattern_info.get('name', pattern.replace('-', ' ').title())}
{pattern_info.get('description', 'Custom loop')}

## Stage (分阶段上线)
**当前阶段: {default_stage.value}**

| 阶段 | 能力 | 状态 |
|------|------|------|
| L1 只报告 | {pattern_info.get('l1_capability', '只生成报告，不做任何修改')} | {'✓ 当前' if default_stage == LoopStage.L1_REPORT else ''} |
| L2 辅助修复 | {pattern_info.get('l2_capability', '小步修复 + 独立Verifier验证')} | {'✓ 当前' if default_stage == LoopStage.L2_ASSIST else ''} |
| L3 无人值守 | {pattern_info.get('l3_capability', '自动执行（需严格denylist）')} | {'✓ 当前' if default_stage == LoopStage.L3_AUTONOMOUS else ''} |

## 目标定义（四步框架）
1. **完成标准（可机器验证）**:
   - TODO: 定义什么叫"做完了"

2. **边界条件（Harness约束，不能怎么做）**:
   - 禁止删除文件
   - 禁止修改denylist中的路径: {', '.join(pattern_info.get('denylist', []))}
   - TODO: 补充其他约束

3. **降级方案（失败怎么办）**:
   - {max_rounds}轮后仍未完成 → 列出未解决项，交给用户决策

4. **目标分层**:
   - 全局约束: 不破坏现有功能，所有测试通过
   - 当前任务: TODO

## Maker/Checker 分离
- **Planner**: 分析状态，生成本轮执行计划
- **Generator**: 执行具体任务
- **Evaluator（独立）**: 验证结果，检查是否违反边界条件，给出"通过/未通过"

## Denylist（高风险路径，L3也不能碰）
{chr(10).join('- ' + d for d in pattern_info.get('denylist', [])) or '- （暂无）'}
"""

    state_md = f"""# Loop State: {name}

Last updated: {now}

## Configuration
- Pattern: {pattern}
- Stage: {default_stage.value}
- Max rounds: {max_rounds}
- Budget limit: {budget_limit} tokens

## High Priority
（需要立即处理的项）

## Watch List
（需要关注但不紧急）

## Recent Noise (ignored)
（可忽略的噪音）

## Execution History
（每轮执行结果记录在此）
"""

    budget_md = f"""# Loop Budget: {name}

## Token Budget
- Limit: {budget_limit} tokens per run
- Estimated per-round cost: ~50000 tokens
- Estimated max runs per budget: ~{budget_limit // 50000} rounds

## Cost Guardrails
- 达到预算80% → 警告，建议人工检查
- 达到预算100% → 自动停止，通知用户
- 同一问题自动修复超过3次 → 升级给人

## Run Log
| Date | Round | Tokens Used | Result | Notes |
|------|-------|-------------|--------|-------|
| {now[:10]} | 0 | 0 | initialized | Loop created |
"""

    (loop_dir / "LOOP.md").write_text(loop_md, encoding="utf-8")
    (loop_dir / "STATE.md").write_text(state_md, encoding="utf-8")
    (loop_dir / "loop-budget.md").write_text(budget_md, encoding="utf-8")

    state = LoopState(
        name=name,
        pattern=pattern,
        stage=default_stage,
        status=LoopStatus.IDLE,
        config_path=loop_dir / "LOOP.md",
        state_path=loop_dir / "STATE.md",
        budget_path=loop_dir / "loop-budget.md",
        created_at=now,
        max_rounds=max_rounds,
        budget_limit_tokens=budget_limit,
    )
    _save_loop_meta(state)

    return {
        "success": True,
        "name": name,
        "pattern": pattern,
        "stage": default_stage.value,
        "path": str(loop_dir),
        "files": ["LOOP.md", "STATE.md", "loop-budget.md"],
    }


def get_loop(name: str) -> LoopState | None:
    loops = list_loops()
    for loop in loops:
        if loop.name == name:
            return loop
    return None


def audit_loop(name: str | None = None) -> dict[str, Any]:
    loops = [get_loop(name)] if name else list_loops()
    loops = [loop for loop in loops if loop is not None]

    if not loops:
        if name:
            return {"success": False, "error": f"Loop '{name}' not found"}
        return {"success": True, "total": 0, "score": 0, "checks": [], "suggestions": ["No loops created yet. Run `hermes loop init <name>` to start."]}

    results: list[dict[str, Any]] = []
    total_score = 0

    for loop in loops:
        checks: list[dict[str, Any]] = []
        score = 0
        suggestions: list[str] = []

        checks.append({
            "name": "STATE.md exists",
            "passed": loop.state_path.exists(),
            "weight": 10,
        })
        if loop.state_path.exists():
            score += 10
        else:
            suggestions.append("Create STATE.md for cross-session state tracking")

        checks.append({
            "name": "LOOP.md has completion criteria",
            "passed": False,
            "weight": 20,
        })
        if loop.config_path.exists():
            content = loop.config_path.read_text(encoding="utf-8")
            has_criteria = "TODO" not in content.split("完成标准")[1].split("##")[0] if "完成标准" in content else False
            checks[-1]["passed"] = has_criteria
            if has_criteria:
                score += 20
            else:
                suggestions.append("Define machine-verifiable completion criteria in LOOP.md (avoid TODO)")
        else:
            suggestions.append("Create LOOP.md with goal definition")

        checks.append({
            "name": "Has Harness boundaries",
            "passed": loop.config_path.exists() and "边界条件" in loop.config_path.read_text(encoding="utf-8"),
            "weight": 15,
        })
        if checks[-1]["passed"]:
            score += 15
        else:
            suggestions.append("Add boundary conditions (Harness constraints) to prevent Goodhart's Law")

        checks.append({
            "name": "Uses L1 stage (start conservative)",
            "passed": loop.stage == LoopStage.L1_REPORT,
            "weight": 10,
        })
        if checks[-1]["passed"]:
            score += 10
        elif loop.stage == LoopStage.L2_ASSIST:
            score += 5
            suggestions.append("Consider running in L1 (report-only) first before enabling auto-fix")

        checks.append({
            "name": "Has fallback plan",
            "passed": loop.config_path.exists() and "降级" in loop.config_path.read_text(encoding="utf-8"),
            "weight": 10,
        })
        if checks[-1]["passed"]:
            score += 10
        else:
            suggestions.append("Add a fallback plan (what to do when max rounds reached)")

        checks.append({
            "name": "Budget configured",
            "passed": loop.budget_path.exists(),
            "weight": 10,
        })
        if checks[-1]["passed"]:
            score += 10
        else:
            suggestions.append("Configure token budget in loop-budget.md to prevent runaway costs")

        checks.append({
            "name": "Maker/Checker separation documented",
            "passed": loop.config_path.exists() and "Evaluator" in loop.config_path.read_text(encoding="utf-8"),
            "weight": 15,
        })
        if checks[-1]["passed"]:
            score += 15
        else:
            suggestions.append("Document Planner/Generator/Evaluator separation (no self-evaluation!)")

        checks.append({
            "name": "Max rounds set",
            "passed": loop.max_rounds > 0 and loop.max_rounds <= 10,
            "weight": 10,
        })
        if checks[-1]["passed"]:
            score += 10
        else:
            suggestions.append("Set reasonable max rounds (3-10) to prevent infinite loops")

        total_score += score
        results.append({
            "loop": loop.name,
            "pattern": loop.pattern,
            "stage": loop.stage.value,
            "score": score,
            "checks": checks,
            "suggestions": suggestions,
        })

    avg_score = total_score // len(results) if results else 0
    readiness = "Not Ready"
    if avg_score >= 80:
        readiness = "Production Ready"
    elif avg_score >= 60:
        readiness = "L1 Ready (report-only)"
    elif avg_score >= 40:
        readiness = "Needs Work"

    return {
        "success": True,
        "total": len(results),
        "average_score": avg_score,
        "readiness": readiness,
        "loops": results,
    }


def estimate_cost(name: str) -> dict[str, Any]:
    loop = get_loop(name)
    if not loop:
        return {"success": False, "error": f"Loop '{name}' not found"}

    per_round_tokens = 50000
    max_rounds = loop.max_rounds
    total_estimate = per_round_tokens * max_rounds
    budget_remaining = loop.budget_limit_tokens - loop.budget_used_tokens
    rounds_remaining = budget_remaining // per_round_tokens if per_round_tokens > 0 else 0

    return {
        "success": True,
        "loop": name,
        "per_round_estimate_tokens": per_round_tokens,
        "max_rounds": max_rounds,
        "total_estimate_tokens": total_estimate,
        "budget_limit_tokens": loop.budget_limit_tokens,
        "budget_used_tokens": loop.budget_used_tokens,
        "budget_remaining_tokens": budget_remaining,
        "estimated_rounds_remaining": rounds_remaining,
        "within_budget": total_estimate <= loop.budget_limit_tokens,
    }


def advance_stage(name: str) -> dict[str, Any]:
    loop = get_loop(name)
    if not loop:
        return {"success": False, "error": f"Loop '{name}' not found"}

    stage_order = [LoopStage.L1_REPORT, LoopStage.L2_ASSIST, LoopStage.L3_AUTONOMOUS]
    current_idx = stage_order.index(loop.stage)
    if current_idx >= len(stage_order) - 1:
        return {"success": False, "error": "Already at highest stage (L3)"}

    audit_result = audit_loop(name)
    if not audit_result.get("success"):
        return audit_result

    loop_result = audit_result["loops"][0]
    if loop_result["score"] < 70 and current_idx == 0:
        return {
            "success": False,
            "error": "Cannot advance to L2: readiness score too low",
            "score": loop_result["score"],
            "required": 70,
            "suggestions": loop_result["suggestions"],
        }
    if loop_result["score"] < 85 and current_idx == 1:
        return {
            "success": False,
            "error": "Cannot advance to L3: readiness score too high",
            "score": loop_result["score"],
            "required": 85,
            "suggestions": loop_result["suggestions"],
        }

    new_stage = stage_order[current_idx + 1]
    loop.stage = new_stage
    _save_loop_meta(loop)

    return {
        "success": True,
        "loop": name,
        "previous_stage": stage_order[current_idx].value,
        "new_stage": new_stage.value,
    }


def knowledge_hygiene_scan() -> dict[str, Any]:
    """Execute L1 report for knowledge-hygiene pattern: scan for issues."""
    root = _project_root()
    knowledge_dir = root / "knowledge"
    skills_dir = root / "skills"

    issues: dict[str, list[str]] = {
        "high_priority": [],
        "watch_list": [],
        "noise": [],
    }

    existing_knowledge = list(knowledge_dir.glob("*.md")) if knowledge_dir.exists() else []
    existing_skills = [d for d in skills_dir.iterdir() if d.is_dir()] if skills_dir.exists() else []

    skill_names = {s.name for s in existing_skills}
    knowledge_names = {k.name for k in existing_knowledge}

    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            listed_skills = set(manifest.get("skills", []))
            listed_knowledge = set(manifest.get("knowledge", []))

            for s in existing_skills:
                if s.name not in listed_skills:
                    issues["watch_list"].append(f"Skill '{s.name}' exists but not in manifest.json")
            for s_name in listed_skills:
                if s_name not in skill_names:
                    issues["high_priority"].append(f"manifest.json lists '{s_name}' but directory missing")

            for k in existing_knowledge:
                if k.name not in listed_knowledge:
                    issues["watch_list"].append(f"Knowledge '{k.name}' exists but not in manifest.json")
            for k_name in listed_knowledge:
                if k_name not in knowledge_names:
                    issues["high_priority"].append(f"manifest.json lists knowledge '{k_name}' but file missing")
        except (json.JSONDecodeError, OSError):
            issues["high_priority"].append("manifest.json parse error")

    for skill_dir in existing_skills:
        skill_md = skill_dir / "SKILL.md"
        meta_json = skill_dir / "_meta.json"
        if not skill_md.exists():
            issues["high_priority"].append(f"Skill '{skill_dir.name}' missing SKILL.md")
        else:
            content = skill_md.read_text(encoding="utf-8")
            if len(content.strip()) < 50:
                issues["watch_list"].append(f"Skill '{skill_dir.name}' SKILL.md is nearly empty")
            if "TODO" in content:
                issues["watch_list"].append(f"Skill '{skill_dir.name}' has TODO in SKILL.md")
        if not meta_json.exists():
            issues["noise"].append(f"Skill '{skill_dir.name}' has no _meta.json (optional)")

    if (root / "README.md").exists():
        readme = (root / "README.md").read_text(encoding="utf-8")
        if "Skill Sync" not in readme and "skill-sync" not in readme:
            issues["watch_list"].append("README.md doesn't mention Skill Sync feature yet")

    intent_debt_notes = []
    if not (root / "AGENTS.md").exists():
        intent_debt_notes.append("AGENTS.md missing - project conventions not documented (Intent Debt)")
    if intent_debt_notes:
        issues["high_priority"].extend(intent_debt_notes)

    return {
        "success": True,
        "pattern": "knowledge-hygiene",
        "stage": LoopStage.L1_REPORT.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "high_priority": issues["high_priority"],
        "watch_list": issues["watch_list"],
        "noise": issues["noise"],
        "summary": {
            "high_priority_count": len(issues["high_priority"]),
            "watch_list_count": len(issues["watch_list"]),
            "noise_count": len(issues["noise"]),
        },
    }

"""Loop readiness audit & deliverable audit.

从 loop.py 拆出的**审计层**：loop 就绪度评分（audit_loop）、产物抽检
（audit_deliverables）、knowledge-hygiene L1 扫描。只读诊断 + 软门禁留疤，
不含 loop 状态机。

依赖方向：loop_audit → loop（读取 LoopState），loop 不 import loop_audit
（CLI 层显式调用），无循环依赖。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes.loop_patterns import STOP_RULES, LoopStage


# 声明性标记协议：与 <!-- failures:json --> 一脉相承，agent 在产物中写标记，
# Hermes 解析校验。校验"标记存在性"，不校验"内容真假"（后者需用户自验）。
_CLAIM_RE = re.compile(r"<!--\s*claim:\s*(.+?)\s*-->")
_CONCLUSION_RE = re.compile(r"<!--\s*conclusion:\s*(.+?)\s*-->")


def audit_loop(name: str | None = None) -> dict[str, Any]:
    # 函数内导入：loop.py 顶层 re-export 本模块，顶层互相 import 会成环
    from hermes.loop import _save_loop_meta, get_loop, list_loops, loops_dir

    loops = [get_loop(name)] if name else list_loops()
    loops = [loop for loop in loops if loop is not None]

    if not loops:
        if name:
            return {"success": False, "error": f"Loop '{name}' not found"}
        return {"success": True, "total": 0, "score": 0, "checks": [], "warnings": [], "suggestions": ["No loops created yet. Run `hermes loop init <name>` to start."]}

    results: list[dict[str, Any]] = []
    total_score = 0

    for loop in loops:
        checks: list[dict[str, Any]] = []
        score = 0
        suggestions: list[str] = []

        checks.append({
            "name": "STATE.md exists",
            "passed": loop.state_path.exists(),
            "weight": 8,
            "hard_gate": False,
        })
        if loop.state_path.exists():
            score += 8
        else:
            suggestions.append("Create STATE.md for cross-session state tracking")

        checks.append({
            "name": "LOOP.md has completion criteria",
            "passed": False,
            "weight": 15,
            # 经验D：完成标准是硬门禁
            "hard_gate": True,
        })
        if loop.config_path.exists():
            content = loop.config_path.read_text(encoding="utf-8")
            has_criteria = "TODO" not in content.split("完成标准")[1].split("##")[0] if "完成标准" in content else False
            checks[-1]["passed"] = has_criteria
            if has_criteria:
                score += 15
            else:
                suggestions.append("Define machine-verifiable completion criteria in LOOP.md (avoid TODO)")
        else:
            suggestions.append("Create LOOP.md with goal definition")

        checks.append({
            "name": "Has Harness boundaries",
            "passed": loop.config_path.exists() and "边界条件" in loop.config_path.read_text(encoding="utf-8"),
            "weight": 10,
            "hard_gate": False,
        })
        if checks[-1]["passed"]:
            score += 10
        else:
            suggestions.append("Add boundary conditions (Harness constraints) to prevent Goodhart's Law")

        checks.append({
            "name": "Uses L1 stage (start conservative)",
            "passed": loop.stage == LoopStage.L1_REPORT,
            "weight": 8,
            "hard_gate": False,
        })
        if checks[-1]["passed"]:
            score += 8
        elif loop.stage == LoopStage.L2_ASSIST:
            score += 4
            suggestions.append("Consider running in L1 (report-only) first before enabling auto-fix")

        checks.append({
            "name": "Has fallback plan",
            "passed": loop.config_path.exists() and "降级" in loop.config_path.read_text(encoding="utf-8"),
            "weight": 8,
            "hard_gate": False,
        })
        if checks[-1]["passed"]:
            score += 8
        else:
            suggestions.append("Add a fallback plan (what to do when max rounds reached)")

        checks.append({
            "name": "Budget configured",
            "passed": loop.budget_path.exists(),
            "weight": 8,
            "hard_gate": False,
        })
        if checks[-1]["passed"]:
            score += 8
        else:
            suggestions.append("Configure token budget in loop-budget.md to prevent runaway costs")

        checks.append({
            "name": "Maker/Checker separation documented",
            "passed": loop.config_path.exists() and "Evaluator" in loop.config_path.read_text(encoding="utf-8"),
            "weight": 10,
            "hard_gate": False,
        })
        if checks[-1]["passed"]:
            score += 10
        else:
            suggestions.append("Document Planner/Generator/Evaluator separation (no self-evaluation!)")

        checks.append({
            "name": "Max rounds set",
            "passed": loop.max_rounds > 0 and loop.max_rounds <= 10,
            "weight": 8,
            "hard_gate": False,
        })
        if checks[-1]["passed"]:
            score += 8
        else:
            suggestions.append("Set reasonable max rounds (3-10) to prevent infinite loops")

        # New checks from "three files" article
        checks.append({
            "name": "Stop rules defined (7 conditions)",
            "passed": False,
            "weight": 12,
            # 经验D：停止规则是硬门禁
            "hard_gate": True,
        })
        loop_dir = loops_dir() / loop.name
        stop_rules_path = loop_dir / "stop-rules.md"
        if stop_rules_path.exists():
            content = stop_rules_path.read_text(encoding="utf-8")
            has_all_rules = all(
                rule["name"] in content
                for rule in STOP_RULES
            )
            checks[-1]["passed"] = has_all_rules
            if has_all_rules:
                score += 12
            else:
                suggestions.append("Define all 7 stop rules in stop-rules.md (budget exceeded, same failure twice, regression, no progress, etc.)")
        else:
            # Check if stop rules are in LOOP.md
            if loop.config_path.exists():
                content = loop.config_path.read_text(encoding="utf-8")
                if "停止规则" in content and "同一失败" in content:
                    checks[-1]["passed"] = True
                    score += 12
                else:
                    suggestions.append("Define stop rules: same failure twice, regression, no progress detection")
            else:
                suggestions.append("Create stop-rules.md with 7 stop conditions")

        checks.append({
            "name": "Tool-level isolation (checker has no Write/Edit)",
            "passed": False,
            "weight": 13,
            # 经验D：安全红线，硬门禁
            "hard_gate": True,
        })
        checker_path = loop_dir / "checker.md"
        if checker_path.exists():
            content = checker_path.read_text(encoding="utf-8")
            # Verify checker.md explicitly excludes Write and Edit from tools
            has_tools_line = "tools:" in content
            no_write = "Write" not in content.split("tools:")[1].split("\n")[0] if has_tools_line else False
            no_edit = "Edit" not in content.split("tools:")[1].split("\n")[0] if has_tools_line else False
            checks[-1]["passed"] = has_tools_line and no_write and no_edit
            if checks[-1]["passed"]:
                score += 13
            else:
                suggestions.append("Ensure checker.md tools field excludes Write and Edit (tool-level hard isolation)")
        else:
            # For non-builder-checker patterns, check if LOOP.md mentions tool isolation
            if loop.config_path.exists():
                content = loop.config_path.read_text(encoding="utf-8")
                if "工具级硬隔离" in content or "tool-level" in content.lower():
                    checks[-1]["passed"] = True
                    score += 13
                else:
                    suggestions.append("Document tool-level isolation: checker must not have Write/Edit tools")
            else:
                suggestions.append("Document tool-level isolation: checker must not have Write/Edit tools")

        # 借鉴 ai-berkshire：multi-perspective pattern 的 summary.md 必须含明确结论
        # （反端水硬约束）。仅约束 multi-perspective，不影响其他 pattern。
        if loop.pattern == "multi-perspective":
            loop_dir = loops_dir() / loop.name
            summary_path = loop_dir / "summary.md"
            has_conclusion = False
            if summary_path.exists():
                content = summary_path.read_text(encoding="utf-8")
                has_conclusion = "<!-- conclusion:" in content
            checks.append({
                "name": "Summary has explicit conclusion (anti-fence-sitter)",
                "passed": has_conclusion,
                "weight": 12,
                "hard_gate": True,
            })
            if has_conclusion:
                score += 12
            else:
                suggestions.append("summary.md must contain <!-- conclusion: --> marker (anti-fence-sitter)")

        total_score += score
        # 经验B：软门禁留疤——收集未通过检查的 name（不是 suggestions）
        loop_warnings = [c["name"] for c in checks if not c["passed"]]
        # 持久化 audit_warnings 到 meta.json，供 _update_state_md 在 STATE.md 留痕
        loop.audit_warnings = loop_warnings
        _save_loop_meta(loop)
        results.append({
            "loop": loop.name,
            "pattern": loop.pattern,
            "stage": loop.stage.value,
            "score": score,
            "checks": checks,
            "suggestions": suggestions,
            "warnings": loop_warnings,
        })

    avg_score = total_score // len(results) if results else 0
    readiness = "Not Ready"
    if avg_score >= 80:
        readiness = "Production Ready"
    elif avg_score >= 60:
        readiness = "L1 Ready (report-only)"
    elif avg_score >= 40:
        readiness = "Needs Work"

    # 经验B：顶层汇总所有未通过检查的 name（扁平列表）
    all_warnings = [w for r in results for w in r["warnings"]]
    return {
        "success": True,
        "total": len(results),
        "average_score": avg_score,
        "readiness": readiness,
        "loops": results,
        "warnings": all_warnings,
    }


def audit_deliverables(name: str) -> dict[str, Any]:
    """借鉴 ai-berkshire report_audit.py：抽检 loop 的 deliverables 产物。

    检查项：
    1. deliverables 中每个文件存在性（复用现有 missing_deliverables 逻辑）
    2. 每个文件中 <!-- claim: --> 标记数量（≥1 为合格，0 为 warning）
    3. multi-perspective pattern 的 summary.md 必须含 <!-- conclusion: --> 标记

    返回 {"missing": [...], "claim_warnings": [...], "conclusion_missing": bool}
    """
    from hermes.loop import get_loop, loops_dir

    loop = get_loop(name)
    if not loop:
        return {"success": False, "error": f"Loop '{name}' not found"}

    missing = [d for d in loop.deliverables if not Path(d).exists()] if loop.deliverables else []
    claim_warnings: list[str] = []
    conclusion_missing = False

    if loop.deliverables:
        for deliverable_path in loop.deliverables:
            p = Path(deliverable_path)
            if not p.exists():
                continue
            content = p.read_text(encoding="utf-8")
            claims = _CLAIM_RE.findall(content)
            if len(claims) == 0:
                claim_warnings.append(f"{p.name}: no <!-- claim: --> markers found")

    # multi-perspective 的 summary.md 必须含 conclusion 标记
    if loop.pattern == "multi-perspective":
        loop_dir = loops_dir() / loop.name
        summary_path = loop_dir / "summary.md"
        if summary_path.exists():
            content = summary_path.read_text(encoding="utf-8")
            if not _CONCLUSION_RE.search(content):
                conclusion_missing = True
        else:
            conclusion_missing = True

    return {
        "success": True,
        "missing": missing,
        "claim_warnings": claim_warnings,
        "conclusion_missing": conclusion_missing,
    }


def knowledge_hygiene_scan() -> dict[str, Any]:
    """Execute L1 report for knowledge-hygiene pattern: scan for issues."""
    root = Path(__file__).resolve().parents[2]
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

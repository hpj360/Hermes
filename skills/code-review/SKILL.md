---
name: code-review
description: "Two-axis review of changes since a fixed point: Standards (coding standards + Fowler smells) and Spec (issue/PRD conformance). Runs both in parallel sub-agents. Use when user wants to review a branch, PR, or WIP changes. 适用于用户提到'code review''代码审查''review PR''审查变更'等场景。"
version: 1.0.0
user-invocable: true
command-dispatch: model
triggers:
  - "code review"
  - "代码审查"
  - "review PR"
  - "审查变更"
  - "/code-review"
---

# Code Review

Two-axis review of the diff between `HEAD` and a fixed point:
- **Standards** — does the code conform to this repo's documented coding standards?
- **Spec** — does the code faithfully implement the originating issue / PRD / spec?

Both axes run as **parallel sub-agents** so they don't pollute each other's context.

适配自 mattpocock/skills (保留双轴方法论，适配为 Hermes pr-babysitter / multi-perspective)。

## 在 Hermes 中的编排

本 skill 作为 `pr-babysitter` loop pattern 的核心能力，也可作为 `multi-perspective` 的 perspective 内容：

```
pr_monitor → code-review (Standards axis + Spec axis 并行) → aggregate
```

在 Hermes 中，双轴通过 `Orchestrator.fan_out` 并行调度：
- perspective_standards → Standards sub-agent
- perspective_spec → Spec sub-agent
- synthesizer → aggregate (不合并、不重排)

## Process

### 1. Pin the fixed point
Capture: `git diff <fixed-point>...HEAD` (three-dot) + `git log <fixed-point>..HEAD --oneline`.

Confirm fixed point resolves and diff is non-empty before spawning sub-agents.

### 2. Identify the spec source
Look for originating spec in order:
1. Issue references in commit messages (`#123`, `Closes #45`)
2. User-supplied path
3. PRD/spec file under `docs/`, `specs/`, or `.scratch/`
4. Ask user; if none, Spec sub-agent reports "no spec available"

### 3. Identify the standards sources
Anything documenting how code should be written (`CODING_STANDARDS.md`, `CONTRIBUTING.md`).

**Smell baseline** (always carries, repo overrides):
- Mysterious Name → rename
- Duplicated Code → extract shared shape
- Feature Envy → move method onto envied data
- Data Clumps → bundle into one type
- Primitive Obsession → give concept its own type
- Repeated Switches → polymorphism
- Shotgun Surgery → gather what changes together
- Divergent Change → split by reason
- Speculative Generality → delete, inline back
- Message Chains → hide walk behind one method
- Middle Man → cut, call direct
- Refused Bequest → drop inheritance, use composition

**Rules**: repo overrides baseline; each smell is a labelled heuristic, never hard violation; skip anything tooling enforces.

### 4. Spawn both sub-agents in parallel

**Standards sub-agent brief**:
- Full diff command + commit list
- Standards-source files + smell baseline pasted in full
- "Report per file/hunk: (a) documented-standard violations with citation; (b) baseline smells with hunk quote. Distinguish hard violations from judgement calls. Skip tooling-enforced. Under 400 words."

**Spec sub-agent brief**:
- Diff command + commit list
- Spec path or fetched contents
- "Report: (a) spec requirements missing/partial; (b) scope creep; (c) implemented-but-wrong. Quote spec line for each. Under 400 words."

### 5. Aggregate
Present two reports under `## Standards` and `## Spec` headings, verbatim or lightly cleaned.

**Do NOT merge or rerank findings** — the two axes are deliberately separate.

End with one-line summary: total findings per axis + worst issue within each axis.

## Why two axes

A change can pass one axis and fail the other:
- Code that follows every standard but implements the wrong thing → **Standards pass, Spec fail.**
- Code that does exactly what the issue asked but breaks conventions → **Spec pass, Standards fail.**

Reporting separately stops one axis from masking the other.

## Completion criteria
- [ ] Fixed point resolves and diff is non-empty
- [ ] Both sub-agents spawned in parallel (or Spec skipped with reason)
- [ ] Reports presented under separate headings, not merged
- [ ] Per-axis worst issue identified (no cross-axis winner)

## Related skills（边界声明）

- **diagnosing-bugs**: 修复**一个具体 bug**（root cause → fix → regression test）。本 skill 审查**整个 PR/diff**（Standards + Spec 双轴）。**不要混用**：bug 排查走 diagnosing-bugs，PR 提交前走 code-review。
- **github**: PR 数据通道（`gh pr view` / `gh pr checks`）。本 skill 解读 diff 的 Standards/Spec，github 负责拉取 PR 元数据。
- **resolving-merge-conflicts**: 冲突解决。本 skill 在 PR **可合并**状态下审查；冲突未解决时由 resolving-merge-conflicts 先处理。
- **codebase-design**: 架构词汇。Standards 轴的 smell 检测（"Shallow Module" / "Pass-through" / "Non-local change"）复用 codebase-design 词汇。
- **triage**: 本 skill 关注**已提交**的 PR；triage 关注**未分诊**的 issue。两者前后衔接。

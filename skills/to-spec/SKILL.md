---
name: to-spec
description: "Turn a raw user request into a PRD-style spec WITHOUT interviewing the user. Synthesizes from conversation + codebase + existing docs. Use when user asks for a spec, PRD, or design doc from a conversation. 适用于用户提到'写spec''生成PRD''设计文档''需求文档'等场景。"
version: 1.0.0
user-invocable: true
command-dispatch: model
triggers:
  - "to-spec"
  - "写 spec"
  - "生成 PRD"
  - "设计文档"
  - "需求文档"
---

# To Spec

Turn a raw user request into a PRD-style spec **without interviewing the user**. Synthesizes from conversation + codebase + existing docs.

适配自 mattpocock/skills (保留 synthesis-first 方法论，适配为 Hermes 规划层入口)。

## 在 Hermes 中的角色

这是规划层的第一步，补齐 Hermes "loop 启动前" 的需求规划缺口：

```
to-spec → to-tickets → wayfinder → loop init (builder-checker)
  PRD      票据分解     决策地图      执行编排
```

## Process

### 1. Gather sources (do NOT ask the user)
Read in this order:
1. The conversation that triggered this skill (the request lives there)
2. Existing `.scratch/*.md`, `docs/specs/*.md`, `docs/adr/*.md`
3. `CONTEXT.md` / `README.md` for domain glossary
4. Codebase structure (module list, key entry points)

### 2. Synthesize the spec
Write to `.scratch/<feature-slug>.spec.md` with this skeleton:

```markdown
# Spec: <feature name>

## Problem
[1-3 sentences. What's broken / missing / needed?]

## Users
[Who benefits and how. Be specific about personas.]

## Non-goals
[Explicitly out of scope. This is as important as goals.]

## Proposed solution
[High-level approach. Reference existing code where possible.]

## User stories
- As <persona>, I want <action>, so that <benefit>.
[3-7 stories. Each must be testable.]

## Acceptance criteria
- [ ] <criterion 1>
- [ ] <criterion 2>
[Each criterion is binary pass/fail.]

## Open questions
[Things you couldn't resolve from sources. User can answer later, but spec is usable without them.]

## Risks
[Technical / product / schedule risks. Note mitigation.]
```

### 3. Validate against codebase
- Does the proposed solution fit the existing architecture?
- Are there ADRs that constrain this? (read `docs/adr/`)
- Are there domain concepts that need modeling? (hand off to domain-modeling)

### 4. Present the spec
Show the spec to the user. Note explicitly:
- What was synthesized vs. what was taken verbatim from sources
- Which open questions the user should answer (but spec is usable without)

## Why synthesis-first (not interview-first)

Interviewing the user blocks on human response, which breaks AFK agent loops. Synthesizing from existing sources:
- Respects that the user already wrote down what they want (in the conversation)
- Produces a spec that's immediately actionable
- Open questions are noted but don't block

If the spec is wrong, the user corrects it — cheaper than a 10-question interview.

## Completion criteria
- [ ] Spec written to `.scratch/<feature-slug>.spec.md`
- [ ] All 8 sections present and non-empty
- [ ] Acceptance criteria are binary (pass/fail)
- [ ] Open questions explicitly marked as non-blocking
- [ ] ADR constraints checked and referenced

## Related skills（边界声明）

- **to-tickets**: PRD → tickets。本 skill 输出 PRD 后由 to-tickets 拆解为 tracer-bullet tickets。本 skill **不**写 ticket 粒度的实现任务。
- **wayfinder**: 决策地图。本 skill 不做技术选型决策；选型由 wayfinder 在 tickets 之后、loop init 之前处理。
- **prototype**: throwaway 原型。如果本 skill 输出的方案 cost-of-wrong = "hard"，由 wayfinder 决定是否走 prototype。
- **domain-modeling**: 领域建模。本 skill 写 spec 时优先读 `CONTEXT.md` 获取术语，新概念同步写入。
- **product-manager**: 产品方法论（discovery / prioritization / SaaS 指标）。本 skill 是**PRD 模板填充**，PM 视角的"为什么做"由 product-manager 提供输入。

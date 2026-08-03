---
name: wayfinder
description: "Map decisions in a large piece of work to a ticket-style decision board before writing code. Each decision has: problem, options, recommended option, cost-of-wrong. Use when facing multiple interconnected decisions or a complex task. 适用于用户提到'决策地图''wayfinder''技术选型''方案选择'等场景。"
version: 1.0.0
user-invocable: true
command-dispatch: model
triggers:
  - "wayfinder"
  - "决策地图"
  - "技术选型"
  - "方案选择"
---

# Wayfinder

Map the decisions in a large piece of work to a **decision board** before writing code.

适配自 mattpocock/skills (保留 decision-ticket 方法论，适配为 Hermes 规划层第三步)。

## 在 Hermes 中的角色

规划层第三步：在 tickets 生成后、loop 启动前，梳理决策点：

```
to-spec → to-tickets → wayfinder → loop init
  PRD      票据分解     决策地图      执行
```

## Decision ticket format

Each decision is a ticket with:

```markdown
## Decision: <short name>
**Problem**: <1-2 sentences. What needs deciding?>
**Options**:
- A) <option> — <pro/con in 1 line>
- B) <option> — <pro/con in 1 line>
- C) <option> — <pro/con in 1 line>
**Recommended**: <A/B/C>
**Cost of wrong**: <how expensive to reverse if we pick wrong? $/time/risk>
**Reversibility**: easy | medium | hard | impossible
**Decided by**: <human name> | <deferred>
```

## Process

### 1. Scan the spec + tickets
Read `.scratch/<feature-slug>.spec.md` and `.scratch/<feature-slug>.tickets.md`.

### 2. Extract decisions
Look for:
- **Architectural choices** (sync vs async, monolith vs service, etc.)
- **Library/framework selections**
- **Data model shape** (one table vs two, normalized vs denormalized)
- **API contract decisions** (REST vs GraphQL, versioning strategy)
- **Deployment choices** (container vs serverless, region)
- **Testing strategy** (unit only vs integration, property vs example)

### 3. Write the decision board
Write to `.scratch/<feature-slug>.decisions.md` with one decision ticket per decision.

### 4. Recommend + assess cost-of-wrong
For each decision:
- Recommend the option with the **lowest cost-of-wrong** (not the "best" option)
- If cost-of-wrong is **easy**, proceed without human input
- If cost-of-wrong is **medium/hard**, flag for human review before loop init
- If cost-of-wrong is **impossible**, BLOCK loop init until human decides

### 5. Output a summary table

| Decision | Recommended | Cost-of-wrong | Reversibility | Action |
|----------|------------|---------------|---------------|--------|
| <name> | <A/B/C> | easy/medium/hard | easy/hard | proceed/flag/block |

## Why cost-of-wrong > "best option"

Picking the "best" option requires knowing the future. Picking the option with the lowest cost-of-wrong means:
- If you're right, great
- If you're wrong, the reversal is cheap

This is especially important for AFK agent loops — a decision that's expensive to reverse can waste an entire loop's budget.

## Completion criteria
- [ ] Decision board written to `.scratch/<feature-slug>.decisions.md`
- [ ] Every decision has: problem, ≥2 options, recommendation, cost-of-wrong, reversibility
- [ ] Summary table includes action column (proceed/flag/block)
- [ ] Any "block" decisions are explicitly called out for human review
- [ ] No "block" decisions remain unresolved before `loop init`

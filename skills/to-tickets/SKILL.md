---
name: to-tickets
description: "Decompose a spec or PRD into tracer-bullet tickets with explicit blocking edges. Each ticket is agent-ready (fully specified, independently testable). Use when user wants to break down a spec/feature into implementable tickets. 适用于用户提到'拆任务''分解ticket''tracer-bullet''工作分解'等场景。"
version: 1.0.0
user-invocable: true
command-dispatch: model
triggers:
  - "to-tickets"
  - "拆任务"
  - "分解 ticket"
  - "tracer-bullet"
  - "工作分解"
---

# To Tickets

Decompose a spec into **tracer-bullet tickets** — each independently testable, with explicit blocking edges.

适配自 mattpocock/skills (保留 tracer-bullet 方法论，适配为 Hermes 规划层第二步)。

## 在 Hermes 中的角色

规划层第二步：spec → tickets：

```
to-spec → to-tickets → wayfinder → loop init
  PRD      票据分解     决策地图      执行
```

## Tracer-bullet principle

A **tracer bullet** is a thin end-to-end slice that proves the architecture works. Decompose so that:
- The **first** ticket is a tracer bullet (touches every layer, minimal functionality)
- Subsequent tickets thicken each layer
- No ticket depends on >3 others (keep DAG shallow)

Anti-pattern: "horizontal" decomposition (all models → all views → all controllers). This blocks integration until the end.

## Process

### 1. Read the spec
Locate `.scratch/<feature-slug>.spec.md` (from to-spec) or user-supplied spec path.

### 2. Identify the tracer bullet
Find the thinnest slice that:
- Touches every architectural layer (input → processing → output)
- Implements exactly ONE user story (the simplest one)
- Is independently testable

This is **Ticket #1**.

### 3. Decompose remaining work
For each remaining user story / acceptance criterion:
- Can it be added independently? → separate ticket
- Does it require extending the tracer bullet? → ticket that depends on #1

### 4. Write tickets
Write to `.scratch/<feature-slug>.tickets.md`:

```markdown
# Tickets: <feature name>

## Ticket 1: <tracer-bullet title>
**Spec ref**: <section/line in spec>
**Blocks**: #2, #3
**Blocked by**: (none)
**Acceptance**:
- [ ] <binary criterion>
**Agent-ready**: yes | no (if no, what's missing)
**Implementation notes**: <key seams / patterns to follow>

## Ticket 2: <title>
**Spec ref**: ...
**Blocks**: #5
**Blocked by**: #1
**Acceptance**: ...
**Agent-ready**: yes
**Implementation notes**: ...

...
```

### 5. Validate the DAG
- Check for cycles (a ticket blocking itself, directly or transitively)
- Check depth: no ticket should be >3 levels deep from the root
- Check coverage: every acceptance criterion in the spec maps to ≥1 ticket
- Check "agent-ready" flags: tickets marked `no` need a human to fill the gap before `loop init`

### 6. Suggest execution order
Output a topological order that respects blocking edges, tracer-bullet-first.

## Completion criteria
- [ ] All tickets written to `.scratch/<feature-slug>.tickets.md`
- [ ] Ticket #1 is a tracer bullet (end-to-end, single story)
- [ ] Every ticket has: spec ref, blocks, blocked-by, acceptance, agent-ready flag
- [ ] DAG is acyclic and ≤3 deep
- [ ] Topological order suggested
- [ ] Every spec acceptance criterion maps to ≥1 ticket

## Related skills（边界声明）

- **to-spec**: 需求 → PRD。本 skill 消费 to-spec 输出的 spec.md；不直接接受用户口头需求（避免重复决策）。
- **wayfinder**: 决策地图。本 skill 拆 ticket 后，wayfinder 在 ticket 边界处识别需要人类决策的**架构选型**。两者串联：to-spec → to-tickets → wayfinder。
- **prototype**: throwaway 原型。如果 wayfinder 标出某个 ticket cost-of-wrong = "hard"，先走 prototype 再填 ticket。
- **loop-engineering**: /goal 与 /loop。本 skill 输出 tickets 后，由 loop init（builder-checker）按依赖图执行。

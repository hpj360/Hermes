---
name: improve-codebase-architecture
description: "Analyze a codebase for architecture improvement opportunities and produce an HTML report with grilling. Deepens opportunities through targeted questions. Use when user wants to improve architecture, reduce coupling, or plan a refactor. 适用于用户提到'改善架构''降低耦合''重构计划''架构审查'等场景。"
version: 1.0.0
user-invocable: true
command-dispatch: model
triggers:
  - "improve architecture"
  - "改善架构"
  - "降低耦合"
  - "重构计划"
  - "架构审查"
---

# Improve Codebase Architecture

Analyze a codebase for architecture improvement opportunities. Produce an HTML report, then deepen each opportunity through grilling.

适配自 mattpocock/skills (保留 HTML 报告 + 拷问方法论，适配为 Hermes audit_loop 的进化版)。

## 在 Hermes 中的角色

这是 `audit_loop` 的深度进化版：
- audit_loop 检查"脚手架是否存在"（10 项 + 1 条件项）
- 本 skill 检查"架构是否健康"（深度、局部性、seam、杠杆）

可作为 `multi-perspective` loop pattern 的 perspective 内容来源。

## Process

### 1. Build the codebase map
Read the project structure. For each module, capture:
- Path + line count
- Public interface (exported names)
- Direct dependencies (imports)
- Test coverage (has test file?)

### 2. Detect opportunities
Using the [codebase-design](codebase-design) vocabulary, scan for:

| Opportunity | Signal | Vocabulary |
|-------------|--------|-----------|
| Shallow module | Large interface, small impl | Depth |
| Pass-through chain | A→B→C where B/C just forward | Leverage |
| Non-local change | Common change touches >3 files | Locality |
| Missing seam | Module has no test file | Seam |
| Interface bloat | Interface has >15 public methods | Interface |
| God module | >1000 lines + >30 public names | Depth |

### 3. Produce HTML report
Write to `.scratch/architecture-report.html`:

```html
<!DOCTYPE html>
<html>
<head><title>Architecture Report</title>
<style>
  body { font-family: sans-serif; max-width: 900px; margin: auto; padding: 2em; }
  .opportunity { border: 1px solid #ddd; padding: 1em; margin: 1em 0; border-radius: 4px; }
  .severity-high { border-left: 4px solid #e74c3c; }
  .severity-medium { border-left: 4px solid #f39c12; }
  .severity-low { border-left: 4px solid #3498db; }
  .metric { font-family: monospace; background: #f8f8f8; padding: 0.2em 0.4em; border-radius: 3px; }
</style>
</head>
<body>
<h1>Architecture Report</h1>
<p>Generated: <time>{{date}}</time></p>

<h2>Summary</h2>
<table>
  <tr><th>Opportunity</th><th>Severity</th><th>Module(s)</th></tr>
  {{rows}}
</table>

<h2>Details</h2>
{{opportunities}}

<h2>Metrics</h2>
<ul>
  <li>Total modules: {{n}}</li>
  <li>Avg depth ratio (impl/interface): {{ratio}}</li>
  <li>Modules without tests: {{untested}}</li>
  <li>Max dependency fan-out: {{max_fanout}}</li>
</ul>
</body>
</html>
```

Each opportunity card includes:
- Severity (high/medium/low)
- Module(s) affected
- Vocabulary term violated
- Evidence (code reference)
- Suggested action

### 4. Grill the opportunities
For each **high** and **medium** severity opportunity, ask 3 targeted questions:

1. **Cost of inaction**: What happens if we don't fix this? (Quantify: time wasted per change, bug risk)
2. **Cheapest fix**: What's the minimal change that reduces the problem? (Not the "ideal" fix — the cheapest one)
3. **Blocker check**: Is there a reason this structure exists? (legacy constraint, performance, external API)

Present questions to the user. Wait for answers before suggesting a refactor plan.

### 5. Suggest a refactor plan (if user confirms)
Order by:
1. Cheapest fix first (build momentum)
2. High-severity before medium
3. Local changes before non-local

Each step in the plan must be:
- Independently revertible (git revert-able)
- Testable in isolation
- Completable in one loop round

## Completion criteria
- [ ] Codebase map built (all modules with interface + deps + test status)
- [ ] HTML report written to `.scratch/architecture-report.html`
- [ ] Every high/medium opportunity has 3 grilling questions
- [ ] Refactor plan (if confirmed) ordered by cost-to-fix
- [ ] Each plan step is independently revertible and testable

## Related skills

- **codebase-design**: 架构词汇表（Module / Interface / Depth / Seam / Adapter / Leverage / Locality）。本 skill 是**流程型**（检测机会 + 生成报告），codebase-design 是**参考型**（提供检测用的词汇）。本 skill 的 "Vocabulary term violated" 字段引用 codebase-design 的词汇。
- **research**: 源码研究。在 Build codebase map 阶段，可用 research 深入理解模块意图。
- **diagnosing-bugs**: 调试。当架构问题导致 bug 时，diagnosing-bugs 的 Phase 6 post-mortem 会 hand off 到本 skill。

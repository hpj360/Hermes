---
name: prototype
description: "Build a one-off, throwaway prototype to answer a design question. The prototype is NOT production code — it exists to answer 'does this approach work?' Use when user wants to explore an approach, validate a design, or spike a technical question. 适用于用户提到'原型''spike''验证方案''技术验证'等场景。"
version: 1.0.0
user-invocable: true
command-dispatch: model
triggers:
  - "prototype"
  - "原型"
  - "spike"
  - "验证方案"
  - "技术验证"
---

# Prototype

Build a one-off, throwaway prototype to answer a design question. The prototype is **not production code** — it exists to answer "does this approach work?"

适配自 mattpocock/skills (保留 throwaway-prototype 方法论，适配为 Hermes 探索能力)。

## 在 Hermes 中的角色

在 wayfinder 之后、to-tickets 之前，用 prototype 验证不确定的技术方案：
- 如果 cost-of-wrong 是 "hard"，先 prototype 验证
- prototype 结果决定 wayfinder 决策

## Principle: Throwaway by default

A prototype is **built to be thrown away**. If it survives into production, it wasn't a prototype — it was premature production code, and that's a failure.

**Rules**:
- Prototype lives in `.scratch/prototype/` (gitignored or explicitly marked)
- Filename starts with `throwaway_`
- Top of file: `# THROWAWAY PROTOTYPE — do not import in production`
- After answering the question, delete the file

## Process

### 1. State the design question
One sentence: "Can we <approach> to achieve <goal>?"

Examples:
- "Can we use a single SQLite file for job persistence instead of JSON?"
- "Can we stream OpenClaw Gateway responses instead of buffering?"
- "Can we run builder-checker sub-agents truly concurrently with asyncio?"

### 2. Define success/failure criteria
What output answers the question?
- **Success**: prototype demonstrates <observable behavior>
- **Failure**: prototype cannot <observable behavior>
- **Metric**: <quantitative threshold if applicable>

### 3. Build the minimum prototype
- Smallest code that can produce the success/failure signal
- No error handling (let it crash)
- No tests (it's throwaway)
- No config (hardcode everything)
- No docs (self-explanatory or commented)

Write to `.scratch/prototype/throwaway_<topic>.py` (or `.js`/`.ts`/`.sh`).

### 4. Run + observe
Run the prototype. Capture:
- Did it produce the signal?
- What was unexpected?
- Did it answer the design question?

### 5. Report + delete
Write findings to `.scratch/prototype/throwaway_<topic>.results.md`:
- Design question (from step 1)
- Success/failure (from step 2)
- What happened (from step 4)
- Decision: proceed / pivot / abandon

Then **delete the prototype code** (keep only the results file).

## When NOT to prototype

- The question is about product direction, not technical feasibility → use to-spec
- The approach is already proven elsewhere → cite the source, don't re-prove
- The cost-of-wrong is "easy" → just pick an option in wayfinder and move on

## Completion criteria
- [ ] Design question stated in one sentence
- [ ] Success/failure criteria defined (observable + binary)
- [ ] Prototype built in `.scratch/prototype/throwaway_*`
- [ ] Prototype run and results captured
- [ ] Decision recorded (proceed/pivot/abandon)
- [ ] Prototype code DELETED (only results.md retained)

## Related skills（边界声明）

- **prototype-validator**: 运行时验证（Playwright + axe-core + Lighthouse）。本 skill 验证**前端原型**（UI/a11y/性能/交互），prototype 验证**技术方案**（设计问题是否可解）。prototype 跑通后再用 prototype-validator 验收前端实现。
- **to-spec**: 需求→PRD。如果设计问题涉及产品方向，先用 to-spec，不要用 prototype。
- **wayfinder**: 决策地图。wayfinder 输出 cost-of-wrong = "hard" 的决策时，先用 prototype 验证再走 loop init。
- **codebase-design**: 架构词汇。prototype 评估 impl 的"深度"时参考其词汇。

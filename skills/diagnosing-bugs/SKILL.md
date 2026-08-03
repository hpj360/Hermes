---
name: diagnosing-bugs
description: "Disciplined diagnosis loop for hard bugs and performance regressions. Use when user says 'diagnose'/'debug this', reports something broken/throwing/failing/slow. 适用于用户提到'调试''排查bug''性能回归''复现'等场景。"
version: 1.0.0
user-invocable: true
command-dispatch: model
triggers:
  - "diagnose"
  - "debug"
  - "调试"
  - "排查"
  - "复现"
  - "性能回归"
---

# Diagnosing Bugs

A discipline for hard bugs. Skip phases only when explicitly justified.

适配自 mattpocock/skills (保留 6 阶段调试方法论，适配为 Hermes ci-sweeper builder)。

## 在 Hermes 中的编排

本 skill 作为 `ci-sweeper` loop pattern 的 **builder** agent 内容来源：

```
ci_monitor (扫描CI失败) → diagnosing-bugs (builder: 诊断+修复) → checker (验证)
```

## Phase 1 — Build a feedback loop

**This is the skill.** 如果有一个 **tight** 的 pass/fail 信号能在这个 bug 上变红，就能找到原因。

构建反馈环的方式（按优先级）：
1. Failing test at whatever seam reaches the bug
2. Curl / HTTP script against a running dev server
3. CLI invocation with fixture input, diffing stdout
4. Headless browser script (Playwright/Puppeteer)
5. Replay a captured trace
6. Throwaway harness
7. Property / fuzz loop
8. Bisection harness
9. Differential loop (old vs new version)
10. HITL bash script (last resort)

**Tighten the loop**: faster / sharper signal / more deterministic.

**Completion criterion**: 一个 tight + red-capable 的命令，已运行至少一次。

## Phase 2 — Reproduce + minimise

Run the loop. Watch it go red. Confirm:
- [ ] Loop produces the failure mode the **user** described
- [ ] Failure is reproducible (or high enough rate for flaky bugs)
- [ ] Exact symptom captured for later verification

**Minimise**: shrink repro to smallest scenario that still goes red. Cut inputs/callers/config/data/steps one at a time. Done when every remaining element is load-bearing.

## Phase 3 — Hypothesise

Generate **3–5 ranked hypotheses** before testing any. Each must be **falsifiable**:

> Format: "If <X> is the cause, then <changing Y> will make the bug disappear."

**Show the ranked list to the user before testing.**

## Phase 4 — Instrument

Each probe maps to a specific prediction. Change one variable at a time.

Tool preference:
1. Debugger / REPL inspection (one breakpoint beats ten logs)
2. Targeted logs at boundaries
3. Never "log everything and grep"

**Tag every debug log** with unique prefix, e.g. `[DEBUG-a4f2]`. Cleanup = single grep.

**Perf branch**: establish baseline measurement, then bisect. Measure first, fix second.

## Phase 5 — Fix + regression test

Write the regression test **before the fix** — but only if there is a **correct seam**:

1. Turn minimised repro into a failing test at that seam
2. Watch it fail
3. Apply the fix
4. Watch it pass
5. Re-run Phase 1 feedback loop against original scenario

If no correct seam exists, that itself is the finding — flag for Phase 6.

## Phase 6 — Cleanup + post-mortem

Required before declaring done:
- [ ] Original repro no longer reproduces
- [ ] Regression test passes (or absence of seam documented)
- [ ] All `[DEBUG-...]` instrumentation removed
- [ ] Throwaway prototypes deleted
- [ ] Correct hypothesis stated in commit/PR message

**Then ask**: what would have prevented this bug? If answer involves architectural change, hand off to improve-codebase-architecture.

## Completion criteria
- [ ] Phase 1: tight + red-capable feedback loop built and run at least once
- [ ] Phase 2: failure reproduced and minimised (every remaining element load-bearing)
- [ ] Phase 3: 3-5 ranked falsifiable hypotheses shown to user before testing
- [ ] Phase 4: one variable changed at a time; all debug logs tagged with unique prefix
- [ ] Phase 5: regression test written before fix; fix applied; Phase 1 loop re-run green
- [ ] Phase 6: all instrumentation removed; throwaway prototypes deleted; correct hypothesis in commit message

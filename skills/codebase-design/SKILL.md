---
name: codebase-design
description: "A vocabulary for talking about codebase architecture: modules, interfaces, depth, seams, adapters, leverage, locality. Use when discussing architecture, reviewing module structure, or planning refactors. 适用于用户提到'架构设计''模块划分''接口设计''seam''耦合'等场景。"
version: 1.0.0
user-invocable: true
command-dispatch: model
triggers:
  - "codebase design"
  - "架构设计"
  - "模块划分"
  - "seam"
  - "耦合"
---

# Codebase Design

A vocabulary for talking about codebase architecture. Words shape what we can think — a shared vocabulary lets a team reason about structure together.

适配自 mattpocock/skills (保留深模块词汇表，沉淀为 Hermes 架构讨论的统一语言)。

## 词汇表

### Module（模块）
A unit of code that groups related responsibilities. Good modules are **deep** (see below).

### Interface（接口）
The surface area a module exposes to its callers. Includes:
- Function/method signatures
- Types
- Error modes
- Side effects (observable externally)
- Configuration it reads
- Resources it holds

**Rule**: an interface is a *promise*. Every public element is something you must maintain. Hide what you can.

### Depth（深度）
A module is **deep** when it has a small interface hiding a large implementation.

```
Shallow module:        Deep-module:
┌──────────────┐      ┌──────────────┐
│  interface   │      │   interface  │  ← small
├──────────────┤      ├──────────────┤
│              │      │              │
│  impl (small)│      │              │
│              │      │   impl       │  ← large
└──────────────┘      │              │
                      └──────────────┘
```

Shallow modules add indirection without leverage. Aim for deep modules.

### Seam（接缝）
A place in the code where you can vary behavior without modifying the code on either side.

Examples:
- A function parameter (dependency injection)
- An interface with multiple implementations
- A config file
- An event handler registration

**Seams are where tests hook in.** No seam = untestable.

### Adapter（适配器）
Code that translates between two interfaces that don't match. Adapters are **shallow by design** — they should be trivial pass-throughs.

If your adapter has real logic, it's not an adapter. It's a new module wearing an adapter costume.

### Leverage（杠杆）
A module has **leverage** when a small amount of code in it controls a large amount of behavior elsewhere.

High-leverage modules:
- Frameworks (you write callbacks, framework drives execution)
- DSLs / config loaders (small parser, large behavior)
- Code generators

Low-leverage modules:
- CRUD wrappers
- Pass-through layers
- "Manager" classes that delegate to one thing

### Locality（局部性）
A change is **local** if it touches one module. A change is **non-local** if it requires coordinated edits across multiple modules.

**Locality is the #1 test of good architecture**: if a common change requires touching 5 files, the architecture is fighting you.

## 评估问题

当审查或设计模块时，问：

1. **Depth**: Is this module deep or shallow? If shallow, can the interface shrink or the impl grow?
2. **Locality**: Where does the most common change land? One module or many?
3. **Seam**: Is there a test seam? If not, where should one be added?
4. **Leverage**: Does this module give us leverage, or is it a pass-through?
5. **Interface**: What's the smallest interface that satisfies callers?

## 反模式

- **Pass-through pyramid**: A → B → C → D, where B and C just forward. Delete B and C.
- **Interface bloat**: 30-method interface where callers use 3. Split or hide.
- **Shallow wrapper**: A class that wraps another class to "add abstraction" but adds no behavior. Delete.
- **Distributed locality**: Adding a field requires touching 6 files. Redesign so the change is local.

## 与 Hermes 的关系

Hermes 的分层（L0-L4）就是 deep-module 原则的应用：
- L1 loop.py（2156 行，深模块）：小接口（init/run/audit/advance），大实现
- L2 orchestrator.py（968 行）：小接口（fan_out/fan_in/aggregate），大实现
- L4 main.py（230 行）：薄入口，无实现

反例（待改进）：workbench/dashboard.py 无测试 = 无 seam。

## Completion criteria
- [ ] 词汇表覆盖 7 个核心概念（Module / Interface / Depth / Seam / Adapter / Leverage / Locality）
- [ ] 每个概念有定义 + 示例
- [ ] 评估问题章节可操作（5 个问题对应 5 个概念）
- [ ] 反模式章节列出了 ≥4 个常见反模式
- [ ] 与 Hermes 的关系章节映射到实际代码（非泛泛而谈）

## Related skills

- **improve-codebase-architecture**: 架构改进机会分析 + HTML 报告。本 skill 是**词汇表**（参考型，提供讨论语言），improve-codebase-architecture 是**流程型**（使用本 skill 的词汇检测机会）。组合使用：先学本 skill 词汇，再用 improve-codebase-architecture 分析。
- **domain-modeling**: 领域建模。本 skill 讨论代码架构，domain-modeling 讨论业务领域概念。
- **code-review**: 代码审查。本 skill 提供架构词汇，code-review 的 Standards 轴可用这些词汇检测 smell。

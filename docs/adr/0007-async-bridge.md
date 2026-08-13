# ADR 0007: async bridge 正式化 —— `asyncio.to_thread` 桥 + 双 helper

Status: Accepted
Date: 2026-08-13

## Context

ADR-0004 确立了「Workbench 同步基线、异步收敛到 FastAPI 层」的边界，但只约定
了原则（「跨边界必须有 `to_thread` 桥接注释」），没有落地的代码入口。实际开发
中每次跨边界都手写 `asyncio.to_thread` / `asyncio.run`，导致：

1. 样板重复、语义不统一（有人用 `run_until_complete`、有人用 `run`）；
2. 在 event loop 内误调 `run_async_in_sync` 会抛难以排查的
   `RuntimeError: This event loop is already running`；
3. 新成员无法从代码中看出「同步→异步」「异步→同步」两条路径的规范用法。

## Decision

新增 `hermes/workbench/async_bridge.py`，提供两个零依赖 helper 作为唯一跨边界
入口：

- `run_async_in_sync(coro)`：同步代码调用 awaitable。无运行中的 loop 时用
  `asyncio.run` 起新 loop；已处于 event loop 内则抛 `RuntimeError`，强制调用方
  改为直接 `await`（「await directly」规则），从源头消除嵌套 loop 死锁。
- `run_sync_in_async(fn, *args, **kwargs)`：异步代码调用阻塞同步 callable，
  内部走 `asyncio.to_thread`，避免阻塞 event loop。

调度器/agent_loop 等核心层**不**改为 async；content_team 的 FastAPI handler
需要调用同步 workbench 能力时，一律经 `run_sync_in_async` 桥接。

## Consequences

- **正面**：边界语义单一来源，嵌套 loop 死锁被显式拒绝；新代码有明确模式可循。
- **负面 / tradeoff**：`run_async_in_sync` 每次新建 event loop，高频调用有开销；
  已处于 async 上下文的调用方需自行 `await`（多一行样板）。
- **后续约束**：跨边界调用必须经 `async_bridge`，禁止在 event loop 内直接
  `time.sleep` / 同步 `urllib` / 阻塞 subprocess（延续 ADR-0004）。

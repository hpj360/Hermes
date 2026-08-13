# ADR 0004: 同步/异步边界 —— Workbench 保持同步基线，异步仅限 FastAPI 层

Status: Accepted
Date: 2026-08-13

## Context

Hermes 存在两套运行时：`hermes/workbench/` 全栈 stdlib + `threading` + 同步
`urllib`；`content_team/` 引入 asyncio + FastAPI + SQLAlchemy[asyncio]。二者并存
带来三个隐患：

1. 调度器双实现（`workbench.scheduler.WorkerPool` daemon thread vs
   `content_team.scheduler` APScheduler）；
2. 同步代码在 asyncio event loop 中被阻塞调用（或反之），易死锁；
3. 跨边界调用 subprocess 时进程树与信号语义不一致。

## Decision

- **核心/Workbench 层保持同步基线**：`threading` + stdlib，作为可复用、零依赖的
  底层。不引入 asyncio。
- **异步边界收敛到 FastAPI 层**：仅 `content_team` 的 HTTP 入口与业务 service
  使用 asyncio；需要调用同步 workbench 能力时用 `asyncio.to_thread` 桥接，禁止
  在 event loop 内直接 `time.sleep` / 同步 `urllib` / 阻塞式 subprocess。
- **调度器统一**：`content_team` 的定时发布沿用 `hermes.workbench.triggers`
  的 CronScheduler；APScheduler 仅在确需秒级/复杂 cron 时作为可选 backend
  注册，不作为默认。

## Consequences

- **正面**：核心层零依赖、可独立测试；异步复杂度被隔离；调度语义单一来源。
- **负面 / tradeoff**：FastAPI 层调用同步能力需显式 `to_thread`，有少量样板；
  长任务仍受 GIL 限制。
- **后续约束**：新增业务模块先判断属于"核心能力"（同步）还是"HTTP 服务"
  （异步），跨边界必须有 `to_thread` 桥接注释。

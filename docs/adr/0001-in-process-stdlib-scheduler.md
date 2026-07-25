# ADR 0001: 进程内 stdlib-only 调度，不引入外部消息队列

Status: Accepted
Date: 2026-07-25

## Context

Phase 3 调度中心需要后台异步执行 job、支持优先级队列与跨项目路由。业界常见方案是引入 Redis/RabbitMQ + Celery/RQ 等成熟调度框架，获得持久化、崩溃恢复、多 worker 进程、水平扩展等能力。

但 Hermes Workbench 运行时层自 v0.2.0 起遵循**零外部运行时依赖**原则（仅依赖 pydantic/pydantic-settings/python-dotenv，HTTP 用 stdlib urllib），且 `architecture.md` §11 明确声明"单机场景，适合单人或小团队使用"。

## Decision

采用**进程内 stdlib-only 调度**：`threading.Thread` (daemon) + `queue.PriorityQueue` + `threading.Lock` + `ThreadingHTTPServer`，不引入 Redis/RabbitMQ/Celery 等外部依赖。worker 池在 HTTP server 进程内运行，job 状态持久化到本地 `.state/jobs.json`。

## Consequences

- **正面**：保持零外部依赖原则，部署仅需 Python 3.10+；与现有 `TaskScheduler`/`AgentLoop`/`Orchestrator` 无缝集成；测试无需启动外部服务
- **负面 / tradeoff**：
  - 进程重启后未完成 job 不自动恢复（标记 ABANDONED），需人工 resubmit
  - 单进程内调度，worker 数受 GIL 限制（IO 密集型尚可，CPU 密集型并行度有限）
  - 无法水平扩展到多机；队列容量受进程内存限制
  - 无跨进程 job 可见性（多个 hermes 实例不共享队列）
- **后续约束**：若未来需要崩溃恢复或多机调度，需引入外部 broker，届时 WorkerPool/JobStore 接口需重构为 broker-backed 实现；当前 Router/ProjectRuntime/ScheduledJob 抽象可复用，仅替换底层 queue/store

# ADR 0008: JobQueue 抽象为 Backend 协议（in-memory / broker 双实现）

Status: Accepted
Date: 2026-08-13

## Context

Phase 3 调度中心（ADR-0001）采用进程内 stdlib-only 的 `JobQueue`
（`queue.PriorityQueue`），单机可用但无法跨进程/多机共享队列。P2-3 需要为
未来多机调度预留 broker 接口，但又不引入 Redis/RabbitMQ 作为运行时依赖。

## Decision

把队列能力抽象为 :class:`JobQueueBackend` 协议（``put`` / ``get`` / ``size``），
不引入任何新运行时依赖：

- `JobQueue` 保持为默认 in-memory 实现（stdlib `queue.PriorityQueue`）。
- `WorkerPool` 的 ``queue`` 参数类型从具体 `JobQueue` 放宽为 `JobQueueBackend`
  协议，执行逻辑不变。
- broker 适配器（Redis Streams / RQ / RabbitMQ）只需实现该协议，把
  `ScheduledJob` 序列化为 JSON 后读写 broker 即可；本仓不内置任何 broker 实现。

## Consequences

- **正面**：多机调度的扩展点已就位；不改变现有单机行为；无新增依赖。
- **负面 / tradeoff**：broker 实现需外部服务与序列化层，本仓只约定接口不
  提供实现；跨进程一致性（去重/幂等）由未来 broker 适配器自行保证。
- **后续约束**：新增 broker 后端时，必须在适配器中处理 `ScheduledJob` 的
  JSON 序列化/反序列化与优先级排序，保持 ``get`` 语义与 `JobQueue` 一致
  （阻塞 + `EmptyError`）。

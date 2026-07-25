# ADR 0003: DAG 上游失败时级联取消下游，不自动重试子图

Status: Accepted
Date: 2026-07-25

## Context

任务 DAG 依赖（`ScheduledJob.depends_on`）引入后，当某个 job 失败（`FAILED` / `CANCELLED` / `TIMEOUT` / `ABANDONED`）时，依赖它的下游 job 有几种处理策略：

1. **级联重试**：自动重跑整个下游子图，假设上游修复后下游可成功
2. **级联取消**：把所有下游标 `CANCELLED`，让用户检查根因后手动 resubmit
3. **悬挂**：下游保持 `PENDING`，等待上游被人工修复并重跑成功后自动触发

## Decision

采用**级联取消（策略 2）**：`DependencyGraph.on_job_done` 在上游非 `SUCCEEDED` 时，递归将所有下游标 `CANCELLED`，`error` 字段记录 `"upstream {job_id} {status}"`。DAG 深度上限 10 防止递归栈溢出。

## Consequences

- **正面**：
  - 语义清晰：上游失败意味着下游的输入不可信，强行重跑大概率再次失败，浪费资源
  - 可审计：`CANCELLED` 的 `error` 字段指明根因 job，用户可顺藤摸瓜修复上游
  - 避免重试风暴：上游若因环境问题（如 token 失效）失败，自动重试下游会重复撞墙
  - 实现简单：递归取消是 O(N) 操作，无需复杂的子图状态机
- **负面 / tradeoff**：
  - 上游修复后需用户手动 resubmit 整个下游子图，体验略差
  - 不区分失败原因：上游 `TIMEOUT`（可能瞬时）与 `FAILED`（可能持久）都一视同仁地取消下游
  - 深度上限 10 在极端长链场景下会截断，但单机调度场景下 10 层已足够（超出通常是设计问题）
- **后续约束**：若未来需要"上游修复后自动重跑下游"，需引入子图重试策略与上游修复检测机制；当前 `JobStore` 不记录 job 间的修复历史，无法判断上游是否已被修复；届时 `DependencyGraph` 需扩展 `retry_subtree(job_id)` 接口

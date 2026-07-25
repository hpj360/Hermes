# ADR 0002: 崩溃恢复仅重入 QUEUED，RUNNING 一律标 ABANDONED

Status: Accepted
Date: 2026-07-25

## Context

进程内调度（ADR 0001）在进程重启后会丢失内存中的 worker 状态，但 `jobs.json` 持久化了所有 job 的 `status`。重启后如何处理 `PENDING` / `QUEUED` / `RUNNING` 三种非终态的 job 有多种策略：

1. **全部重跑**：把三种状态都重新入队执行
2. **全部放弃**：把三种状态都标 `ABANDONED`，让用户手动 resubmit
3. **分级恢复**：`QUEUED` 重入队（job 已准备好但 worker 未消费），`RUNNING` 标 `ABANDONED`（无法判断执行到哪一步），`PENDING` 保留（等待显式提交或 DAG 上游）

## Decision

采用**分级恢复（策略 3）**：`RecoveryManager` 在进程启动时扫描 `jobs.json`，`QUEUED` 重新入队，`RUNNING` 标 `ABANDONED`，`PENDING` 保持不变。恢复动作记录到 L2 episode。

## Consequences

- **正面**：
  - `QUEUED` 的 job 不丢失，用户无需手动 resubmit，体验接近"无感恢复"
  - `RUNNING` 不冒险重跑——job 内部的 `TaskScheduler.run` 可能已部分执行（如已写 L1 facts、追加 L2 episodes），重跑会导致副作用重复
  - `PENDING` 保留语义清晰：要么等待 DAG 上游，要么等待显式 `submit`，恢复时无法判断该走哪条路径
  - 恢复动作记 L2 episode，可审计
- **负面 / tradeoff**：
  - `RUNNING` 的 job 需要人工 resubmit，体验略差
  - 不做 write-ahead log，无法知道 `RUNNING` 的 job 执行到第几个 step，因此无法断点续传
  - 如果 `jobs.json` 在崩溃时损坏（写到一半），`safe_read_json` 会回退到空列表，所有历史 job 丢失（依赖现有 `persistence.py` 的容错：损坏文件重命名为 `*.corrupt`）
- **后续约束**：若未来需要 `RUNNING` 的断点续传，需引入 step 级别的执行日志（StepExecution 落盘），届时 RecoveryManager 可改为按 step 恢复；当前 JobExecution 粒度太粗（只有 attempt 级），不支持

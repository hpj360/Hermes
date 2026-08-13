# ADR 0006: JobStore 从单文件 JSON 迁移到 SQLite（WAL）

Status: Accepted
Date: 2026-08-13

## Context

`JobStore` 原为 `jobs.json` 单文件 + `threading.Lock` 串行化读改写。缺陷：

1. 每次 `save` 全量序列化整个 dict 落盘，高频 job 写争锁、O(N) 写放大；
2. `update_status` 也要全量重写文件；
3. 进程内锁无法覆盖多进程（多 hermes 实例共享 `.state` 时）。

## Decision

改用 stdlib `sqlite3`（WAL 模式）存储 job，保持 `JobStore` 公共接口不变：

- 表结构 `jobs(job_id PK, status, target_project, payload)`，`status`/
  `target_project` 建索引，`payload` 存 JSON 文本。
- 线程安全沿用 thread-local connection（与 `FTS5Index` 一致），避免 sqlite3
  连接跨线程使用的 `ProgrammingError`。
- `__init__` 时若检测到旧 `jobs.json` 且 SQLite 为空，自动迁移（`INSERT OR IGNORE`，
  幂等）；旧文件保留 30 天宽限，不主动删除。

## Consequences

- **正面**：并发写不再争全局锁；状态查询走索引；持久化原子性由 SQLite 保证。
- **负面 / tradeoff**：`safe_read_json` 的"损坏文件改名 .corrupt"语义不再适用于
  job 数据（SQLite 自带损坏检测）；多进程仍需靠 WAL 锁，未做跨进程事务协调。
- **后续约束**：`jobs.json` 迁移后保留，未来清理需显式删除并记录；若需跨机
  调度，JobStore 接口保持，仅替换底层为 broker-backed（见 ADR-0001）。

# Context

## Glossary

| Term | Meaning | Notes |
|---|---|---|
| ScheduledJob | 调度中心的基本单元，封装 Task + target_project + priority + retry_policy | Phase 3 引入；区别于 Task（执行单元） |
| JobExecution | 一次 job 执行尝试的记录（attempt_num/status/error/trace_id） | 一个 ScheduledJob 可有多次 attempts（重试） |
| JobStatus | job 生命周期状态枚举：PENDING/QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED/TIMEOUT/ABANDONED | ABANDONED 仅用于进程重启后未恢复的 job |
| ProjectConnection | 已注册项目的连接配置（local/github/api 三类，含 state_dir/skills_dir/config） | "default" 项目始终存在，指向全局 hermes_state_dir |
| ProjectRuntime | 单个项目的运行时捆绑（SkillRunner + MemoryService + AgentLoop + Tracer），懒加载 | 由 Router 按 target_project 解析得到 |
| Router | 按 job.target_project 解析到 ProjectRuntime 的路由层 | 未找到抛 NotFoundError |
| JobQueue | 线程安全优先级队列，`(priority, seq)` 排序，同优先级 FIFO | 基于 stdlib queue.PriorityQueue |
| WorkerPool | N 个 daemon worker 线程，从 JobQueue 消费 job 执行 | N 默认 2，可配置 |
| JobStore | ScheduledJob + JobExecution 的持久化层，threading.Lock 保护读改写 | 落盘到 .state/jobs.json |
| StatusBus | 进程内 pub/sub，worker 发布 job 状态变更，SSE handler 订阅 | Queue 满时丢弃旧事件 |
| RetryPolicy | 重试策略：max_retries + 指数退避（base_delay * 2^attempt，上限 max_delay） | max_retries=0 表示不重试 |

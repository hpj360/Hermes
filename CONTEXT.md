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
| Trigger | 触发器定义，绑定 job 模板，支持 cron（定时）与 manual（手动）两类 | 被 TriggerStore 管理；Cron 触发时实例化 ScheduledJob |
| TriggerStore | Trigger 的持久化层，落盘到 .state/triggers.json | 与 JobStore 同样的 Lock 模式 |
| CronScheduler | 后台 daemon 线程，每 60s 扫描启用的 cron trigger，匹配则实例化 job 入队 | 最小粒度分钟；同分钟内不重复触发（last_fired_at 去重） |
| RecoveryManager | 进程启动时扫描 jobs.json，QUEUED 重新入队、RUNNING 标 ABANDONED、PENDING 保留 | 恢复动作记 L2 episode（kind="recovery"）；开关 HERMES_SCHEDULER_RECOVERY |
| DependencyGraph | DAG 依赖管理，job_id → depends_on 映射，提交时环检测，完成回调触发下游入队或级联取消 | DAG 深度上限 10，防递归栈溢出 |
| AssetSync | 跨项目资产同步引擎，单向（源→目标），支持 skills/memory/profile/all 四种 scope | skills 复制文件；memory 合并 facts+追加 episodes 去重；profile 浅合并 JSON 顶层 |
| SyncResult | AssetSync.sync 的返回，含 ok/scope/source/targets/synced_count/errors | |

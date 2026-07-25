# Phase 3 调度中心（Scheduling Center）Spec

> Status: ALIGNED
> Author: Hermes Agent
> Last updated: 2026-07-25
> Mode: default (2 waves, scope-expanded)
> Final ambiguity: ~22%

## Background

Workbench 运行时当前（v0.2.0）的 `TaskScheduler.run` 是**同步阻塞**的：`POST /tasks/{id}/run` 会在一个请求线程内跑完整任务（或整个 loop 循环），期间无法接受新的执行请求，也无法取消正在运行的任务。`TaskRegistry` 是进程内字典，`TaskStore` 是单个扁平 `tasks.json`，没有跨项目概念、没有队列、没有 worker 池、没有路由层、没有定时触发、没有崩溃恢复、没有任务依赖、没有跨项目资产同步。

Phase 3 在现有 `TaskScheduler` + `AgentLoop` + `Orchestrator` 之上，构建一个**完整的进程内调度中心**，覆盖：后台异步执行 + 跨项目路由 + 优先级队列 + 限流 + 超时 + 重试 + Cron 定时触发 + 崩溃恢复 + 任务 DAG 依赖 + 跨项目资产同步 + 状态流式 API + 指标看板。全部使用 Python 标准库（`threading` / `queue` / `concurrent.futures` / `sched`），保持零外部依赖原则。

## In scope

### 3.1 核心调度（Core Scheduling）

- **JobQueue**：线程安全优先级队列，`(priority, seq)` 排序，同优先级 FIFO
- **WorkerPool**：N 个 daemon worker 线程从队列消费 job，N 可配置（默认 2）
- **ScheduledJob**：调度单元，封装 `Task` + `target_project` + `priority` + `retry_policy` + `timeout` + `depends_on`
- **JobStore**：job 定义 + 执行历史持久化，`threading.Lock` 保护读改写
- **Job 生命周期状态机**：`PENDING → QUEUED → RUNNING → SUCCEEDED | FAILED | CANCELLED | TIMEOUT | ABANDONED`
- **协作式取消**：每个 job 持有 `cancel_event`，worker 在步骤间检查
- **重试策略**：`max_retries` + 指数退避（`base_delay * 2^attempt`，上限 `max_delay`）
- **超时**：`ScheduledJob.timeout`（秒），worker 起独立计时线程，超时设置 `cancel_event` 并标 `TIMEOUT`

### 3.2 跨项目路由（Cross-Project Routing）

- **ProjectRegistry**：项目注册表（local/github/api 三类），每个项目独立 `state_dir` / 技能集 / 配置 / `max_concurrent`，持久化到 `.state/projects.json`
- **ProjectRuntime**：捆绑单个项目的 `SkillRunner` + `MemoryService` + `AgentLoop` + `Tracer`，懒加载
- **Router**：按 job 的 `target_project` 解析到对应 `ProjectRuntime`；未声明时落到 default 项目
- **并发限流**：`ProjectConnection.max_concurrent`（默认 1），Router 维护每项目 in-flight 计数，超限的 job 留在队列或标 `QUEUED` 等待

### 3.3 定时触发（Cron Triggers）

- **TriggerStore**：触发器定义持久化到 `.state/triggers.json`
- **Trigger** dataclass：`trigger_id` / `workflow_id`（绑定 ScheduledJob 模板）/ `trigger_type`（`"cron"` | `"manual"`）/ `config`（cron 表达式）/ `enabled`
- **CronScheduler**：后台 daemon 线程，每 60s 扫描启用的 cron trigger，匹配当前时间则从模板实例化 ScheduledJob 入队
- **cron 表达式**：标准 5 字段（分 时 日 月 周），支持 `*` / 数字 / `,` / `-` / `/`，不支持秒与命名别名
- **手动触发**：`POST /triggers/{id}/fire` 立即从模板实例化 job 入队

### 3.4 崩溃恢复（Crash Recovery）

- **RecoveryManager**：进程启动时扫描 `jobs.json`，将 `PENDING` / `QUEUED` / `RUNNING` 状态的 job 处理如下：
  - `PENDING` → 保持 `PENDING`（尚未入队，可重新提交）
  - `QUEUED` → 重新入队（job 已准备好，只是 worker 未消费）
  - `RUNNING` → 标记 `ABANDONED`（无法判断执行到哪一步，不可安全恢复）
- **恢复开关**：`HERMES_SCHEDULER_RECOVERY`（默认 `true`），关闭则跳过恢复直接标 `ABANDONED`
- **恢复日志**：恢复动作记录到 L2 episode（`kind="recovery"`）

### 3.5 任务 DAG 依赖（Task Dependencies）

- **DependencyGraph**：维护 `job_id → depends_on: list[str]` 映射
- **入队规则**：job 的所有 `depends_on` 全部为 `SUCCEEDED` 时才入队；任一上游 `FAILED` / `CANCELLED` / `TIMEOUT` / `ABANDONED` → 当前 job 标 `CANCELLED`（级联取消）
- **检测环**：提交带 `depends_on` 的 job 时做 DFS 环检测，有环则 `400 ValidationError`
- **状态变更回调**：job 完成后 WorkerPool 调用 `DependencyGraph.on_job_done(job_id, status)`，触发下游检查

### 3.6 跨项目资产同步（Asset Sync）

- **AssetSync** engine：在项目间同步 skill / memory / profile
- **SyncScope**：`"skills"` | `"memory"` | `"profile"` | `"all"`
- **同步方向**：源项目 → 目标项目列表（单向，不自动回写）
  - `skills`：复制 `skills_dir` 下的 SKILL.md + entrypoint 文件到目标项目 `skills_dir`
  - `memory`：合并 L1 facts（源覆盖目标同 key）+ 追加 L2 episodes（去重 by `episode.id`）
  - `profile`：浅合并 `data/profile.json` 顶层字段（源覆盖目标）
- **SyncResult** dataclass：`ok` / `scope` / `source` / `targets` / `synced_count` / `errors`
- **CLI**：`hermes workbench sync --source proj-a --target proj-b --scope all`
- **HTTP**：`POST /sync` body `{source, targets, scope}`

### 3.7 状态流式 API 与指标

- **StatusBus**：进程内 pub/sub，worker 发布 job 状态变更，SSE handler 订阅
- **SSE**：`GET /stream/jobs` 推送 job 状态变更事件
- **Metrics**：`GET /jobs/metrics` 返回聚合指标
  - `total` / `succeeded` / `failed` / `cancelled` / `timeout` / `abandoned`
  - `success_rate`
  - `avg_duration_ms` / `p95_duration_ms`
  - `avg_queue_wait_ms` / `p95_queue_wait_ms`
  - `queue_depth`（当前）
  - `workers_active` / `workers_idle`

### 3.8 CLI 与 HTTP 接口

- **CLI 子命令**：
  - `hermes workbench job submit/list/show/cancel/retry`
  - `hermes workbench project add/list/show/remove/ping`
  - `hermes workbench trigger add/list/show/fire/enable/disable`
  - `hermes workbench sync --source --target --scope`
  - `hermes workbench job metrics`
- **HTTP 路由**：
  - `POST /jobs` / `GET /jobs` / `GET /jobs/{id}` / `POST /jobs/{id}/cancel` / `POST /jobs/{id}/retry` / `GET /jobs/metrics` / `GET /stream/jobs`
  - `POST /projects` / `GET /projects` / `GET /projects/{id}` / `DELETE /projects/{id}` / `POST /projects/{id}/ping`
  - `POST /triggers` / `GET /triggers` / `GET /triggers/{id}` / `POST /triggers/{id}/fire` / `POST /triggers/{id}/enable` / `POST /triggers/{id}/disable`
  - `POST /sync`
- **健康检查扩展**：`/health` 返回 `scheduler: {workers: {active, idle}, queue_depth, recovery: "done"|"skipped"}`

## Out of scope

- **分布式 worker / 多机调度**：不引入 Redis / RabbitMQ / Celery；保持单机 stdlib
- **资源感知调度**：不做 CPU/内存感知的动态 worker 扩缩容（固定 N，可配置）
- **多租户隔离**：单用户场景，不做租户级资源配额
- **Webhook 触发**：本阶段不做外部 webhook 触发（仅 cron + manual；webhook 属后续扩展）
- **跨项目资产双向同步**：仅做单向（源→目标），不自动回写
- **skill 版本管理**：同步时全量覆盖，不做增量 diff 或版本号
- **任务子图重试**：DAG 中某节点失败后不自动重试整个子图，仅级联取消下游
- **持久化 WAL**：崩溃恢复基于 `jobs.json` 快照，不做 write-ahead log

## Assumptions

- 单机部署，单进程内调度；不跨进程/跨机器
- worker 线程数 N 默认 2，可通过 `--workers` 或 `HERMES_SCHEDULER_WORKERS` 配置
- "跨项目"指多个本地项目配置（不同 `state_dir` / 技能集 / git url），不是远程 worker
- default 项目始终存在，指向当前 `hermes_state_dir`，保证旧 `POST /tasks` 接口向后兼容
- job 执行仍委托现有 `AgentLoop.execute` / `TaskScheduler.run` / `Orchestrator`，调度中心只负责排队/路由/生命周期，不重新实现执行逻辑
- `queue.PriorityQueue` 的入队是线程安全的；`JobStore` 的读改写需显式 `Lock`
- SSE 复用现有 `/stream/episodes` 的实现模式（`ThreadingHTTPServer` + 轮询 + `wfile.write`）
- cron 最小粒度为分钟，扫描间隔 60s（不保证秒级精度）
- 崩溃恢复仅恢复 `QUEUED` 状态；`RUNNING` 一律标 `ABANDONED`（无法安全断点续传）
- DAG 依赖检查由 WorkerPool 在 job 完成回调中同步触发，不另起线程
- 资产同步是显式触发的同步操作（CLI/HTTP），不是后台自动同步
- ProcessPool 不可行：`SkillRunner` / `MemoryService` / `AgentLoop` 持有文件句柄与不可 pickle 的状态，跨进程传递 overhead 大于 GIL 收益

## Solution

### 架构总览

```
                         ┌─────────────────────────────────────────┐
   POST /jobs ──────────▶│              Router                     │
   CronScheduler ──────▶│  job.target_project → ProjectRuntime     │
   DependencyGraph ─────▶│  + max_concurrent 限流                  │
                         └──────────────┬──────────────────────────┘
                                        ▼
                         ┌─────────────────────────────────────────┐
                         │          JobQueue                       │
                         │  PriorityQueue((priority, seq), job)    │
                         └──────────────┬──────────────────────────┘
                                        ▼
              ┌─────────────────────────┴─────────────────────────┐
              ▼                       ▼                           ▼
        ┌──────────┐           ┌──────────┐               ┌──────────┐
        │ Worker 0 │           │ Worker 1 │      ...      │ Worker N │
        │ (daemon) │           │ (daemon) │               │ (daemon) │
        └────┬─────┘           └────┬─────┘               └────┬─────┘
             │                      │                          │
             └──────────┬───────────┴──────────────────────────┘
                        ▼
              ┌─────────────────────┐         ┌─────────────────────┐
              │   ProjectRuntime    │◀────────│  TimeoutWatcher     │
              │  ┌───────────────┐  │         │  独立计时线程       │
              │  │ SkillRunner   │  │         │  超时→cancel_event  │
              │  ├───────────────┤  │         └─────────────────────┘
              │  │ MemoryService │  │
              │  ├───────────────┤  │
              │  │  AgentLoop    │  │
              │  ├───────────────┤  │
              │  │   Tracer      │  │
              │  └───────────────┘  │
              └─────────┬───────────┘
                        │
                        ▼
              ┌─────────────────────┐
              │      JobStore       │  ← Lock 保护读改写
              │  .state/jobs.json   │
              └─────────┬───────────┘
                        │
              ┌─────────┴───────────┐
              ▼                     ▼
   ┌─────────────────────┐  ┌─────────────────────┐
   │  DependencyGraph    │  │  SSE /stream/jobs   │  → 客户端实时状态
   │  on_job_done →      │  │  + StatusBus        │
   │  检查下游入队/级联  │  └─────────────────────┘
   └─────────────────────┘

   ┌─────────────────────────────────────────────────────────────┐
   │                  启动时恢复                                  │
   │  RecoveryManager 扫描 jobs.json                            │
   │  PENDING→保留  QUEUED→重新入队  RUNNING→ABANDONED          │
   └─────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────┐
   │                  定时触发                                    │
   │  CronScheduler (daemon, 60s 扫描)                          │
   │  匹配 cron → 从 trigger 模板实例化 ScheduledJob → 入队      │
   └─────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────┐
   │                  资产同步（显式触发）                        │
   │  AssetSync.sync(source, targets, scope)                    │
   │  skills: 复制文件  memory: 合并 facts+追加 episodes         │
   │  profile: 浅合并 JSON 顶层                                  │
   └─────────────────────────────────────────────────────────────┘
```

### 核心数据结构

```python
@dataclass
class RetryPolicy:
    max_retries: int = 0          # 0 = 不重试
    base_delay: float = 2.0       # 指数退避基数
    max_delay: float = 60.0       # 退避上限

class JobStatus(str, Enum):
    PENDING = "PENDING"           # 已创建未入队（含等待 DAG 上游）
    QUEUED = "QUEUED"             # 已入队等待 worker
    RUNNING = "RUNNING"           # worker 正在执行
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"             # 失败（含重试耗尽）
    CANCELLED = "CANCELLED"       # 被取消（含 DAG 级联）
    TIMEOUT = "TIMEOUT"           # 超时
    ABANDONED = "ABANDONED"       # 进程重启后未恢复（原 RUNNING）

@dataclass
class ScheduledJob:
    job_id: str                   # uuid4
    task: Task                    # 复用现有 Task dataclass
    target_project: str = "default"
    priority: int = 5             # 1(最高) - 10(最低)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout: float | None = None  # 秒，None=不限
    depends_on: list[str] = field(default_factory=list)  # job_id 列表
    status: JobStatus = JobStatus.PENDING
    attempts: list[JobExecution] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    created_at: str = ...
    submitted_by: str = "cli"     # "cli" | "api" | "cron" | "loop"
    queued_at: str | None = None  # 入队时间（用于计算 queue_wait）
    started_at: str | None = None # 首次 RUNNING 时间

@dataclass
class JobExecution:
    attempt_num: int
    started_at: str
    ended_at: str | None
    status: JobStatus             # RUNNING / SUCCEEDED / FAILED / TIMEOUT
    error: str | None
    trace_id: str | None
    round_summary: dict | None    # 来自 TaskScheduler.run 的 round
```

### ProjectConnection 与路由限流

```python
@dataclass
class ProjectConnection:
    id: str                       # "default" | "proj-xxx"
    name: str
    project_type: str             # "local" | "github" | "api"
    state_dir: str
    skills_dir: str | None        # None = 继承全局
    config: dict                  # url/token/branch 等
    max_concurrent: int = 1       # 该项目同时运行 job 上限
    health: str = "unknown"       # "connected" | "disconnected" | "unknown"

class ProjectRuntime:
    """懒加载：首次路由到该项目时才实例化 runner/memory/loop。"""
    def __init__(self, conn: ProjectConnection): ...
    def runner(self) -> SkillRunner: ...
    def memory(self) -> MemoryService: ...
    def loop(self) -> AgentLoop: ...
    def scheduler(self) -> TaskScheduler: ...

class Router:
    def __init__(self, registry: ProjectRegistry): ...
    def resolve(self, project_id: str) -> ProjectRuntime:
        """未找到抛 NotFoundError；'default' 永远存在。"""
    def try_acquire(self, project_id: str) -> bool:
        """获取并发槽位，超 max_concurrent 返回 False。"""
    def release(self, project_id: str) -> None:
        """释放并发槽位。"""
```

### WorkerPool 执行流（含超时与 DAG 回调）

```python
class WorkerPool:
    def _execute(self, job: ScheduledJob, runtime: ProjectRuntime):
        # 超时 watcher（独立线程）
        if job.timeout:
            t = threading.Timer(job.timeout, job.cancel_event.set)
            t.daemon = True; t.start()
        try:
            for attempt in range(job.retry_policy.max_retries + 1):
                exec_record = JobExecution(attempt_num=attempt, started_at=now(), status=RUNNING, ...)
                job.status = RUNNING; self._bus.emit(job)
                try:
                    if job.cancel_event.is_set():
                        exec_record.status = TIMEOUT if job.timeout else CANCELLED; break
                    scheduler = runtime.scheduler()
                    scheduler.run(job.task.task_id)
                    if job.cancel_event.is_set():
                        exec_record.status = TIMEOUT if job.timeout else CANCELLED; break
                    exec_record.status = SUCCEEDED; job.status = SUCCEEDED; break
                except TimeoutError:
                    exec_record.status = TIMEOUT
                except Exception as e:
                    exec_record.status = FAILED; exec_record.error = str(e)
                finally:
                    exec_record.ended_at = now()
                    job.attempts.append(exec_record)
                    self._store.save(job)
                    self._bus.emit(job)
                if attempt < job.retry_policy.max_retries:
                    delay = min(job.retry_policy.base_delay * 2**attempt, job.retry_policy.max_delay)
                    time.sleep(delay)
            if job.status == RUNNING:
                job.status = FAILED
        finally:
            if job.timeout: t.cancel()
            self._router.release(job.target_project)
            self._dep_graph.on_job_done(job.job_id, job.status)  # DAG 回调
            self._store.save(job)
            self._bus.emit(job)
```

### CronScheduler

```python
@dataclass
class Trigger:
    trigger_id: str
    job_template: dict             # ScheduledJob 的序列化模板（不含 job_id/status/attempts）
    trigger_type: str              # "cron" | "manual"
    config: dict                   # {"cron": "30 9 * * *"} for cron type
    enabled: bool = True
    created_at: str

class CronScheduler:
    """daemon 线程，每 60s 扫描启用的 cron trigger。"""
    def _matches_cron(expr: str, dt: datetime) -> bool:
        """标准 5 字段 cron 匹配。"""
    def _loop(self):
        while not self._stop.is_set():
            now = datetime.now()
            for t in self._store.list_enabled_cron():
                if self._matches_cron(t.config["cron"], now):
                    job = ScheduledJob.from_template(t.job_template, submitted_by="cron")
                    self._submit(job)
            self._stop.wait(60.0)
```

### RecoveryManager

```python
class RecoveryManager:
    def recover(self) -> dict:
        """进程启动时调用，返回 {requeued, abandoned, skipped}。"""
        stats = {"requeued": 0, "abandoned": 0, "skipped": 0}
        for job in self._store.list():
            if job.status == JobStatus.PENDING:
                stats["skipped"] += 1       # 保留，等待显式提交
            elif job.status == JobStatus.QUEUED:
                self._queue.put(job); stats["requeued"] += 1
            elif job.status == JobStatus.RUNNING:
                job.status = JobStatus.ABANDONED
                self._store.save(job); stats["abandoned"] += 1
                self._memory.record_episode(make_episode("recovery", f"abandoned job {job.job_id}"))
        return stats
```

### DependencyGraph

```python
class DependencyGraph:
    def __init__(self, store: JobStore, queue: JobQueue):
        self._deps: dict[str, list[str]] = {}  # job_id -> depends_on
        self._dependents: dict[str, list[str]] = {}  # job_id -> 被谁依赖
        self._lock = threading.Lock()

    def register(self, job_id: str, depends_on: list[str]) -> None:
        """提交时调用，做环检测。有环抛 ValidationError。"""
        self._detect_cycle(job_id, depends_on)

    def ready_to_queue(self, job_id: str) -> bool:
        """所有 depends_on 状态为 SUCCEEDED。"""

    def on_job_done(self, job_id: str, status: JobStatus) -> None:
        """job 完成回调：上游成功→检查下游入队；上游失败→级联取消下游。"""
        if status == JobStatus.SUCCEEDED:
            for dep_id in self._dependents.get(job_id, []):
                if self.ready_to_queue(dep_id):
                    self._queue.put(self._store.get(dep_id))
        else:  # FAILED / CANCELLED / TIMEOUT / ABANDONED
            for dep_id in self._dependents.get(job_id, []):
                self._cascade_cancel(dep_id, reason=f"upstream {job_id} {status}")

    def _cascade_cancel(self, job_id: str, reason: str) -> None:
        job = self._store.get(job_id)
        job.status = JobStatus.CANCELLED
        self._store.save(job)
        self._bus.emit(job)
        for dep_id in self._dependents.get(job_id, []):
            self._cascade_cancel(dep_id, reason)
```

### AssetSync

```python
@dataclass
class SyncResult:
    ok: bool
    scope: str               # "skills" | "memory" | "profile" | "all"
    source: str
    targets: list[str]
    synced_count: int
    errors: list[str]

class AssetSync:
    def sync(self, source: str, targets: list[str], scope: str) -> SyncResult:
        src_runtime = self._router.resolve(source)
        results = []
        for tgt in targets:
            tgt_runtime = self._router.resolve(tgt)
            if scope in ("skills", "all"):
                self._sync_skills(src_runtime, tgt_runtime)
            if scope in ("memory", "all"):
                self._sync_memory(src_runtime, tgt_runtime)
            if scope in ("profile", "all"):
                self._sync_profile(src_runtime, tgt_runtime)
        return SyncResult(...)
```

### StatusBus（状态事件总线）

```python
class StatusBus:
    """进程内 pub/sub，worker 发布 job 状态变更，SSE handler 订阅。"""
    def emit(self, job: ScheduledJob): ...
    def subscribe(self) -> queue.Queue: ...
    def unsubscribe(self, q: queue.Queue): ...
```

### 向后兼容

- `POST /tasks`（旧接口）保持不变：内部转换为 `target_project="default"` 的 `ScheduledJob` 入队，但**默认同步等待**（`wait: true`）以保持旧语义
- `POST /jobs`（新接口）默认**异步**：返回 `job_id` + `202 Accepted`，客户端轮询或订阅 SSE
- `hermes workbench task run`（旧 CLI）保持同步语义；新增 `hermes workbench job submit` 走异步

## Edge cases & risks

| Category | Notes |
|---|---|
| **并发写 JobStore** | 多 worker 同时完成 job 会并发写 `jobs.json`；用 `threading.Lock` 串行化读改写，单次 `atomic_write_json` 落盘 |
| **worker 异常崩溃** | daemon 线程崩溃不会重启；worker 内 try/except 兜底，将 job 标 FAILED 而非让线程死亡；`/health` 暴露活跃 worker 数 |
| **队列积压** | 高优先级 job 饥饿低优先级；用 `(priority, seq)` 保证同优先级 FIFO，不实现 aging（超出范围） |
| **取消时序** | `cancel()` 设置 `cancel_event`，worker 在**步骤间**检查；正在执行的 `AgentLoop.execute` 不可中断；实际取消延迟 = 当前 step 剩余时间 |
| **超时与取消冲突** | `timeout` 触发与显式 `cancel()` 都设置同一 `cancel_event`；worker 通过 `job.timeout is not None` 区分标 `TIMEOUT` 还是 `CANCELLED` |
| **ProjectRuntime 懒加载失败** | github 项目 token 失效 → runner 构造失败 → job 标 FAILED，error 含诊断；不影响其他项目 |
| **进程重启** | `QUEUED` 重新入队，`RUNNING` 标 `ABANDONED`；`PENDING` 保留等待显式处理；恢复动作记 L2 episode |
| **SSE 订阅者断连** | `subscribe` 的 Queue 满 `put_nowait` 丢弃旧事件；SSE handler 捕获 `BrokenPipeError` 后 `unsubscribe` |
| **default 项目状态目录冲突** | default 项目 `state_dir` = 全局 `hermes_state_dir`，与现有 `tasks.json` / `facts.json` 共存；`jobs.json` 独立文件不冲突 |
| **TaskScheduler.run 内部 loop 模式长耗时** | loop 模式可能跑数分钟；worker 被占用期间不消费新 job；需文档提示 `max_rounds` 与 `workers` 配比 |
| **max_concurrent 死锁** | 项目 max_concurrent=2 但有 3 个同项目 job 在队列；前 2 个运行时第 3 个留在队列等待，worker 空闲也不消费（需 Router 在出队时检查）；解决方案：worker 出队后先 `try_acquire`，失败则 requeue 并 sleep 1s |
| **DAG 环检测** | 提交时 DFS 检测；环 → `400 ValidationError`；运行时不再检测（job 已入队后新增依赖会破坏图，禁止运行时修改 depends_on） |
| **DAG 级联取消风暴** | 上游失败触发深度级联；`_cascade_cancel` 递归实现，深度过大可能栈溢出；限制 DAG 深度 ≤ 10 |
| **CronScheduler 重复触发** | 60s 扫描间隔内同一 trigger 可能匹配多次（如 `* * * * *`）；记录 `last_fired_at`，同分钟内不重复触发 |
| **崩溃恢复与 Cron 冲突** | 恢复的 `QUEUED` job 与 Cron 新触发的 job 共存于队列，按 priority 排序；无冲突 |
| **资产同步并发** | 同步进行时目标项目正在运行 job；同步 skills 覆盖文件不影响运行中的 skill（已加载到内存）；同步 memory 用 `atomic_write_json` 不破坏正在追加的 episodes（不同文件） |
| **Trigger 模板与 ProjectConnection 不一致** | 模板中 `target_project` 指向已删除的项目；CronScheduler 触发时 Router 抛 NotFoundError → job 标 FAILED + 记录诊断；不阻塞其他 trigger |

## Acceptance criteria

### 核心调度

- **AC-1**：`POST /jobs` 提交一个 `target_project="default"` 的 job，立即返回 `202` + `job_id`；job 在 worker 池中异步执行，最终 `GET /jobs/{id}` 返回 `status: SUCCEEDED`
- **AC-2**：提交 3 个 `priority=1` 的 job + 2 个 `priority=5` 的 job 到单 worker 池，3 个高优先级 job 的 `started_at` 全部早于 2 个低优先级 job 的 `started_at`
- **AC-3**：`POST /jobs/{id}/cancel` 对一个 `QUEUED` 状态的 job，立即返回 `200`，job 状态变为 `CANCELLED` 且从未进入 `RUNNING`
- **AC-4**：`POST /jobs/{id}/cancel` 对一个 `RUNNING` 状态的 job，worker 在当前 `LoopStep` 完成后检查到 `cancel_event`，将 job 标记为 `CANCELLED`，不再继续后续 step
- **AC-5**：提交 `retry_policy={max_retries: 2, base_delay: 0.1}` 的 job，当首次执行抛异常时，job 经过 3 次 attempt（1 + 2 重试）后 `status=FAILED`，`attempts` 列表长度为 3

### 超时

- **AC-6**：提交 `timeout=1.0` 的 job（其 task plan 含一个 sleep 3s 的 step），worker 在 1s 后设置 `cancel_event`，job 在当前 step 完成后标 `TIMEOUT`，`attempts[-1].status == "TIMEOUT"`

### 跨项目路由与限流

- **AC-7**：注册一个 `project_type="local"` 的项目 `proj-a`（`state_dir=/tmp/proj-a`），提交 `target_project="proj-a"` 的 job，job 执行时读写的是 `/tmp/proj-a/` 下的 facts/episodes，而非全局 `.state/`
- **AC-8**：注册一个不存在的项目 `proj-x`，提交 `target_project="proj-x"` 的 job，返回 `404 NotFoundError`，job 不入队
- **AC-9**：注册 `proj-a`（`max_concurrent=2`），提交 5 个 `target_project="proj-a"` 的 job，同时处于 `RUNNING` 状态的不超过 2 个，其余保持 `QUEUED` 直到槽位释放

### Cron 定时触发

- **AC-10**：创建一个 `trigger_type="cron"`、`config={"cron": "* * * * *"}`（每分钟）的 trigger，60s 内 CronScheduler 自动从模板实例化一个 job 入队，`submitted_by="cron"`
- **AC-11**：`POST /triggers/{id}/fire` 立即从模板实例化 job 入队，返回 `job_id`
- **AC-12**：`POST /triggers/{id}/disable` 后，CronScheduler 不再扫描该 trigger；`POST /triggers/{id}/enable` 后恢复

### 崩溃恢复

- **AC-13**：提交 3 个 job 分别处于 `PENDING` / `QUEUED` / `RUNNING` 状态（通过 mock worker 模拟），调用 `RecoveryManager.recover()` 后，`QUEUED` 的重新入队，`RUNNING` 的标 `ABANDONED`，`PENDING` 的保持不变；恢复动作记录到 L2 episode（`kind="recovery"`）

### 任务 DAG

- **AC-14**：提交 job-A（无依赖），再提交 job-B（`depends_on=["job-A"]`），job-B 初始状态为 `PENDING`；job-A 完成为 `SUCCEEDED` 后，job-B 自动入队并最终 `SUCCEEDED`
- **AC-15**：job-A 失败后，依赖它的 job-B 自动标 `CANCELLED`，`job-B.attempts[0].error` 含 `"upstream job-A FAILED"`
- **AC-16**：提交 `depends_on=["job-A"]` 的 job-B，其中 job-B 又被 job-A 依赖（环），返回 `400 ValidationError`，job 不创建

### 跨项目资产同步

- **AC-17**：proj-a 有一个 `echo` skill，proj-b 没有；`POST /sync {source: "proj-a", targets: ["proj-b"], scope: "skills"}` 后，proj-b 的 `skills_dir` 下出现 `echo/SKILL.md`
- **AC-18**：proj-a 有 fact `k=v`，proj-b 有 fact `k=old`；`POST /sync {source: "proj-a", targets: ["proj-b"], scope: "memory"}` 后，proj-b 的 `k=v`（源覆盖目标）
- **AC-19**：`POST /sync` 对不存在的 source 项目返回 `404 NotFoundError`

### 状态流式 API 与指标

- **AC-20**：`GET /stream/jobs` SSE 连接后，提交一个新 job，客户端在 2 秒内收到至少 3 条状态事件（`QUEUED` → `RUNNING` → `SUCCEEDED`）
- **AC-21**：`GET /jobs/metrics` 返回 `total` / `succeeded` / `failed` / `success_rate` / `avg_duration_ms` / `p95_duration_ms` / `queue_depth` / `workers_active` / `workers_idle`；其中 `success_rate = succeeded / total`（保留 3 位小数）
- **AC-22**：`GET /health` 返回 `scheduler: {workers: {active: N, idle: M}, queue_depth: K, recovery: "done"}`，其中 `active + idle = workers_total`

### 向后兼容与 CLI

- **AC-23**：旧接口 `POST /tasks`（带 `run: true`）仍同步返回完整 task 结果，行为与 v0.2.0 一致
- **AC-24**：`hermes workbench job submit --plan '[{"skill":"echo"}]' --project proj-a --priority 1 --timeout 30` 返回 `job_id`；`hermes workbench job list` 列出该 job；`hermes workbench job show {id}` 显示状态与执行历史；`hermes workbench job metrics` 显示聚合指标
- **AC-25**：`hermes workbench project add/list/show/remove/ping` 与 `hermes workbench trigger add/list/show/fire/enable/disable` 与 `hermes workbench sync --source --target --scope` 全部可用

### 测试覆盖

- **AC-26**：`pytest tests/workbench/test_scheduler.py` 覆盖 AC-1 至 AC-25，`pytest tests/workbench/test_triggers.py` 覆盖 AC-10 至 AC-12，`pytest tests/workbench/test_recovery.py` 覆盖 AC-13，`pytest tests/workbench/test_dag.py` 覆盖 AC-14 至 AC-16，`pytest tests/workbench/test_sync.py` 覆盖 AC-17 至 AC-19；全部通过且 `ruff check` 无报错

## Open questions

无。范围与架构已通过用户确认（进程内调度 + 跨项目路由 + Cron + 崩溃恢复 + DAG + 资产同步，stdlib-only，线程池+限流）。

## Core entities (ontology)

| Entity | Type | Key fields | Relationship |
|---|---|---|---|
| `ScheduledJob` | dataclass | job_id, task, target_project, priority, retry_policy, timeout, depends_on, status, attempts | 包含 1 个 `Task`；属于 1 个 `ProjectConnection`；产生 N 个 `JobExecution`；可依赖 N 个 `ScheduledJob` |
| `JobExecution` | dataclass | attempt_num, started_at, ended_at, status, error, trace_id | 属于 1 个 `ScheduledJob` |
| `JobStatus` | Enum | PENDING/QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED/TIMEOUT/ABANDONED | `ScheduledJob.status` 与 `JobExecution.status` 共用 |
| `RetryPolicy` | dataclass | max_retries, base_delay, max_delay | 被 `ScheduledJob` 包含 |
| `ProjectConnection` | dataclass | id, name, project_type, state_dir, skills_dir, config, max_concurrent, health | 被 `ProjectRegistry` 管理；1:1 对应 `ProjectRuntime` |
| `ProjectRuntime` | class | conn, runner, memory, loop, scheduler | 由 `Router` 解析得到；懒加载 |
| `ProjectRegistry` | class | store, _runtimes | 管理 `ProjectConnection` 列表 |
| `Router` | class | registry, _inflight (dict) | `resolve(project_id) → ProjectRuntime`；`try_acquire` / `release` 限流 |
| `JobQueue` | class | _pq (PriorityQueue), _seq | 线程安全入队/出队 |
| `WorkerPool` | class | _workers[], _stop (Event) | 消费 `JobQueue`，调用 `ProjectRuntime` 执行，超时 watcher，DAG 回调 |
| `JobStore` | class | path, _lock | 持久化 `ScheduledJob` + `JobExecution` |
| `StatusBus` | class | _subscribers[], _lock | 发布 job 状态变更给 SSE 订阅者 |
| `Trigger` | dataclass | trigger_id, job_template, trigger_type, config, enabled | 被 `TriggerStore` 管理；Cron 触发时实例化 `ScheduledJob` |
| `TriggerStore` | class | path, _lock | 持久化 `Trigger` |
| `CronScheduler` | class | _stop (Event), _store, _queue, _last_fired | daemon 线程，60s 扫描 cron trigger |
| `RecoveryManager` | class | _store, _queue, _memory | 进程启动时恢复 `QUEUED` job，标 `ABANDONED` 给 `RUNNING` |
| `DependencyGraph` | class | _deps, _dependents, _lock, _store, _queue, _bus | DAG 依赖管理，环检测，级联取消 |
| `AssetSync` | class | _router | 跨项目同步 skills/memory/profile |
| `SyncResult` | dataclass | ok, scope, source, targets, synced_count, errors | `AssetSync.sync` 返回 |

## Interview metadata

- Mode: default
- Waves: 2
- Final ambiguity: ~22%
- Status: PASSED

### Clarity breakdown

| Dimension | Score | Weight | Weighted |
|---|---|---|---|
| Goal | 0.90 | 0.40 | 0.36 |
| Scope | 0.85 | 0.25 | 0.2125 |
| AC | 0.80 | 0.25 | 0.20 |
| Context | 0.85 | 0.10 | 0.085 |
| **Ambiguity** | | | **~22.25%** |

### Ontology

- stable: `Task`, `AgentLoop`, `TaskScheduler`, `Orchestrator`, `MemoryService`, `SkillRunner`, `Tracer`（复用现有）
- new (wave 1): `ScheduledJob`, `JobExecution`, `JobStatus`, `RetryPolicy`, `ProjectConnection`, `ProjectRuntime`, `ProjectRegistry`, `Router`, `JobQueue`, `WorkerPool`, `JobStore`, `StatusBus`
- new (wave 2): `Trigger`, `TriggerStore`, `CronScheduler`, `RecoveryManager`, `DependencyGraph`, `AssetSync`, `SyncResult`

## Plan

详见后续 `dev-plan` 产出的 `.claude/artifacts/plans/phase3-scheduling-center.md`。

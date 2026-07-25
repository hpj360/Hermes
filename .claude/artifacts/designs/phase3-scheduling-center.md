# Phase 3 调度中心（Scheduling Center）Spec

> Status: ALIGNED
> Author: Hermes Agent
> Last updated: 2026-07-25
> Mode: default (1 wave, scope-confirmed)
> Final ambiguity: ~28%

## Background

Workbench 运行时当前（v0.2.0）的 `TaskScheduler.run` 是**同步阻塞**的：`POST /tasks/{id}/run` 会在一个请求线程内跑完整任务（或整个 loop 循环），期间无法接受新的执行请求，也无法取消正在运行的任务。`TaskRegistry` 是进程内字典，`TaskStore` 是单个扁平 `tasks.json`，没有跨项目概念、没有队列、没有 worker 池、没有路由层。

Phase 3 在现有 `TaskScheduler` + `AgentLoop` + `Orchestrator` 之上，增加**进程内后台调度 + 跨项目路由**能力，让一个任务可声明目标项目并异步执行，同时提供状态流式 API。全部使用 Python 标准库（`threading` / `queue` / `concurrent.futures`），保持零外部依赖原则。

## In scope

- **JobQueue**：线程安全优先级队列，支持 `(priority, seq)` 排序，同优先级 FIFO
- **WorkerPool**：N 个 daemon worker 线程从队列消费 job，N 可配置（默认 2）
- **ProjectRegistry**：项目注册表（local/github/api 三类），每个项目独立 `state_dir` / 技能集 / 配置，持久化到 `.state/projects.json`
- **ProjectRuntime**：捆绑单个项目的 `SkillRunner` + `MemoryService` + `AgentLoop` + `Tracer`
- **Router**：按 job 的 `target_project` 解析到对应 `ProjectRuntime`；未声明时落到 default 项目
- **ScheduledJob**：调度单元，封装 `Task` + `target_project` + `priority` + `retry_policy`
- **JobStore**：job 定义 + 执行历史持久化，`threading.Lock` 保护读改写
- **Job 生命周期状态机**：`PENDING → QUEUED → RUNNING → SUCCEEDED | FAILED | CANCELLED | TIMEOUT`
- **协作式取消**：每个 job 持有 `cancel_event`，worker 在步骤间检查
- **重试策略**：`max_retries` + 指数退避（`delay * 2^attempt`，上限 60s）
- **状态流式 API**：`GET /stream/jobs` SSE，推送 job 状态变更
- **CLI 子命令**：`hermes workbench job submit/list/show/cancel`
- **HTTP 路由**：`POST /jobs`、`GET /jobs`、`GET /jobs/{id}`、`POST /jobs/{id}/cancel`、`GET /stream/jobs`
- **健康检查扩展**：`/health` 返回 worker 池状态（active/idle/queue_depth）

## Out of scope

- **分布式 worker / 多机调度**：不引入 Redis / RabbitMQ / Celery；保持单机 stdlib
- **持久化崩溃恢复**：进程重启后未完成的 job 不自动恢复（标记为 `ABANDONED`，需人工 resubmit）
- **任务 DAG / 依赖图**：job 之间不支持依赖声明（plan 内部仍是 `LoopStep` 扁平列表）
- **Cron 定时调度**：本阶段不做定时触发（属后续 Trigger 模块）
- **Webhook 触发**：本阶段不做外部触发（属后续 Trigger 模块）
- **多租户隔离**：单用户场景，不做租户级资源配额
- **资源感知调度**：不做 CPU/内存感知的动态 worker 扩缩容
- **跨项目资产同步**：本阶段不做 skill/memory/profile 在项目间同步（属后续 Sync 模块）

## Assumptions

- 单机部署，单进程内调度；不跨进程/跨机器
- worker 线程数 N 默认 2，可通过 `--workers` 或 `HERMES_SCHEDULER_WORKERS` 配置
- "跨项目"指多个本地项目配置（不同 `state_dir` / 技能集 / git url），不是远程 worker
- default 项目始终存在，指向当前 `hermes_state_dir`，保证旧 `POST /tasks` 接口向后兼容
- job 执行仍委托现有 `AgentLoop.execute` / `TaskScheduler.run` / `Orchestrator`，调度中心只负责排队/路由/生命周期，不重新实现执行逻辑
- `queue.PriorityQueue` 的入队是线程安全的；`JobStore` 的读改写需显式 `Lock`
- SSE 复用现有 `/stream/episodes` 的实现模式（`ThreadingHTTPServer` + 轮询 + `wfile.write`）

## Solution

### 架构总览

```
                         ┌─────────────────────────────────────┐
   POST /jobs ──────────▶│            Router                   │
                         │  job.target_project → ProjectRuntime│
                         └──────────────┬──────────────────────┘
                                        ▼
                         ┌─────────────────────────────────────┐
                         │          JobQueue                   │
                         │  PriorityQueue((priority, seq), job)│
                         │  + threading.Lock for JobStore      │
                         └──────────────┬──────────────────────┘
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
              ┌─────────────────────┐
              │   ProjectRuntime    │  ← Router 解析得到
              │  ┌───────────────┐  │
              │  │ SkillRunner   │  │  项目专属技能集
              │  ├───────────────┤  │
              │  │ MemoryService │  │  项目专属 .state/
              │  ├───────────────┤  │
              │  │  AgentLoop    │  │  顺序执行 plan
              │  ├───────────────┤  │
              │  │   Tracer      │  │  trace_id 贯穿
              │  └───────────────┘  │
              └─────────┬───────────┘
                        │
                        ▼
              ┌─────────────────────┐
              │      JobStore       │  ← Lock 保护读改写
              │  .state/jobs.json   │
              │  job + executions[] │
              └─────────┬───────────┘
                        │
                        ▼
              ┌─────────────────────┐
              │  SSE /stream/jobs   │  → 客户端实时状态
              └─────────────────────┘
```

### 核心数据结构

```python
@dataclass
class RetryPolicy:
    max_retries: int = 0          # 0 = 不重试
    base_delay: float = 2.0       # 指数退避基数
    max_delay: float = 60.0       # 退避上限

@dataclass
class ScheduledJob:
    job_id: str                   # uuid4
    task: Task                    # 复用现有 Task dataclass
    target_project: str = "default"
    priority: int = 5             # 1(最高) - 10(最低)，默认 5
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    status: JobStatus = JobStatus.PENDING
    attempts: list[JobExecution] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    created_at: str = ...
    submitted_by: str = "cli"     # "cli" | "api" | "loop"

@dataclass
class JobExecution:
    attempt_num: int
    started_at: str
    ended_at: str | None
    status: JobStatus             # RUNNING / SUCCEEDED / FAILED / TIMEOUT
    error: str | None
    trace_id: str | None
    round_summary: dict | None    # 来自 TaskScheduler.run 的 round

class JobStatus(str, Enum):
    PENDING = "PENDING"           # 已创建未入队
    QUEUED = "QUEUED"             # 已入队等待 worker
    RUNNING = "RUNNING"           # worker 正在执行
    SUCCEEDED = "SUCCEEDED"       # 成功
    FAILED = "FAILED"             # 失败（含重试耗尽）
    CANCELLED = "CANCELLED"       # 被取消
    TIMEOUT = "TIMEOUT"           # 超时
    ABANDONED = "ABANDONED"       # 进程重启后未恢复
```

### ProjectRuntime 与路由

```python
@dataclass
class ProjectConnection:
    id: str                       # "default" | "proj-xxx"
    name: str
    project_type: str             # "local" | "github" | "api"
    state_dir: str                # 项目专属状态目录
    skills_dir: str | None        # None = 继承全局
    config: dict                  # url/token/branch 等
    health: str = "unknown"       # "connected" | "disconnected" | "unknown"

class ProjectRuntime:
    """懒加载：首次路由到该项目时才实例化 runner/memory/loop。"""
    def __init__(self, conn: ProjectConnection): ...
    def runner(self) -> SkillRunner: ...
    def memory(self) -> MemoryService: ...
    def loop(self) -> AgentLoop: ...
    def scheduler(self) -> TaskScheduler: ...  # 用上述组件构造

class Router:
    def __init__(self, registry: ProjectRegistry): ...
    def resolve(self, project_id: str) -> ProjectRuntime:
        """未找到抛 NotFoundError；'default' 永远存在。"""
```

### WorkerPool 执行流

```python
class WorkerPool:
    def __init__(self, size: int, router: Router, queue: JobQueue, store: JobStore, bus: StatusBus):
        self._workers = [threading.Thread(target=self._loop, daemon=True) for _ in range(size)]

    def _loop(self):
        while not self._stop.is_set():
            job = self._queue.get(timeout=1.0)  # 阻塞等待
            if job is None: break
            runtime = self._router.resolve(job.target_project)
            self._execute(job, runtime)

    def _execute(self, job: ScheduledJob, runtime: ProjectRuntime):
        for attempt in range(job.retry_policy.max_retries + 1):
            exec_record = JobExecution(attempt_num=attempt, started_at=now(), status=RUNNING, ...)
            job.status = RUNNING; self._bus.emit(job)
            try:
                scheduler = runtime.scheduler()
                scheduler.run(job.task.task_id)  # 复用现有执行逻辑
                # 检查 cancel_event
                if job.cancel_event.is_set():
                    exec_record.status = CANCELLED; break
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
            # 重试退避
            if attempt < job.retry_policy.max_retries:
                delay = min(job.retry_policy.base_delay * 2**attempt, job.retry_policy.max_delay)
                time.sleep(delay)
        if job.status == RUNNING:  # 全部重试失败
            job.status = FAILED
```

### 向后兼容

- `POST /tasks`（旧接口）保持不变：内部转换为 `target_project="default"` 的 `ScheduledJob` 入队，但**默认同步等待**（`wait: true`）以保持旧语义
- `POST /jobs`（新接口）默认**异步**：返回 `job_id` + `202 Accepted`，客户端轮询或订阅 SSE
- `hermes workbench task run`（旧 CLI）保持同步语义；新增 `hermes workbench job submit` 走异步

### StatusBus（状态事件总线）

```python
class StatusBus:
    """进程内 pub/sub，worker 发布 job 状态变更，SSE handler 订阅。"""
    def __init__(self):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
    def emit(self, job: ScheduledJob):
        with self._lock:
            for sub in self._subscribers:
                sub.put_nowait({"job_id": job.job_id, "status": job.status, "ts": now()})
    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=100)
        with self._lock: self._subscribers.append(q)
        return q
    def unsubscribe(self, q: queue.Queue):
        with self._lock: self._subscribers.remove(q)
```

## Edge cases & risks

| Category | Notes |
|---|---|
| **并发写 JobStore** | 多 worker 同时完成 job 会并发写 `jobs.json`；用 `threading.Lock` 串行化读改写，单次 `atomic_write_json` 落盘 |
| **worker 异常崩溃** | daemon 线程崩溃不会重启；`WorkerPool` 启动时记录活跃数，`/health` 暴露；建议 worker 内 try/except 兜底，将 job 标 FAILED 而非让线程死亡 |
| **队列积压** | 高优先级 job 饥饿低优先级；用 `(priority, seq)` 保证同优先级 FIFO，不实现 aging（超出范围） |
| **取消时序** | `cancel()` 设置 `cancel_event`，但 worker 只在**步骤间**检查；正在执行的 `AgentLoop.execute` 不可中断；实际取消延迟 = 当前 step 剩余时间 |
| **ProjectRuntime 懒加载失败** | github 项目 token 失效 → runner 构造失败 → job 标 FAILED，error 含诊断；不影响其他项目 |
| **进程重启** | 未完成 job（PENDING/QUEUED/RUNNING）在重启后标 `ABANDONED`，`/jobs` 仍可查询历史；不自动恢复 |
| **SSE 订阅者断连** | `subscribe` 的 Queue 满 `put_nowait` 丢弃旧事件；SSE handler 捕获 `BrokenPipeError` 后 `unsubscribe` |
| **default 项目状态目录冲突** | default 项目 `state_dir` = 全局 `hermes_state_dir`，与现有 `tasks.json` / `facts.json` 共存；`jobs.json` 独立文件不冲突 |
| **TaskScheduler.run 内部 loop 模式长耗时** | loop 模式可能跑数分钟；worker 被占用期间不消费新 job；需文档提示 `max_rounds` 与 `workers` 配比 |

## Acceptance criteria

- **AC-1**：`POST /jobs` 提交一个 `target_project="default"` 的 job，立即返回 `202` + `job_id`；job 在 worker 池中异步执行，最终 `GET /jobs/{id}` 返回 `status: SUCCEEDED`
- **AC-2**：提交 3 个 `priority=1` 的 job + 2 个 `priority=5` 的 job 到单 worker 池，3 个高优先级 job 的 `started_at` 全部早于 2 个低优先级 job 的 `started_at`
- **AC-3**：`POST /jobs/{id}/cancel` 对一个 `QUEUED` 状态的 job，立即返回 `200`，job 状态变为 `CANCELLED` 且从未进入 `RUNNING`
- **AC-4**：`POST /jobs/{id}/cancel` 对一个 `RUNNING` 状态的 job，worker 在当前 `LoopStep` 完成后检查到 `cancel_event`，将 job 标记为 `CANCELLED`，不再继续后续 step
- **AC-5**：提交 `retry_policy={max_retries: 2, base_delay: 0.1}` 的 job，当首次执行抛异常时，job 经过 3 次 attempt（1 + 2 重试）后 `status=FAILED`，`attempts` 列表长度为 3
- **AC-6**：注册一个 `project_type="local"` 的项目 `proj-a`（`state_dir=/tmp/proj-a`），提交 `target_project="proj-a"` 的 job，job 执行时读写的是 `/tmp/proj-a/` 下的 facts/episodes，而非全局 `.state/`
- **AC-7**：注册一个不存在的项目 `proj-x`，提交 `target_project="proj-x"` 的 job，返回 `404 NotFoundError`，job 不入队
- **AC-8**：`GET /stream/jobs` SSE 连接后，提交一个新 job，客户端在 2 秒内收到至少 3 条状态事件（`QUEUED` → `RUNNING` → `SUCCEEDED`）
- **AC-9**：`GET /health` 返回 `scheduler: {workers: {active: N, idle: M}, queue_depth: K}`，其中 `active + idle = workers_total`
- **AC-10**：旧接口 `POST /tasks`（带 `run: true`）仍同步返回完整 task 结果，行为与 v0.2.0 一致（向后兼容）
- **AC-11**：`hermes workbench job submit --plan '[{"skill":"echo"}]' --project proj-a --priority 1` 返回 `job_id`；`hermes workbench job list` 列出该 job；`hermes workbench job show {id}` 显示状态与执行历史
- **AC-12**：进程重启后，`GET /jobs` 仍返回历史 job，但重启前处于 `PENDING/QUEUED/RUNNING` 的 job 状态变为 `ABANDONED`
- **AC-13**：`pytest tests/workbench/test_scheduler.py` 覆盖上述全部 AC，且 `ruff check` 通过

## Open questions

无。范围已通过用户确认（进程内调度 + 跨项目路由，stdlib-only）。

## Core entities (ontology)

| Entity | Type | Key fields | Relationship |
|---|---|---|---|
| `ScheduledJob` | dataclass | job_id, task, target_project, priority, retry_policy, status, attempts | 包含 1 个 `Task`；属于 1 个 `ProjectConnection`；产生 N 个 `JobExecution` |
| `JobExecution` | dataclass | attempt_num, started_at, ended_at, status, error, trace_id | 属于 1 个 `ScheduledJob` |
| `JobStatus` | Enum | PENDING/QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED/TIMEOUT/ABANDONED | `ScheduledJob.status` 与 `JobExecution.status` 共用 |
| `RetryPolicy` | dataclass | max_retries, base_delay, max_delay | 被 `ScheduledJob` 包含 |
| `ProjectConnection` | dataclass | id, name, project_type, state_dir, skills_dir, config, health | 被 `ProjectRegistry` 管理；1:1 对应 `ProjectRuntime` |
| `ProjectRuntime` | class | conn, runner, memory, loop, scheduler | 由 `Router` 解析得到；懒加载 |
| `ProjectRegistry` | class | store, _runtimes | 管理 `ProjectConnection` 列表 |
| `Router` | class | registry | `resolve(project_id) → ProjectRuntime` |
| `JobQueue` | class | _pq (PriorityQueue), _seq | 线程安全入队/出队 |
| `WorkerPool` | class | _workers[], _stop (Event) | 消费 `JobQueue`，调用 `ProjectRuntime` 执行 |
| `JobStore` | class | path, _lock | 持久化 `ScheduledJob` + `JobExecution` |
| `StatusBus` | class | _subscribers[], _lock | 发布 job 状态变更给 SSE 订阅者 |

## Interview metadata

- Mode: default
- Waves: 1
- Final ambiguity: ~28%
- Status: PASSED

### Clarity breakdown

| Dimension | Score | Weight | Weighted |
|---|---|---|---|
| Goal | 0.85 | 0.40 | 0.34 |
| Scope | 0.80 | 0.25 | 0.20 |
| AC | 0.75 | 0.25 | 0.1875 |
| Context | 0.85 | 0.10 | 0.085 |
| **Ambiguity** | | | **~28.75%** |

### Ontology

- stable: `Task`, `AgentLoop`, `TaskScheduler`, `Orchestrator`, `MemoryService`, `SkillRunner`, `Tracer`（复用现有）
- new: `ScheduledJob`, `JobExecution`, `JobStatus`, `RetryPolicy`, `ProjectConnection`, `ProjectRuntime`, `ProjectRegistry`, `Router`, `JobQueue`, `WorkerPool`, `JobStore`, `StatusBus`

## Plan

详见后续 `dev-plan` 产出的 `.claude/artifacts/plans/phase3-scheduling-center.md`。

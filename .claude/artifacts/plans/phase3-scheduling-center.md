# Phase 3 调度中心 Implementation Plan

> Status: APPROVED
> Source: `.claude/artifacts/designs/phase3-scheduling-center.md`
> Mode: default (deliberate-level test plan due to concurrency risk)
> Iterations: 2 / 3
> Author: Hermes Agent
> Last updated: 2026-07-25

## Requirements summary

在 Workbench 运行时（v0.2.0）之上构建进程内调度中心，覆盖：后台异步执行 + 跨项目路由 + 优先级队列 + 限流 + 超时 + 重试 + Cron 定时触发 + 崩溃恢复 + 任务 DAG 依赖 + 跨项目资产同步 + 状态流式 API + 指标看板。stdlib-only，每子模块独立 commit+push，每阶段测试验收质量分>95。

## Acceptance criteria

继承 spec 的 AC-1 至 AC-26（详见 [spec](file:///workspace/.claude/artifacts/designs/phase3-scheduling-center.md#acceptance-criteria)）。

## RALPLAN-DR

### Principles

1. **每子模块独立可测、可 commit**：不跨模块耦合实现，先做不依赖后续模块的核心调度
2. **stdlib-only**：`threading` / `queue` / `concurrent.futures` / `sched`，零外部依赖
3. **复用现有执行原语**：job 执行委托 `TaskScheduler.run` / `AgentLoop.execute`，不重写执行逻辑
4. **TDD 严格红绿**：每个 dataclass/class 先写测试再写实现，覆盖率 > 90%
5. **分阶段 push 防丢失**：每子模块完成 → 测试通过 → commit → `scripts/git-push.sh`，绝不积累

### Decision drivers

1. **并发安全**（最高）：多 worker 线程并发读写 JobStore/ProjectRegistry，锁粒度与死锁风险是核心
2. **向后兼容**：旧 `POST /tasks` 与 `hermes workbench task run` 必须保持同步语义
3. **可测性**：线程代码难测，需可注入 mock runner/scheduler/clock
4. **实施顺序**：依赖关系决定顺序（核心调度 → 路由 → 触发 → 恢复 → DAG → 同步 → API → CLI）

### Viable options

**Option A: 单文件大模块 `scheduler.py`**
- 实现思路：所有调度相关类放一个 `src/hermes/workbench/scheduler.py`（~800 行）
- 改动文件：`scheduler.py`（新建）、`server.py`（加路由）、`cli.py`（加子命令）、`__init__.py`
- Pros：导入简单、类间访问无跨文件开销
- Cons：单文件过大难维护、测试 fixture 难复用、merge 冲突高发

**Option B: 按职责拆分多模块（favored）**
- 实现思路：拆为 `scheduler.py`（核心调度）+ `projects.py`（项目路由）+ `triggers.py`（Cron）+ `recovery.py`（崩溃恢复）+ `dag.py`（依赖图）+ `asset_sync.py`（资产同步）
- 改动文件：6 个新模块 + `server.py` 加路由 + `cli.py` 加子命令 + `dashboard.py` 扩展 + 测试 6 个新文件
- Pros：每模块独立可测、职责清晰、merge 友好、对应 spec 的 8 个子节
- Cons：跨模块 import 略多、需注意循环依赖（用 lazy import 打破）

**Invalidation rationale for Option A**：spec 明确 8 个子模块、19 个实体，单文件会超 1000 行，违反可维护性；且用户要求"每阶段审查验收"，单文件无法分阶段交付。

### Implementation steps

按依赖顺序分 8 个阶段，每阶段独立 commit+push。文件路径基于 `/workspace/src/hermes/workbench/`。

#### 阶段 1：3.1 核心调度（scheduler.py）

1. 新建 `tests/workbench/test_scheduler.py`，先写 dataclass 与状态机测试（红）— 覆盖 `ScheduledJob`/`JobExecution`/`JobStatus`/`RetryPolicy` 序列化与状态转换
2. 新建 `src/hermes/workbench/scheduler.py`，实现 `JobStatus` Enum + `RetryPolicy`/`JobExecution`/`ScheduledJob` dataclass（绿）
3. 加 `JobStore` 测试：CRUD + 并发写（10 线程 × 50 次）+ Lock 串行化验证
4. 实现 `JobStore`：`threading.Lock` + `atomic_write_json` 落盘到 `.state/jobs.json`
5. 加 `JobQueue` 测试：优先级排序（priority=1 早于 priority=5）+ 同优先级 FIFO（seq 递增）
6. 实现 `JobQueue`：`queue.PriorityQueue` + `_seq` 计数器
7. 加 `WorkerPool` 测试：单 worker 执行 job + 多 worker 并发 + cancel_event 协作式取消 + retry 指数退避 + timeout watcher
8. 实现 `WorkerPool`：daemon 线程 + `_execute` 循环 + `threading.Timer` 超时 + DAG 回调钩子（暂留空）
9. `pytest tests/workbench/test_scheduler.py -v` 全绿，`ruff check src/hermes/workbench/scheduler.py tests/workbench/test_scheduler.py`
10. `git add` 具体文件 + `git commit` + `bash scripts/git-push.sh`

#### 阶段 2：3.2 跨项目路由（projects.py）

1. 新建 `tests/workbench/test_projects.py`，先写 `ProjectConnection` dataclass + `ProjectRegistry` CRUD + `ping` 健康检查测试
2. 新建 `src/hermes/workbench/projects.py`，实现 `ProjectConnection` + `ProjectRegistry`（持久化到 `.state/projects.json`）
3. 加 `ProjectRuntime` 测试：懒加载 + 各组件实例化 + state_dir 隔离验证
4. 实现 `ProjectRuntime`：懒加载 `SkillRunner`/`MemoryService`/`AgentLoop`/`Tracer`/`TaskScheduler`
5. 加 `Router` 测试：resolve 成功/失败 + `try_acquire`/`release` 限流（max_concurrent=2，3 个 job 第 3 个 acquire 失败）
6. 实现 `Router`：`_inflight: dict[str, int]` + `threading.Lock`
7. 集成到 `WorkerPool._execute`：出队后 `try_acquire`，失败则 requeue + sleep 1s
8. `pytest tests/workbench/test_projects.py -v` 全绿，ruff 通过
9. commit + push

#### 阶段 3：3.3 Cron 定时触发（triggers.py）

1. 新建 `tests/workbench/test_triggers.py`，先写 `Trigger` dataclass + `TriggerStore` CRUD 测试
2. 新建 `src/hermes/workbench/triggers.py`，实现 `Trigger` + `TriggerStore`（`.state/triggers.json`）
3. 加 `CronScheduler._matches_cron` 测试：5 字段解析 + `*` / 数字 / `,` / `-` / `/` 边界
4. 实现 `_matches_cron(expr, dt)`：纯函数，无副作用
5. 加 `CronScheduler` 集成测试：daemon 线程启动 + 60s 扫描 + last_fired_at 去重 + enable/disable
6. 实现 `CronScheduler`：`threading.Event` + `wait(60)` + 模板实例化 job 入队
7. `pytest tests/workbench/test_triggers.py -v` 全绿
8. commit + push

#### 阶段 4：3.4 崩溃恢复（recovery.py）

1. 新建 `tests/workbench/test_recovery.py`，先写 `RecoveryManager.recover` 测试：PENDING 保留 / QUEUED 重入队 / RUNNING 标 ABANDONED + L2 episode 记录
2. 新建 `src/hermes/workbench/recovery.py`，实现 `RecoveryManager`
3. 加 `HERMES_SCHEDULER_RECOVERY` 开关测试：关闭时全部标 ABANDONED
4. `pytest tests/workbench/test_recovery.py -v` 全绿
5. commit + push

#### 阶段 5：3.5 任务 DAG（dag.py）

1. 新建 `tests/workbench/test_dag.py`，先写 `DependencyGraph.register` 环检测测试（DFS）+ `ready_to_queue` + `on_job_done` 级联取消 + 深度上限 10
2. 新建 `src/hermes/workbench/dag.py`，实现 `DependencyGraph`
3. 集成到 `WorkerPool._execute` 的 finally 块：调用 `on_job_done`
4. `pytest tests/workbench/test_dag.py -v` 全绿
5. commit + push

#### 阶段 6：3.6 跨项目资产同步（asset_sync.py）

1. 新建 `tests/workbench/test_asset_sync.py`，先写 `SyncResult` + `AssetSync.sync` 测试：skills 复制 / memory 合并 facts+追加 episodes 去重 / profile 浅合并
2. 新建 `src/hermes/workbench/asset_sync.py`，实现 `AssetSync` + `SyncResult`
3. 加错误处理测试：source/target 不存在抛 NotFoundError
4. `pytest tests/workbench/test_asset_sync.py -v` 全绿
5. commit + push

#### 阶段 7：3.7 状态流式 API 与指标（扩展 scheduler.py + server.py）

1. 在 `scheduler.py` 加 `StatusBus` 类 + 测试：emit/subscribe/unsubscribe + Queue 满 put_nowait 丢弃
2. 在 `server.py` 加 `GET /stream/jobs` SSE handler + 测试（复用 `/stream/episodes` 模式）
3. 在 `scheduler.py` 加 `JobMetrics` 计算函数 + `GET /jobs/metrics` 路由 + 测试（success_rate/p95/queue_depth）
4. 扩展 `/health` 返回 scheduler 状态 + 测试
5. `pytest tests/workbench/test_server.py -v` 全绿（新增路由测试）
6. commit + push

#### 阶段 8：3.8 CLI 与 HTTP 路由集成 + 版本升级

1. 在 `cli.py` 加 `_make_scheduler_center()` 工厂 + job/project/trigger/sync 子命令
2. 在 `server.py` 加全部新路由：`POST /jobs` / `GET /jobs` / `GET /jobs/{id}` / `POST /jobs/{id}/cancel` / `POST /jobs/{id}/retry` / `POST /projects` / `GET /projects` / `POST /triggers` / `POST /triggers/{id}/fire` / `POST /sync` 等
3. 向后兼容：`POST /tasks` 内部转 ScheduledJob + `wait:true` 同步
4. 全量回归 `pytest tests/ -v` + `ruff check .`
5. 版本号 v0.2.0 → v0.3.0（pyproject.toml / manifest.json / `__init__.py`）
6. 更新 `CODE_WIKI.md`（模块数 15→21，路由数 38→50+，测试数 +N）
7. commit + push

### Workspace setup

- 当前分支 `main`（已确认 working tree 干净）
- **不创建 worktree**：用户明确要求"完成后 push git main"，直接在 main 上开发并分阶段 push
- 每阶段 commit 前运行 `git status` 确认暂存内容，用 `git add <具体文件>` 不用 `git add .`
- 每阶段 push 用 `bash scripts/git-push.sh`（push + ls-remote 原子校验）

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| **JobStore 并发写丢数据** | `threading.Lock` 串行化读改写 + `atomic_write_json` 落盘；测试 10 线程 × 50 次并发无丢失 |
| **WorkerPool 死锁（max_concurrent）** | worker 出队后 `try_acquire` 失败则 requeue + sleep 1s，不阻塞；测试 5 job / max_concurrent=2 场景 |
| **cancel_event 与 timeout 冲突** | 同一 event，worker 用 `job.timeout is not None` 区分标 TIMEOUT 还是 CANCELLED；测试 AC-4 + AC-6 |
| **CronScheduler 重复触发** | `last_fired_at` 记录，同分钟不重复；测试 `* * * * *` 场景 |
| **DAG 递归栈溢出** | 深度上限 10，超出抛 ValidationError；测试 11 层链 |
| **RecoveryManager 误恢复 RUNNING** | RUNNING 一律标 ABANDONED（ADR-0002）；测试 AC-13 |
| **SSE 订阅者断连泄漏** | handler 捕获 BrokenPipeError 后 unsubscribe；try/finally 保证 |
| **lazy import 循环依赖** | scheduler.py ↔ cli.py 用函数内 import 打破（复用现有模式） |
| **旧 POST /tasks 语义破坏** | 内部转 ScheduledJob + wait:true 同步等待；测试 AC-23 |
| **测试 flaky（时序依赖）** | 用 mock clock + 显式 sleep(0.1) + assert timeout 而非 sleep；WorkerPool 测试用单 worker + 小 delay |

## Verification steps

### 每阶段通用验证

```bash
# 1. 单元测试
pytest tests/workbench/test_<module>.py -v --tb=short

# 2. Lint
ruff check src/hermes/workbench/<module>.py tests/workbench/test_<module>.py

# 3. 覆盖率（目标 > 90%）
pytest tests/workbench/test_<module>.py --cov=src/hermes/workbench/<module> --cov-report=term-missing

# 4. commit + push
git add src/hermes/workbench/<module>.py tests/workbench/test_<module>.py
git -c user.name="Hermes Agent" -c user.email="hermes@agent.dev" commit -m "feat(workbench): Phase 3.<n> <module> + tests"
bash scripts/git-push.sh
```

### AC 验证映射

- AC-1~5（核心调度）：阶段 1 `test_scheduler.py`
- AC-6（超时）：阶段 1 `test_scheduler.py::test_timeout`
- AC-7~9（路由限流）：阶段 2 `test_projects.py`
- AC-10~12（Cron）：阶段 3 `test_triggers.py`
- AC-13（恢复）：阶段 4 `test_recovery.py`
- AC-14~16（DAG）：阶段 5 `test_dag.py`
- AC-17~19（同步）：阶段 6 `test_asset_sync.py`
- AC-20~22（SSE/指标/health）：阶段 7 `test_server.py`
- AC-23~25（兼容/CLI）：阶段 8 `test_server.py` + `test_cli.py`
- AC-26（测试覆盖）：全量 `pytest tests/ -v` + `ruff check .`

### 质量分验收（每阶段 > 95）

每阶段完成后用以下维度自评（0-100）：

| 维度 | 权重 | 标准 |
|---|---|---|
| 测试通过率 | 30 | 100% 通过 |
| 覆盖率 | 20 | > 90% |
| Lint | 10 | ruff 零报错 |
| AC 覆盖 | 20 | 本阶段 AC 全部有对应测试 |
| 并发安全 | 10 | Lock 正确、无死锁、测试覆盖并发场景 |
| 向后兼容 | 10 | 旧接口行为不变（如有涉及） |

## Pre-mortem (deliberate)

1. **Scenario**：WorkerPool 死锁，所有 worker 卡在 max_concurrent 等待
   **Trigger**：3 个同项目 job 入队，max_concurrent=2，前 2 个 job 内部 TaskScheduler.run 卡死（如 LLM 无响应）
   **Mitigation**：job.timeout 强制 cancel；worker try_acquire 失败 requeue 不阻塞；`/health` 暴露 active worker 数供监控

2. **Scenario**：JobStore 损坏导致全量历史丢失
   **Trigger**：崩溃时 `atomic_write_json` 写到一半，`safe_read_json` 回退空列表
   **Mitigation**：`persistence.py` 已有容错（损坏文件重命名 `*.corrupt`）；RecoveryManager 检测到空 jobs.json 时记 warning episode

3. **Scenario**：CronScheduler 在进程退出时未清理 daemon 线程导致 hang
   **Trigger**：`CronScheduler._stop.wait(60)` 阻塞，主线程退出时 daemon 未退出
   **Mitigation**：daemon=True 保证主进程退出时自动终止；提供 `shutdown()` 方法设置 `_stop` event

## Expanded test plan (deliberate)

- **Unit**：每模块独立 test 文件，dataclass 序列化、纯函数（cron 匹配、DAG 环检测）、状态机转换
- **Integration**：WorkerPool + Router + ProjectRuntime 端到端（mock runner）；CronScheduler + JobQueue + WorkerPool 集成
- **E2E**：`POST /jobs` → 异步执行 → `GET /jobs/{id}` 轮询 → SSE 实时事件；CLI `hermes workbench job submit` 全流程
- **Observability**：`/health` 暴露 worker active/idle/queue_depth；`/jobs/metrics` 暴露 success_rate/p95；L2 episode 记录 recovery 动作

## ADR

- **Decision**：采用 Option B（按职责拆分 6 个新模块 + 测试 6 个新文件），按 8 阶段顺序实施，每阶段独立 commit+push
- **Drivers**：并发安全（决定 Lock 粒度与测试策略）、向后兼容（决定 POST /tasks 转换层）、可测性（决定模块拆分）、实施顺序（决定依赖图）
- **Alternatives considered**：
  - Option A（单文件大模块）：rejected，单文件超 1000 行难维护，无法分阶段交付
  - Option B（多模块拆分）：chosen，对应 spec 8 子节，每模块独立可测可 commit
- **Why chosen**：spec 已明确 8 个子模块边界，拆分后每阶段可独立审查验收，符合用户"每阶段质量分>95"要求；stdlib-only 无外部依赖风险
- **Consequences**：
  - 正面：模块职责清晰、测试隔离、merge 友好、可分阶段交付
  - 负面：跨模块 import 略多（用 lazy import 打破）、6 个新文件增加发现成本
  - 约束：后续若需重构 WorkerPool，需同步修改 scheduler.py + 集成点（projects.py 的 Router、dag.py 的回调）
- **Follow-ups**：Webhook 触发（spec Out of scope）、任务子图重试（ADR-0003 后续）、StepExecution 细粒度恢复（ADR-0002 后续）

## Review trail

- Planner draft v1：8 阶段拆分，Option B 拆 6 模块
- Architect challenge v1：tension —— "每阶段独立 commit" vs "模块间依赖（WorkerPool 依赖 Router/DAG）"；steelman Option A 单文件更易处理跨类访问
- Critic verdict v1：REVISE —— 实施步骤缺具体文件路径行号；并发测试策略不明确；缺 pre-mortem（concurrency 高风险应升 deliberate）
- Planner draft v2：补全文件路径（`src/hermes/workbench/<module>.py`）、补 pre-mortem 3 场景、补 expanded test plan、补质量分验收矩阵
- Architect challenge v2：tension 接受 —— 阶段间依赖通过"集成点暂留空钩子"解决（如 WorkerPool 阶段 1 留 `_dep_graph` 钩子，阶段 5 填充）
- Critic verdict v2：APPROVED with 1 reservation
- Final iterations: 2 / 3

## Critic verdict

| 维度 | 状态 | 备注 |
|---|---|---|
| Principle consistency | ✓ | 8 阶段拆分对应 Principle 5 分阶段 push |
| Alternative exploration | ✓ | Option A 有 invalidation rationale |
| Risk mitigation clarity | ✓ | 10 条 risk 各有 mitigation |
| AC testability | ✓ | 26 条 AC 映射到具体测试文件 |
| Verification concreteness | ✓ | 每阶段有 pytest + ruff + cov 命令 |
| File/line coverage | ✓ | 实施步骤 100% cite 具体文件路径 |
| Pre-mortem present | ✓ | 3 场景 |
| Expanded test plan present | ✓ | unit/integration/e2e/observability |

### Verdict: APPROVED

### Reservations

1. **阶段 1 `test_scheduler.py::test_timeout`** —— 用真实 `threading.Timer` + sleep 测试可能 flaky。建议用 mock clock 或 `timeout=0.1` + `sleep(0.3)` 的极小值，并在测试注释中说明时序假设。实施时若发现 flaky，需重构为注入 `Clock` 抽象。

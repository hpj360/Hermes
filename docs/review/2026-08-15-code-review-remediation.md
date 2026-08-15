# Hermes 深度代码审查与可执行整改清单

> 审查日期：2026-08-15 ｜ 审查对象：`hermes` 主仓（v0.6.0，`src/hermes` + `content_team` + `workbench`）
> 审查方式：静态通读 + 关键路径追踪 + 测试/静态检查实测。**未修改任何代码。**

---

## 0. 执行摘要

- **工程质量基线良好**：`ruff check src/ tests/` 全绿；`mypy src/`（strict）0 错误；pytest 实测 **913 passed / 16 skipped**（另 765 errors + 2 failed 均为本沙盒环境对 `tempfile`/`pytest basetemp` 目录的拒绝，**非项目 bug**，根因已复现，见附录 A）。
- **架构分层清晰、文档与 ADR 体系完整**，loop/scheduler/memory/LLM 各层边界明确，"零外部运行时依赖"原则执行到位。
- **但存在 6 个 P0/P1 级功能断裂与安全问题**，集中在三个区域：
  1. **content-team 定时发布/定时采集链路是断的**（cron 触发后 job 必然 FAILED，业务闭环未接通）；
  2. **凭据与模拟数据的"诚信/安全"问题**（API 明文回传 token；模拟指标无法与真实数据区分）；
  3. **并发/崩溃恢复的正确性缺口**（DAG 不持久化、memory 无锁、episodes 重写非原子、timeout 不中断）。

本清单每项给出：证据（file:line）→ 修复动作 → 验收标准（可执行命令）。按 P0 → P1 → P2 → 复查兜底排序。

---

## 1. P0 —— 立即修复（安全/数据完整性，1-2 天）

### P0-1 skill_market 安装路径穿越 + zip-slip

- **证据**
  - `src/hermes/skill_market.py:203` — `target = (dest or skills_dir()) / name`，`name` 未做任何消毒；`name = "../../evil"` 可逃逸出 skills 目录，`force=True` 时 `shutil.rmtree(target)`（L230）可删任意目录。
  - `src/hermes/skill_market.py:123-128` — `zf.extractall(extract_dir)` 未过滤 zip 条目中的 `../`，恶意 registry 条目可写盘到任意位置（zip-slip）。
- **影响**：安装一个恶意 skill 名 / 恶意 zip 即可任写或任删用户目录。marketplace 是面向外部 registry 的入口，攻击面真实。
- **修复动作**
  1. `install_skill` 入口处校验 `name`：`re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)`，拒绝 `/`、`\`、`..`。
  2. 计算 `target` 后断言 `target.resolve().is_relative_to(skills_dir().resolve())`。
  3. `_extract_zip` 改为逐条目校验：每个条目的 `resolve()` 必须 `is_relative_to(extract_dir)`，否则拒绝；同时 `extractall` 改为 `zf.open(member)` + 手动写。
- **验收**
  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests/test_skill_market.py -q
  # 新增安全用例：install_skill("..\\..\\evil") 被拒；zip 含 "../x.txt" 被拒
  ```

### P0-2 content_team API 明文回传平台凭据

- **证据**
  - `src/hermes/content_team/api/publish.py:45-47` — `PlatformAccountResponse` 含 `auth_token` / `refresh_token` 字段，`GET /accounts`、`POST /accounts` 直接明文返回；DB 中 token 亦明文落盘（`models/platform.py`）。
  - `app.py:53-59` — CORS `allow_origins=["*"]`，任意网页可请求本机 API 拿到 token。
- **影响**：token 经浏览器/日志/抓包即泄。product-plan P4 已规划（Fernet 加密 + `has_token`），但**当前代码现状就是泄漏**。
- **修复动作**（最小增量，对齐 P4 前两步）
  1. `PlatformAccountResponse` 删除 `auth_token`/`refresh_token`，改为 `has_auth_token: bool` / `has_refresh_token: bool`。
  2. `PlatformAccountCreate` 仍接受 token（写入用），但响应不再回显。
  3. CORS 白名单：`allow_origins` 从环境变量读取（默认 `http://127.0.0.1:*`）。
- **验收**：`curl http://127.0.0.1:8000/api/accounts` 响应中不再出现 token 值；`test_publish_api` 相关断言同步更新。

---

## 2. P1 —— 功能断裂与正确性（1-2 周）

### P1-1 content_team 定时发布/定时采集链路断裂（cron 触发的 job 全部 FAILED）

- **证据**
  - `src/hermes/content_team/scheduler.py:39-59` — `_NoopRouter.resolve()` 直接 `raise RuntimeError`，WorkerPool 消费任何 job 都会 `router resolve failed` → FAILED。
  - `src/hermes/content_team/triggers.py:92-113` — `register_publish_trigger` 的 `job_template = {"type": "publish", "payload": {...}}`，而 worker 执行的是 `scheduler.run(job.task.task_id)`（`workbench/scheduler.py:687-688`）；`_task_from_dict`（scheduler.py:177-189）只认识 `task_id/plan/mode/...` 的 Task 形状 —— **`type/payload` 是死数据，永不执行**。
  - 结论：`dispatch(scheduled_at=...)` 注册的定时发布，到点后 job 入队 → 必然 FAILED → **定时发布从未真正发布**；"每日数据采集"触发器同理。
- **影响**：content-team 的"定时发布 + 自动采集"两个宣传能力实际不可用，属于产品级功能断裂。
- **修复动作**（二选一，推荐 A）
  - A. 把定时发布改造成**任务模板**：`job_template.task = {"task_id": <uuid>, "plan": [{"skill": "content_team_publish", "args": {"content_id": ..., "platform": ...}}], "mode": "oneshot"}`，并实现 `content_team` 的 `ProjectRuntime.scheduler().run(task_id)` 分发（Router 解析到 `PublishDispatcher`）；采集同理（`collect_metrics` action → `MetricsCollector.collect_all`）。
  - B. 若暂不实现执行：**显式降级** —— `dispatch(scheduled_at=...)` 返回 `SCHEDULED` 时在响应中标注 `"execution_not_wired": true`，并在 `ROADMAP.md` 把"定时发布"改标 ⚠️ 未接通，杜绝虚假 ✅。
- **验收**
  ```powershell
  # 集成测试：创建 SCHEDULED 发布 → 手动 fire trigger → PublishTask 状态从 SCHEDULED 变为 SUCCESS/PARTIAL_SUCCESS
  .\.venv\Scripts\python.exe -m pytest tests/content_team/test_triggers.py -q
  ```

### P1-2 DAG 状态不持久化 + cascade cancel 无法中断 RUNNING 任务

- **证据**
  - `src/hermes/workbench/dag.py:52-53` — `_deps`/`_dependents` 仅存内存。进程重启后 `on_job_done` 找不到下游映射 → 依赖上游完成的下游 job 永远 PENDING；`ready_to_queue` 读的是内存表而非 `job.depends_on`（L86-99）。
  - `dag.py:212-226` — `_cascade_cancel` 只改 JobStore 里的状态，**不 set `cancel_event`**；若下游正在 RUNNING，worker 内存里的 `job` 对象跑完后会以 SUCCEEDED `save()` 覆盖掉 CANCELLED（`scheduler.py:700-706`），且 worker 内存对象里没有那条 synthetic cancel 记录 → 数据被覆盖。
- **修复动作**
  1. `on_job_done` / `_enqueue_ready_downstreams` 改为以 `store` 中 `job.depends_on` 为真相源（遍历 store 找 dependents），或把 DAG 边持久化到 JobStore（`deps.json`/jobs.db 新表）。
  2. `_cascade_cancel` 对非终态 job：`job.cancel_event.set()`（需通过 Router/WorkerPool 暴露句柄）+ 保留 store 中的 CANCELLED 记录；worker 在 `save()` 前检查 `cancel_event`，已置位则不覆盖状态、只追加 TIMEOUT/CANCELLED execution。
- **验收**：新增重启恢复测试——注册 A→B，跑完 A 后重启进程，B 能继续被调度；取消 RUNNING 中的 B 后其终态仍为 CANCELLED。

### P1-3 worker timeout 只置标志位、不中断执行

- **证据**：`src/hermes/workbench/scheduler.py:654-658` — `threading.Timer(job.timeout, job.cancel_event.set)`；`scheduler.run(task.task_id)` 是同步阻塞调用（L688），挂死时 timer 只能置位，**run 永不返回 → job 永远 RUNNING，worker 线程被永久占用**。`TIMEOUT` 状态只在 run 恰好返回时才有机会落（L691-699）。
- **修复动作**：`scheduler.run` 挪到独立可终止线程/子进程中执行（超时强杀，复用 `skill_runner._terminate_process_tree` 或 `multiprocessing`），主 worker 在 timer 触发后 join 超时并标记 TIMEOUT；至少先把 `job.timeout` 文档改成"软超时"，避免误用。
- **验收**：新增测试——注入一个 sleep(∞) 的任务，断言 timeout 后 job 终态为 TIMEOUT 且 worker 可继续消费下一个 job。

### P1-4 MemoryService 并发丢失更新 + episodes 重写非原子

- **证据**
  - `src/hermes/workbench/memory.py:146-160`（`remember_fact`）、`176-187`（`forget_fact`）、`201-219`（`_purge_expired_facts`）— read-modify-write JSON 文件，**无任何锁**；HTTP 线程池并发写 → 丢失更新。JobStore/TriggerStore 都有 Lock，这里漏了。
  - `memory.py:682-684`（`compact_episodes`）、`751-753`（`archive_episodes`）— `write_text` 直接覆写 `episodes.jsonl`，非原子（`persistence.atomic_write_text` 现成却没用）；且与 `atomic_append_jsonl` 的锁互不覆盖（append 锁 ≠ rewrite 锁），并发 append 会丢行或写坏。
- **修复动作**
  1. `MemoryService` 增加 `threading.Lock` 包住 facts/ttls/embeddings 的读改写（参考 `TriggerStore._lock` 模式）。
  2. `compact_episodes`/`archive_episodes` 重写改用 `atomic_write_text`（tempfile + os.replace），并把"重写"与 `atomic_append_jsonl` 的 append 共用同一把文件锁。
  3. 给 `compact/archive` 增加崩溃恢复测试（写一半 kill，重启后 episodes 可读）。
- **验收**：新增并发测试（8 线程 × 100 次 remember_fact 后计数正确）；`pytest tests/workbench/test_memory.py tests/content_team/test_memory.py -q`。

### P1-5 技能沙盒静态门可被绕过（4 个具体缺口）

- **证据**（`src/hermes/workbench/sandbox.py`）
  1. L253-256 — 文件不可读/解码失败时返回 `clean=True`。Python 源码带 PEP 263 编码声明（如 latin-1）时 `read_text("utf-8")` 抛 `UnicodeDecodeError` → **门直接放行**，而 Python 解释器能正常执行该文件。
  2. `DANGEROUS_IMPORTS`（L34-64）检查的是 `alias.name.split(".")[0]`，但表里没有 `"urllib"` 根名（只有 `"urllib.request"`）→ `import urllib; urllib.request.urlopen(...)` 放行；`"xmlrpc"` 在表内但 `import xmlrpc.client` 的根名 `xmlrpc` 被拦，然而 `"http"`、`"ftplib"` 等根名同样存在类似缺口需逐一核对。
  3. `DANGEROUS_DUNDERS`（L119-134）缺 `"__dict__"`、`"__getitem__"` — `os.__dict__["system"]("cmd")` 放行。
  4. `_check_call`（L180-200）只认 `ast.Name`/字面量绑定 — `getattr(os, "system")("cmd")`、`mode = "w"; open(f, mode)` 均放行。
- **影响**：文档已诚实声明"defense-in-depth 非安全边界"，但这些是可低成本堵上的洞；配合 P0-2 的攻击面（任意安装 skill）组合风险高。
- **修复动作**：① 解码失败改为 `clean=False`（violation="无法按 UTF-8 解析"）；② `DANGEROUS_IMPORTS` 补 `"urllib"` 根名并加"根名枚举测试"（遍历 stdlib 危险根名断言全被拦）；③ dunder 表补 `__dict__`/`__getitem__`；④ `open` 的 mode 非字面量时按"写"拒绝（保守侧）；⑤ 为 `getattr` 双常量模式增加静态识别（能识别的拦，识别不了的在 SKILL.md 信任模型文档中写明）。
- **验收**：`pytest tests/security/test_skill_sandbox.py -q` 增加上述 5 个反例用例，全部被拒。

### P1-6 LLM stream 重试会重复产出已流式内容

- **证据**：`src/hermes/workbench/llm.py:342-353` — `yield from self._stream_once(...)` 整体包在重试循环里；`_stream_once` 中途（已 yield 若干 chunk 后）抛 `URLError`（断流）→ 重试从第 0 个 token 重新流 → **调用方收到重复前缀**。docstring 声称"只在流式开始前重试"，代码与文档不符。
- **修复动作**：首次 yield 后置 `streamed=True` 标志；已产出任何 chunk 则不再重试（或抛错前把已产出的 chunk 交由调用方并明确 `partial=True`）。
- **验收**：新增测试——mock 连接在中途断开，断言 chunk 序列无重复；文档同步更新。

### P1-7 模拟指标与真实指标在数据层不可区分（诚信缺口）

- **证据**
  - `src/hermes/content_team/models/metrics.py` — `ContentMetric` **没有 source 列**。
  - `analytics/collector.py:168-173` — `source = "adapter"|"simulation"` 只写进 `log_event`，不落库；`api/analytics.py:35-52` 的 `MetricResponse` 也无 source 字段。
  - 结果：仪表盘/API 上看到的"阅读数"无法判断是真实回采还是固定种子随机数。
- **修复动作**：`ContentMetric` 增加 `source: str = "simulation"` 列（DB 迁移走 create_all 补列或随 Alembic 一并引入）；`MetricResponse` 暴露 `source`；前端在数据旁标注"模拟数据"徽标。
- **验收**：`GET /api/analytics` 响应含 `source`；`test_collector_*` 断言落库的 source 正确。

### P1-8 定时发布的"任务 + 触发器"跨存储非事务

- **证据**：`src/hermes/content_team/publish/dispatcher.py:106-123` — SCHEDULED 任务写入 DB session（循环结束后才 commit），而 `register_publish_trigger` 写独立的 `data/content_team_triggers/triggers.json`（TriggerStore）。若第 N 个账号注册 trigger 失败（如 cron 表达式非法），前面已注册的 trigger 成为**孤儿**：DB 回滚后任务不存在，trigger 却会照常 fire。
- **修复动作**：`dispatch` 中先校验所有 cron 表达式合法（`_matches_cron`），再逐账号注册 trigger；捕获异常时显式回滚已注册 trigger（delete_trigger）；最终在文档中明确"trigger 与任务非同一事务"的补偿语义。
- **验收**：测试——第二个账号的 `scheduled_at` 非法时，第一个 trigger 被清理。

---

## 3. P2 —— 工程卫生与技术债（随迭代排期）

| # | 问题 | 证据 | 修复动作 |
|---|------|------|---------|
| P2-1 | `parents[2]` 路径默认值在 pip 安装后指向 site-packages 上级（`.state`/`.cache` 会建在 Python 安装目录旁） | `src/hermes/config.py:179-192, 285`、`secrets.py:52`、`skills.py:94`、`loop.py:450`、`gepa.py:545`、`content_team/triggers.py:30`、`content_team/scheduler.py:29` | 统一为 `HERMES_DATA_DIR` 环境变量优先、`parents[n]` 兜底（product-plan P1 已规划，本次给出全部 9 处清单） |
| P2-2 | 四仓同名 `hermes` 冒名（伪依赖歧义）+ 主仓有 **17 个未提交文件**（8 modified + 9 untracked，含 ADR-0017/0018、presets.py、trajectory.py） | `pyproject.toml` 实测：content-team `name="hermes" 0.6.0`、workbench `name="hermes" 0.4.0`；`git status --porcelain` 实测 17 项 | 按 AGENTS.md 规则：先 `git add <具体文件>` 提交并 `scripts/git-push.sh`（防 push 幻觉）；随后执行六仓归一的阶段 0/1 |
| P2-3 | JobStore `update_status`(json_set) 与 worker `save`(全量 REPLACE) 存在 lost-update 竞争；worker 兜底 FAILED 路径不写 JobExecution | `workbench/scheduler.py:401-416` vs `360-373`；`617-624` | 兜底路径补 JobExecution；`save` 加"状态只允许向前"的乐观校验或统一走 `update_status` |
| P2-4 | DAG 环/深度校验后 `register` 允许重复注册同一依赖（dependents 列表重复），深度超限时 cascade 静默中断 | `workbench/dag.py:82-84, 195-227` | dependents 去重；cascade 超深时记录 episode 而非静默吞掉 |
| P2-5 | `memos_search` 查询串未 URL 编码 | `workbench/memory.py:1063` | `urllib.parse.urlencode({"q": query, "limit": limit})` |
| P2-6 | `_task_from_dict` 丢失 Task 的 status/rounds/created_at（重启后任务历史消失） | `workbench/scheduler.py:177-189` | 反序列化时回填三字段 |
| P2-7 | `recovery.py`/`scheduler.py` 文档仍写"jobs.json / Lock + atomic_write_json"，与 SQLite 实现不符 | `workbench/recovery.py:2-19, 32-35` | 文档对齐（P0-5 精神） |
| P2-8 | 定时 trigger 去重 `_last_fired` 仅内存（同分钟重启会 double-fire）；`_scan` 用本地时间而 job 时间戳用 UTC | `workbench/triggers.py:233, 315-317` | 去重键持久化到 TriggerStore；统一 UTC 或显式文档化 |
| P2-9 | `_extract_json` 声称支持 `[...]` 数组但实际只提取 `{...}` | `workbench/llm.py:569-627` | 补数组分支或改 docstring |
| P2-10 | cron 扫描循环 `except: pass` 无日志，故障静默 | `workbench/triggers.py:307-311` | 记录 `logger.exception` |
| P2-11 | `Settings` 无自定义 repr，print(settings) 会打印全部 API key | `src/hermes/config.py:26` | 给敏感字段加 `Field(repr=False)` 或自定义 `__repr__` |
| P2-12 | ADR 编号缺口 0011/0012；architecture.md 知识文档多处行号/命令与 0.6.0 实际不符（如 14 commands、7 篇 knowledge） | `docs/adr/` 实测；`knowledge/architecture.md` | 补编号说明（跳号原因一句话）+ 文档校对 |
| P2-13 | 默认 `hermes_llm_provider="ollama"` 配 `hermes_llm_model="gpt-3.5-turbo"`（默认组合在本地 ollama 下必然 model not found） | `config.py:206-207` | 默认模型改为 `llama3.2` 或 doctor 检查该组合并告警 |

---

## 4. 执行顺序建议（按依赖关系）

```
第 1 天  P0-1、P0-2（安全止血，各自独立可并行）
第 2-3 天  P1-1（定时发布链路，产品生死线）、P1-7（模拟数据标注）
第 4-7 天  P1-2、P1-3（调度正确性）、P1-4（memory 并发/原子性）
第 2 周  P1-5、P1-6、P1-8 + 每项补回归测试
第 3 周+  P2 清单随 product-plan 阶段 0/1（六仓归一、路径抽象）一并消化
```

每完成一项：`bash scripts/verify-state.sh`（全绿）→ `git add <具体文件>` → `scripts/git-push.sh` 校验远端 SHA（AGENTS.md 硬性规则）。

---

## 5. 尚未覆盖的复查兜底（本清单不视为"审查完成"）

本次深审未逐一通读以下模块，建议下一轮按同样方法复查：

- `src/hermes/gepa.py`（24KB）、`gepa_stats.py` 的 Welch's t 检验数学与多重比较/peeking 偏差、`gepa_redteam.py` 的"红队"实际覆盖面
- `src/hermes/eval/`（client/runner/gepa_bridge/result 契约一致性）
- `src/hermes/workbench/server.py`（60 个 HTTP handler 的入参校验与错误路径，本轮仅登记了路由清单）
- `src/hermes/workbench/ima_sync.py`（36KB，最大的单文件）、`github_sync.py`、`asset_sync.py`、`goal.py`、`projects.py`
- `src/hermes/skill_sync.py`、`cli_power.py` 的文件操作路径安全
- `src/hermes/orchestrator.py` 的 Gateway HTTP 轮询/超时细节（本轮只核对了 denylist 注入点）
- 4 篇 ADR（0013-0016）对应实现是否落地（token 加密、Alembic 目前均未落地——已在本清单 P0-2/阶段 2 反映）

---

## 附录 A：本沙盒环境测试注意事项（非项目 bug）

- pytest 在本 DSH 沙盒下：`tempfile` 创建的临时目录与 `--basetemp` 目录清理会被沙盒拒绝（`PermissionError: WinError 5`），导致 765 errors + 2 failed 的假象。
- **真值**：913 passed / 16 skipped；2 个 failed 测试（`test_loop.py` denylist 用例）在正常环境可过，失败点均为 `tempfile.TemporaryDirectory()`。
- 复现/规避：在非沙盒环境运行，或改用 `--basetemp=<工作区内已存在目录>` 并关闭 `tmp_path` 相关用例；`ruff`/`mypy` 不受影响。
- 验证命令（工作区内）：
  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests\ -q --basetemp=D:\Hermes\hermes\.pytest_basetemp
  .\.venv\Scripts\python.exe -m ruff check src\ tests\
  .\.venv\Scripts\python.exe -m mypy src\
  ```

## 附录 B：审查用到的关键命令与状态快照

- `git status --porcelain`（hermes）：8 M + 9 ??（未提交工作，P2-2）
- `git ls-files | grep __pycache__`：0 个入库（.gitignore 正确覆盖）
- 四仓包名实测：hermes 0.6.0 / content-team(hermes) 0.6.0 / hermes-kb(hermes) / workbench(hermes) 0.4.0
- skills 44 个与 `manifest.json` 一致；knowledge 13 篇与 manifest 一致

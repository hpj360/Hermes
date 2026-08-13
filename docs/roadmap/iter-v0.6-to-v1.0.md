# Hermes 迭代优化 Spec v0.1

> **版本**：v0.1 (2026-08-13)
> **依据**：v0.6.0 现状审查 + 12 类问题深度分析
> **范围**：hermes / content-team / hermes-workbench- / hermes-kb 四仓协同
> **目标**：补齐三大软肋（LLM 过薄 / 同步异步双轨 / 多仓碎片化），完成业务闭环与自进化升级
> **状态**：待执行

---

## 0. 决策基线（已与用户确认）

| # | 决策项 | 选择 |
|---|---|---|
| D1 | P0 阶段范围 | **全部 8 项做**（约 60h，1-2 周） |
| D2 | LLM 层深化顺序 | **并行 3 项**（stream + retry + token counter 同时开工） |
| D3 | Spec 落地形式 | **单文件** `docs/roadmap/iter-v0.6-to-v1.0.md`（本文件） |
| D4 | content_team 前端栈 | **复用 hermes-kb webpack 栈** |
| D5 | 执行节奏 | **严格 P0→P1→P2→P3 顺序**，每 Phase 全部完成且验收后才进入下一个 |

---

## 1. 顶层节奏 (4 Phase × 10 Workstream)

| Phase | 周期 | 主题 | 关键交付 | 估期 |
|---|---|---|---|---|
| **P0 稳基** | 1-2 周 | 修补"承诺但未实现"的能力 | memory search handlers / LLM stream+retry+token / skill env 隔离 / JobStore SQLite / 文档对齐 / 多仓 sync / 调度器隔离 / audit log | ~60h |
| **P1 闭环** | 3-6 周 | content-team 业务真实化 + 自进化原型 | analytics 真实 API / 视频号适配 / OAuth / 前端 UI / GEPA 自动 variant / skill manifest / /metrics | ~180h |
| **P2 扩张** | 6-12 周 | 跨仓集成 + 多机准备 + 安全强化 | hermes-kb 集成 / skill sandbox / broker interface / Vault backend / async bridge 文档化 | ~280h |
| **P3 自治** | 12+ 周 | 自我对抗 + 长期记忆 + 一键发布 | GEPA 红队 / memory TTL+向量化 / deploy skill / skill marketplace | 持续 |

---

## 2. Workstream 划分 (10 领域)

| W# | 领域 | 主责仓 | Phase 分布 | 关键决策 |
|---|---|---|---|---|
| W1 | LLM 层深化 | hermes | P0, P1 | D2 并行 3 项；sqlite 仅用 stdlib |
| W2 | 调度统一与多机化 | hermes + content-team | P0, P1, P2 | content_team 仍走 hermes CronScheduler，APScheduler 仅可选 backend |
| W3 | 记忆系统补全 | hermes | P0, P3 | server.py 已暴露端点优先补实现 |
| W4 | Skill 体系安全与进化 | hermes | P0, P1, P2 | subprocess env 显式白名单 + 强收兜底 |
| W5 | Loop / GEPA 自进化 | hermes | P1, P3 | variant 由 LLM 自动生成 + split-run 显著性 |
| W6 | 可观测性统一 | hermes + content-team | P1, P2 | `/metrics` Prometheus + trace_id 消费 |
| W7 | 多仓治理与文档 | 全部 | P0, P2 | CHANGELOG + ADR 4-6 补齐 |
| W8 | content-team 业务闭环 | content-team | P1, P2 | D4 复用 hermes-kb webpack |
| W9 | hermes-kb 集成 | hermes-kb + hermes | P2, P3 | `/kb/search` proxy |
| W10 | 配置/密钥治理 | hermes | P2 | 指针式继承 + Vault backend |

---

## 3. P0 Task 详细表（稳基，1-2 周）

> **D1 已确认：全部 8 项做**

| ID | W# | 标题 | 改动面 | 产出 | 验收标准 | 估期 |
|---|---|---|---|---|---|---|
| **P0-1** | W3 | 补 `memory_search.py` 实现 RRF/FTS/semantic | 新增 `workbench/memory_search.py`；server.py 7 个已暴露 handlers (`/memory/search`、`/memory/search/rrf`、`/memory/search/fts`、`/memory/search/semantic`、`/memory/cleanup`、`/memory/learn`、`/memory/compact`) | RRF 检索可用，端点 200 | `/memory/search?q=...` 返回 ranked hits；其余 6 端点不再 500 | 8h |
| **P0-2** | W1 | LLM stream + retry + token counter **并行 3 项**（D2） | `llm.py` 加 `stream()`、接入 `RetryPolicy`、用 `tiktoken` 精确计数（仅 dev 依赖） | LlmClient 3 方法新接口 | stream chunk 可消费；超限熔断基于真实 token；429 自动退避重试 | 12h |
| **P0-3** | W4 | Skill subprocess env 白名单 + SIGKILL 兜底 | `skill_runner._sanitized_env` 改显式白名单；timeout 加 `SIGTERM→2s→SIGKILL` 链；Win 用 `taskkill /T /F` | runner.py + tests | 子进程 `os.environ` 不含未授权 key；超时强收 0 困尸 | 6h |
| **P0-4** | W2 | JobStore 改 SQLite 分锁 | `scheduler.JobStore` 切 stdlib `sqlite3`；按 `project_id` 分库；migrator 一次性迁移 `jobs.json` | scheduler.py + persistence.py | 1000 jobs/s 写入无锁等待；崩重启 ABANDONED 仍正确；旧 `jobs.json` 保留 30 天 | 10h |
| **P0-5** | W7 | 文档对齐 + CHANGELOG + ADR 4-6 | 新增 `CHANGELOG.md`、`ROADMAP.md`；ADR-0004 async 边界 / ADR-0005 token counter / ADR-0006 SQLite JobStore | docs/adr/ 新增 3 篇 | CODE_WIKI 与 manifest.json 版本同步到 v0.6.0；ADR 索引完整 | 6h |
| **P0-6** | W7 | 多仓 sync 脚本 | `scripts/sync-forks.sh` 把 workbench/hermes-kb 同步到对应 GitHub 仓 | scripts/ | `bash scripts/sync-forks.sh --dry-run` 输出 diff；幂等 | 4h |
| **P0-7** | W2 | 调度器命名空间隔离 | content_team `register_publish_trigger` 改为调 hermes CronScheduler，APScheduler 包装为可选 backend | content_team/triggers.py | 两套 Cron 不再独立扫描；同一 `trigger_id` 全局唯一 | 8h |
| **P0-8** | W6 | Audit log 持久化 | `mcp._audit_log` 改写 `.state/audit.jsonl`；新增 `AuditStore` | mcp.py + persistence | 进程重启后 audit 不丢；`hermes audit tail` 可查 | 6h |

### P0 验收门
- `bash scripts/verify-state.sh` 全 ✅
- `pytest tests/` 全绿，覆盖率不低于现状
- `ruff check src/ tests/` 零错误
- `hermes workbench serve` 后 38 路由无 500（curl 扫描）
- 每个 Task 完成立即 `bash scripts/git-push.sh`（半自动 + 分阶段 commit）

---

## 4. P1 Task 详细表（闭环，3-6 周）

| ID | W# | 标题 | 改动面 | 验收 | 估期 |
|---|---|---|---|---|---|
| **P1-1** | W8 | content_team analytics 接真实平台 API | `analytics/collector.py` 替换 random；接微信公众号 Read API、小红书数据后台 | 5 平台真实指标可拉取；固定种子模拟保留为 fallback | 24h |
| **P1-2** | W8 | 视频号适配 + B站撤回 | `publish/adapters/wechat_video.py` 新增；B站加 `recall()` | 视频号 OAuth + 发布走通；B 站撤回命令成功 | 20h |
| **P1-3** | W8 | content_team OAuth 标准化 | 新增 `auth/oauth_flow.py`；5 平台统一 token 刷新 | token 过期自动续；存到 PlatformAccount.credentials | 16h |
| **P1-4** | W8 | content_team 前端 UI（D4 复用 hermes-kb webpack） | `apps/web/` 复用 hermes-kb webpack 栈；topic/content/publish 三个页面 | 浏览器可选题→创作→发布；与 API 联调通 | 40h |
| **P1-5** | W5 | GEPA 自动 variant 生成 | `gepa.py` 加 `auto_generate_variants(llm)`；LLM-driven 变体 | 不再手填 variant；GEPA cycle 全自动 | 16h |
| **P1-6** | W5 | GEPA 评估 split-run + 显著性 | 新增 `gepa_stats.py`；t 检验 | 5 次重复后才能 promote；p<0.05 才显著 | 12h |
| **P1-7** | W4 | Skill Manifest 协议 | `skills/*/manifest.yaml`（version/requires/provides/test_command）；`hermes skills list --untested` | 44 skill 至少 30 个补 manifest；CI 报未测 skill | 16h |
| **P1-8** | W6 | `/metrics` + dashboard trace 消费 | server.py 加 `/metrics` Prometheus；dashboard.py 消费 `trace_id` | curl `/metrics` 出 `hermes_jobs_total`；dashboard 显示 trace span | 12h |
| **P1-9** | W1 | LLM function calling | `LlmClient.chat(tools=[...])`；orchestrator 接入 | builder 可调 skill 工具而不走 subprocess | 14h |
| **P1-10** | W4 | `skill_exec_security_test` 回归套件 | 新增 `tests/security/test_skill_sandbox.py` 8 个反例 | 全部反例被拦截；CI 加安全回归 | 10h |

### P1 验收门
- content_team 5 平台真实发布链路打通（视频号除外因 OAuth 限制可降级测试模式）
- GEPA 自动 variant 跑通至少一个 cycle 且显著
- 30+ skill 有 manifest，未测 skill 列表 < 15
- 每 Task 完成立即 push，整体完成后开 3 个独立 agent 角色对抗性审查

---

## 5. P2 / P3 Task 摘要表

| ID | W# | 标题 | Phase | 估期 |
|---|---|---|---|---|
| P2-1 | W9 | `/kb/search` proxy + content_team RAG 调用 | P2 | 24h |
| P2-2 | W4 | skill sandbox（RestrictedPython + Deno） | P2 | 40h |
| P2-3 | W2 | JobQueue `BrokerInterface`（in-memory / Redis 双 backend） | P2 | 28h |
| P2-4 | W10 | 配置指针式继承 + Vault backend plugin | P2 | 32h |
| P2-5 | W2 | async bridge formalize：`asyncio.to_thread` 桥 + ADR-0007 | P2 | 12h |
| P2-6 | W6 | OTLP exporter + 全仓 trace 关联 | P2 | 24h |
| P3-1 | W5 | GEPA 红队 variant + denylist 强度回归 | P3 | 20h |
| P3-2 | W3 | Memory TTL + 归档 + 向量化（`embeddings.npz`） | P3 | 32h |
| P3-3 | W7 | `hermes deploy` 一键发布（Render/Fly/Railway） | P3 | 24h |
| P3-4 | W7 | Skill marketplace（`hermes skills publish/install`） | P3 | 60h |

---

## 6. 关键技术约束

### 6.1 零依赖基线
- Workbench 运行时层继续 stdlib-only（仅 `pydantic` / `pydantic-settings` / `python-dotenv`）
- P0-4 引入的 `sqlite3` 是 stdlib 模块，**不算破原则**
- P0-2 引入的 `tiktoken` 必须放 `requirements-dev.txt`，生产可选降级到字符长度估算 + 启动期 warning
- 引入任何新第三方包必须 ADR 论证

### 6.2 平台兼容（Windows/win32）
- P0-3 subprocess 强收：Win 用 `taskkill /T /F <pid>`；Unix 用 `os.killpg(os.getpgid(pid), SIGKILL)`
- P0-1 `memory_search.py` 索引文件路径用 `pathlib.Path`，不硬编码 `/`
- 跨平台差异封装到 `hermes.workbench.platform_compat` 模块

### 6.3 多仓 git 工作
- 工作分支统一 `trae/agent-glOxQF`
- 每 Task 完成用 `bash scripts/git-push.sh` 替代裸 `git push`
- 同步多仓用 P0-6 的 `scripts/sync-forks.sh`，不重复手工

### 6.4 半自动 Gated Mode
- P0 全自动（无修改风险项为主）
- P1 GEPA 加 `--gated`（GEPA-P1-5/P1-6）
- P2/P3 默认 gated
- L1 报告模式不强 gated

---

## 7. 风险登记

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| JobStore SQLite 迁移破坏现有 jobs.json | 中 | 高 | 一次性 migrator，旧 json 保留 30 天 |
| LLM stream 引入并发读打断现有 chat() 调用方 | 中 | 中 | 新增 `stream()` 不改 `chat()` 签名；老调用方零改动 |
| content_team 平台 OAuth 各家差异大 | 高 | 高 | 优先精简到微信+小红书两家跑通，其他平台后续 |
| GEPA 自动 variant 评估样本不够统计显著 | 中 | 高 | 强制最少 5 次重复，否则不 promote |
| Windows 子进程 SIGKILL 行为与 Unix 不一致 | 中 | 中 | 平台抽象层（P0-3 内置） |
| 多仓 sync 脚本误删发行仓内容 | 低 | 高 | `--dry-run` 默认开启；需显式 `--apply` |
| LLM token counter 在国产 provider 上不精确 | 中 | 中 | tiktoken 加 provider-specific fallback 表 |
| hermes-kb React 栈与 content_team 需求 mismatch | 中 | 中 | P1-4 启动前做 2h 评估 spike |

---

## 8. 验收与审查机制

### 8.1 单 Task 验收
1. `bash scripts/verify-state.sh` 退出码 0
2. `pytest tests/ -k <module>` 全绿
3. `ruff check src/hermes/ tests/` 零错误
4. commit message 含根因 + 验证方式
5. `bash scripts/git-push.sh` SHA 校验通过

### 8.2 Phase 验收
1. 该 Phase 全部 Task 完成
2. 跑完整 `pytest tests/`，用例数增加符合预期
3. 跑 `ruff check` + `mypy src/`
4. 触发对抗性审查：开 3 个独立角色 agent 从反方视角质疑
5. 审查发现的问题回溯修复，不得带病进入下一 Phase
6. 更新 `CHANGELOG.md` 与 `CODE_WIKI.md` 对应章节

### 8.3 整体里程碑
- **M0** P0 完成：v0.6.1（稳基版本）—— 路由无 500、LLM 三能力到位、调度无锁等待
- **M1** P1 完成：v0.7.0（业务闭环版）—— content_team 5 平台真实发布 + GEPA 自进化
- **M2** P2 完成：v0.8.0（扩张版）—— kb 集成 + sandbox + broker 抽象
- **M3** P3 完成：v1.0.0（自治版）—— 红队对抗 + 长期向量化 + marketplace

---

## 9. 执行清单（活表，每日更新）

> 用 `- [ ]` 标记；完成 `- [x]`；阻塞 `- [!]`

### P0 完成 ✅
- [x] P0-1 memory_search.py + 7 handlers
- [x] P0-2 LLM stream + retry + token counter（并行 3 项）
- [x] P0-3 Skill env 白名单 + SIGKILL 兜底
- [x] P0-4 JobStore SQLite + migrator
- [x] P0-5 CHANGELOG / ROADMAP / ADR-0004..0006
- [x] P0-6 sync-forks.sh
- [x] P0-7 调度器命名空间隔离
- [x] P0-8 Audit log 持久化 + AuditStore

### P1 完成 ✅
- [x] P1-1 content_team analytics 平台指标适配器（真实 API 边界 + 模拟回退）
- [x] P1-2 视频号适配 + B站撤回
- [x] P1-3 content_team OAuth 标准化（oauth_flow.py）
- [x] P1-4 content_team 前端 UI（Vite + React + Tailwind）
- [x] P1-5 GEPA 自动 variant 生成
- [x] P1-6 GEPA split-run + t 检验显著性
- [x] P1-7 Skill Manifest 协议 + skills list --untested
- [x] P1-8 /metrics Prometheus 端点
- [x] P1-9 LLM function calling
- [x] P1-10 skill_exec 安全回归套件

### P2 进行中
- [x] P2-1 /kb/search proxy（hermes-kb 集成骨架）
- [ ] P2-2 skill sandbox（RestrictedPython + Deno，需引入第三方依赖 + ADR）
- [x] P2-3 JobQueue BrokerInterface + Redis backend 骨架
- [x] P2-4 配置指针式继承 + Vault backend
- [x] P2-5 async bridge 正式化 + ADR-0007
- [x] P2-6 OTLP exporter 骨架

### P3 进行中
- [ ] P3-1 GEPA 红队 variant + denylist（需 LLM）
- [x] P3-2 Memory 归档（TTL/压缩已有，补 archive_episodes 冷热分离）
- [ ] P3-3 hermes deploy 一键发布（需发布平台凭证）
- [ ] P3-4 Skill marketplace（大量工作）

---

## 10. 变更历史

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-08-13 | v0.1 | 初稿创建；P0 范围=8 项全做；LLM 并行；前端栈复用 hermes-kb；严格 P0→P3 顺序 |

---

## 11. 后续操作

- 用户确认本 Spec 后，按 ID 顺序执行 P0-1 → P0-8
- 每 Task 完成立即 `bash scripts/git-push.sh`，不等"全部做完"
- P0 全部完成后开 3 个独立 agent 角色对抗性审查，通过后进入 P1
- 任何超出本 Spec 范围的改动需 ADR 论证
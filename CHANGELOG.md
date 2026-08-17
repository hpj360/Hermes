# Changelog

本文件记录 Hermes 的显著变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Fixed

- P2-3 `JobStore.save` 增加"终态保护"——不再用陈旧内存对象的不同终态覆盖数据库里
  由另一 actor 写入的终态（如 DAG cascade-cancel 的 CANCELLED 被 worker SUCCEEDED
  覆盖）；worker 兜底 FAILED 路径补记 `JobExecution`（此前只翻状态无审计）。
- P2-8 Cron 触发器的分秒去重键从内存 `_last_fired` 迁移到 `Trigger.last_fired_at`
  （持久化，重启同分钟内不再 double-fire）；`_scan` 改用 UTC 时间（与 job 时间戳
  统一，cron 表达式按 UTC 解释）。
- P2-12 新增 `docs/adr/README.md`，说明编号缺口 0011/0012 的跳号原因。

### Security

- `server.py` `/ima/files` 校验 `file_path` 必须位于项目根内，堵住任意本地文件
  外传（默认 dev 模式无鉴权下的高危面）。
- `projects.py` 新增 `to_public_dict()` + `redact_config()`，API 返回项目时脱敏
  `token/secret/password/api_key/...` 等凭据键；`h_get_projects`/`h_get_project`/
  `h_post_projects` 改用脱敏视图（持久化 `to_dict()` 保持明文以可用）。
- `server.py` `/loops/<name>/trajectory*` 校验 `name`（拒绝 `..`/路径分隔符），
  堵住路径穿越（只读）。
- `skill_sync.py` `remove_skill` 校验 managed path 必须落在已知 agent 目录内，
  堵住经 `skill_sync.json` 注入任意目录后 `shutil.rmtree` 删除；`save_sync_state`
  改用 `atomic_write_json`（防中断损坏）。
- `mcp.py` `post_pr_comment`/`create_pr` 幂等探测失败改为 fail-closed（返回错误），
  不再静默继续写造成重复评论/PR。

### Fixed

- `gepa.py` 评分 `rounds` 截断由 400 修正为 100，与 SCORE_WEIGHT_* 注释的
  worst-case 包络一致（修复"success 恒胜"不变式被 30k>20k 惩罚打破）。
- `gepa.py` `run_gepa_split_run` 对多 challenger 施加 Bonferroni 校正
  （alpha/N），抑制族错误率膨胀。
- `gepa_stats.welch_ttest` 零方差（确定性）样本不再返回 `(inf, 0.0)` 无限显著，
  改为 `(0.0, 1.0)` 不显著。
- `server.py` 新增 `_parse_int` 帮助器，非整数入参返回 400 而非 500（dashboard
  limits / ima notes limit / projects max_concurrent 已接）。

### Added

- 派发轨迹日志 + 可重建不变量（见 ADR-0017）：
  - `hermes/trajectory.py`：追加式 JSONL 轨迹（`.loops/<name>/trajectory.jsonl`），
    记录每个 sub-agent 的 `dispatch/request` / `dispatch/result` 事件（含
    `round_num` / `agent_file_sha256` 关联与校验键）；
  - 派发前校验 `assert_reconstructable`（序列化 round-trip 门禁，desync 中止派发）；
  - `OpenClawClient.spawn_agent` 保持旧签名，新增 `spawn_payload` 入口，
    `_build_spawn_payload` 成为唯一 payload 构造点；
  - `AgentTask.round_num` + `LoopRound.trajectory_seq` 持久化（跨会话追溯轮次↔轨迹）；
  - `hermes loop trajectory <name> [--json] [--verify]` CLI（离线审计：
    corrupt 行计数/seq 连续/request-result 配对完备（含非 int request_seq）/
    agent 文件哈希一致）；
  - `resume_loop` 新周期开始时归档旧轨迹（`trajectory.<n>.jsonl`）；
  - `hermes.workbench.llm` 可选 `trajectory` 参数（`request/header`/`request/context`，
    仅记录、best-effort、不校验——直连路径与派发路径语义不同）。
- Agent Preset（见 ADR-0018）：
  - `hermes/presets.py`：命名的能力面组合（tools/mcp_tools/denylist/token_limit/
    model/prompt_sections），内置 `builder-default`/`checker`/`synthesizer`/
    `perspective`/`data-analyst`；
  - 解析优先级：显式字段 > preset > 角色默认；denylist 并集（L3 红线不可清空）；
    mcp_tools 只可收紧不可放宽；
  - `AgentTask` 新增 `preset`/`tools`/`model`/`isolated`/`tool_violations`/`round_num`
    字段；
  - Gateway payload 新增 `allowed_builtin_tools` 键（`allowed_tools` 保持 MCP 语义）；
  - 内置工具越权审计 `_audit_builtin_tool_violations`（fan_in 兜底），产出计入
    `aggregate_results` 的 `Tool violations` summary 计数（仅记录不强制失败）；
  - `hermes loop presets [list|show <name>]` CLI。
- `hermes dump-config` 顶层命令（见 ADR-0019）：打印运行时最终生效组装视图，
  7 区段（paths/models/gateway/loop_patterns/agent_presets/skills/denylist_aggregate），
  支持 `--json`；denylist 聚合 = DEFAULT ∪ LOOP_PATTERNS[*] ∪ presets[*]（并集，
  L3 红线不可丢失）；与真实启动共用组装逻辑，回答 DSH 三问之①。
- Trajectory 视图后端 API + Dashboard 面板（见 ADR-0020）：
  - `GET /loops`、`GET /loops/<name>/trajectory`、`GET /loops/<name>/trajectory/verify`
    三条 HTTP 路由（复用 `TrajectoryLogger.events()` 与 `verify_trajectory()`）；
  - workbench dashboard 新增 "Loop Trajectory" 面板：loop 选择器 + events 表格
    （Seq/Type/Time/Detail）+ Verify 按钮（PASS/FAIL + seq gaps / unpaired /
    hash mismatches 明细）；
  - 排障从"SSH 跑 CLI"变为"浏览器点选"。

### Fixed

- `FTS5Index` 线程安全：改用 thread-local sqlite3 连接，修复 `ThreadingHTTPServer`
  worker 线程复用主线程连接导致的 `ProgrammingError`（`/tasks` 返回 500）。
- `compact_episodes` 返回结构与测试契约对齐（`l2_summaries`/`l3_summaries`）。
- `list_knowledge_docs` 按文件名字符串排序，跨平台确定（此前 `Path` 排序与
  `sorted(names)` 不一致导致测试失败）。
- Windows 编码：skill 脚本子进程注入 `PYTHONIOENCODING=utf-8`，修复 GBK
  编码无法输出 emoji/CJK 导致脚本崩溃的问题。
- `server.h_post_memos_feedback` 调用不存在的 `_parse_body`（真实 bug，`/memos/feedback`
  会 500），改为 `_read_json_body`。
- content_team 类型债务：`db.py` GUID 泛型、`middleware.py` 类型注解、
  `analytics.py` `_apply_filters` 注解、`triggers.py` import ignore，mypy 恢复 0 errors。
- ruff 版本漂移：锁定 `ruff==0.4.10` 并显式 `select` 规则集（F/E4/E7/E9/W），
  排除 ruff 0.5+ 新增的 S110/UP/BLE/DTZ/RUF/SIM/PLW 等未采纳规则。

### Added

- LLM 层三能力（见 ADR-0005）：
  - `LlmClient.stream()` SSE 流式输出（`LlmStreamChunk`）；
  - `LlmRetryPolicy` 指数退避重试（429/5xx/网络），`make_llm_client` 默认重试 2 次；
  - `count_tokens()`（tiktoken 优先，`len/4` 启发式降级）。
- Skill 子进程环境白名单（`_build_safe_env`）+ 进程树强杀兜底
  （`_terminate_process_tree`，Unix `SIGKILL` / Windows `taskkill /T /F`）。
- `JobStore` 迁移到 SQLite（WAL），自动从 `jobs.json` 迁移（见 ADR-0006）。
- `AuditStore` 持久化审计日志（`.state/audit.jsonl`）+ `hermes audit tail` CLI +
  `GitHubMCPClient` 集成持久化。
- memory 端点 HTTP 集成测试（`/memory/search/{rrf,fts,semantic}`、`/memory/{cleanup,learn,compact}`）。
- `scripts/sync-forks.sh` 多仓资产同步（dry-run 默认，`--apply` 执行）。
- ADR-0004（同步/异步边界）、ADR-0005（LLM 三能力）、ADR-0006（SQLite JobStore）。
- 新增 `CHANGELOG.md`、`ROADMAP.md` 与迭代 Spec `docs/roadmap/iter-v0.6-to-v1.0.md`。

### P1 闭环（纯代码部分）

- **LLM function calling（P1-9）**：`LlmClient.chat(tools=[...])` + `LlmToolCall`
  结构化解析，为 orchestrator 原生工具调用打基础。
- **GEPA split-run + t 检验（P1-6）**：`gepa_stats.py` 纯 stdlib 实现 Welch's
  t 检验（连分数不完全 beta），`compare_variants` 三重门（≥5 次重复 +
  challenger 均值更高 + p<0.05）才 promote。
- **GEPA 自动 variant 生成（P1-5）**：`auto_generate_variants()` LLM 驱动产出
  差异化策略 variant，失败优雅降级为空列表。
- **Skill Manifest 协议（P1-7）**：`manifest.yaml`（version/requires/provides/
  test_command），`discover_skills` 自动加载，`hermes skills list --untested`。
  44 个 skill 全部补齐 manifest（9 个有测试、35 个待补）。
- **`/metrics` Prometheus 端点（P1-8）**：`hermes_jobs_total` /
  `hermes_jobs_queue_depth` / `hermes_jobs_by_status{status=...}`。
- **skill_exec 安全回归套件（P1-10）**：`tests/security/test_skill_sandbox.py`
  8 个敏感变量反例 + `requires_env` 无法强取密钥。

### P1 闭环（content-team 业务部分）

- **analytics 平台指标适配器（P1-1）**：`analytics/adapters.py` 定义
  `PlatformMetricsAdapter` 协议 + `MetricsAdapterRegistry` +
  `WechatOfficialMetricsAdapter` 参考实现；`MetricsCollector` 注入 registry 后
  优先走真实 API，缺凭证/失败时回退可复现模拟（保持向后兼容）。
- **视频号适配 + B站撤回（P1-2）**：新增 `wechat_video.py`（半自动模式，视频号
  无公开投稿 API）；`BaseAdapter.recall` 默认实现显式暴露"不支持撤回"的能力边界，
  `BilibiliAdapter` 重写 recall（半自动下架）；`get_adapter` 接入 WECHAT_VIDEO。
- **OAuth 标准化（P1-3）**：`auth/oauth_flow.py` 的 `OAuthTokenManager` 统一
  token 过期检查（skew 提前刷新）+ 可注入 `refresh_fn` 的刷新流程，降级语义明确。
- **前端 UI（P1-4）**：`apps/web/`（Vite + React + Tailwind + wouter，复用
  hermes-kb 栈），选题/创作/发布三页面 + fetch 封装；`app.py` 存在构建产物时
  挂载 dist 并做 SPA 回退。

### P2 扩张 / P3 自治（可落地骨架）

- **async bridge（P2-5）**：`async_bridge.py` 的 `run_async_in_sync` /
  `run_sync_in_async` 双 helper（`asyncio.run` / `asyncio.to_thread`），嵌套
  loop 死锁显式拒绝；ADR-0007 记录边界规范。
- **JobQueue BrokerInterface + Redis（P2-3）**：`broker.py` 的 `BrokerInterface`
  结构化协议（现有 JobQueue 零改动满足）+ `RedisBroker`（ZSET+BZPOPMIN，惰性
  import redis），多机传输可插拔，默认仍走 stdlib in-memory。
- **Vault backend + 配置指针式继承（P2-4）**：`VaultSecretSource`（stdlib
  urllib 调 KV-v2，VAULT_ADDR/TOKEN/PATH，惰性 fetch + 缓存，缺凭证降级）；
  `load_inherited_env` 支持 `HERMES_INHERIT_ENV_PATHS` 指针式继承路径。
- **/kb/search proxy（P2-1）**：`Settings.hermes_kb_base_url` + `GET /kb/search`
  端点，转发 hermes-kb 检索，未配置 503 / 不可达 502，优雅降级。
- **OTLP exporter（P2-6）**：`otlp.py` 的 `OtlpExporter` 把 trace_id episode
  转成 OTLP/HTTP JSON span POST 到 collector，未配置 no-op。
- **Memory 归档（P3-2）**：`archive_episodes()` 把旧 episode 移入
  `episodes.archive.jsonl` 冷档，热档保持精简，FTS 索引同步重建。

### P2/P3 技术债清零（零依赖落地）

- **skill sandbox（P2-2）**：`workbench/sandbox.py` 用 stdlib `ast` 对 Python
  entrypoint 做尽力而为的静态门（拒绝 subprocess/socket/eval/exec/`os.system`/
  `shutil.rmtree`/写入模式 `open`/越权 dunder），默认开启、frontmatter
  `sandbox: false` 可 opt-out；接入 `skill_runner` 运行前拦截。替代原
  RestrictedPython/OS 隔离方案（见 ADR-0009）。
- **Skill marketplace（P3-4）**：`skill_market.py` + `hermes skills
  install/pack/remote`，registry 降级为 `skills/registry.json` 目录文件 +
  可选 `HERMES_SKILL_REGISTRY` 远端（stdlib `urllib`）；install 支持 git
  clone / 本地目录 / zip 归档；pack 用 stdlib `zipfile` 打包为
  `<name>-<version>.zip`。替代原"在线注册中心/分发服务"（见 ADR-0010）。
- **Vault backend（P2-4）**：`VaultSecretSource`（stdlib `urllib` 调 KV-v2）与
  配置指针式继承此前已落地；本次对齐 ROADMAP 勾选状态，消除"技术债"标记。

## [0.6.0]

- Phase 3 调度中心：Job 队列 / Worker 池 / Cron 触发 / 崩溃恢复 / DAG 依赖 /
  跨项目路由 / 资产同步 / SSE 流式 API / 指标看板。
- Loop Engineering CLI（14 子命令）与多 Agent 安全架构（P0 MCP 分舱 /
  P1 Token 熔断 / P2 协作指标 / P3 GEPA 自进化 / Stage 6 L3 denylist）。
- 44 个 skills 与 13 篇知识文档沉淀。

## [0.5.0]

- Workbench 运行时层（Skill 执行引擎、Agent 循环、三层记忆、任务调度、
  HTTP Dashboard API、GitHub 同步）。
- UI/Design 五层栈（figma-reader / ui-design-system / ui-review-checklist /
  style-dictionary-sync / component-library-selector / design-spec-skill-creator /
  prototype-validator / storybook-chromatic / liquid-glass-builder）。

# Changelog

本文件记录 Hermes 的显著变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Fixed

- `FTS5Index` 线程安全：改用 thread-local sqlite3 连接，修复 `ThreadingHTTPServer`
  worker 线程复用主线程连接导致的 `ProgrammingError`（`/tasks` 返回 500）。
- `compact_episodes` 返回结构与测试契约对齐（`l2_summaries`/`l3_summaries`）。
- `list_knowledge_docs` 按文件名字符串排序，跨平台确定（此前 `Path` 排序与
  `sorted(names)` 不一致导致测试失败）。
- Windows 编码：skill 脚本子进程注入 `PYTHONIOENCODING=utf-8`，修复 GBK
  编码无法输出 emoji/CJK 导致脚本崩溃的问题。

### Added

- LLM 层三能力（见 ADR-0005）：
  - `LlmClient.stream()` SSE 流式输出（`LlmStreamChunk`）；
  - `LlmRetryPolicy` 指数退避重试（429/5xx/网络），`make_llm_client` 默认重试 2 次；
  - `count_tokens()`（tiktoken 优先，`len/4` 启发式降级）。
- Skill 子进程环境白名单（`_build_safe_env`）+ 进程树强杀兜底
  （`_terminate_process_tree`，Unix `SIGKILL` / Windows `taskkill /T /F`）。
- `JobStore` 迁移到 SQLite（WAL），自动从 `jobs.json` 迁移（见 ADR-0006）。
- memory 端点 HTTP 集成测试（`/memory/search/{rrf,fts,semantic}`、`/memory/{cleanup,learn,compact}`）。

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

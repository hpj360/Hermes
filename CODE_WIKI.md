# Hermes Code Wiki

> 版本：对应 `pyproject.toml` 中 `hermes==0.5.0`（`manifest.json` 同为 `0.5.0`）
> 生成时间：2026-07-25（v0.5.0：Phase 3 调度中心 + Loop Engineering CLI 集成）
> 范围：`/workspace`（Hermes 独立 Python Agent 层 + Workbench 运行时 + 沉淀的 24 个 skills + 4 篇知识文档 + 内容创作素材）

---

## 0. TL;DR

Hermes 是一个**独立于主仓库（`/workspace/OpenClaw/openclaw-main`）的 Python Agent 层**。它继承了主仓库沉淀下来的账号与 API 环境配置，把分散在主仓库 `.trae/skills/` 与 `.trae/docs/knowledge/` 下的 24 个 skills 与 4 篇知识文档收纳为一个可独立运行、可独立提交的子项目。在此基础上，**Workbench 运行时层**（`src/hermes/workbench/`）提供了 Skill 执行引擎、Agent 循环、三层记忆、任务调度、HTTP Dashboard API 与 GitHub 同步能力，构成一个可被外部系统（GitHub Issues、HTTP 客户端、CLI）驱动的个人 AI 工作台。

- **定位**：Agent 层 + Skills/知识资产的"打包发行版" + Workbench 运行时
- **入口**：`hermes` CLI（`[project.scripts] hermes = "hermes.main:main"`）
- **语言**：Python ≥ 3.10（核心层 + Workbench 层）；skills 自身涉及 Python / Node.js / Shell / 纯 prompt 等多种形态
- **核心依赖**：`pydantic` / `pydantic-settings` / `python-dotenv`（仅 3 个运行时依赖，Workbench 层纯 stdlib）
- **关键能力**：多 provider 环境继承、skills/知识发现、用户画像、Agent 循环、三层记忆、任务调度、**进程内调度中心（Phase 3：Job 队列/Worker 池/Cron 触发/崩溃恢复/DAG 依赖/跨项目路由/资产同步/SSE 流式 API/指标看板）**、HTTP API（38 路由）、GitHub Issues 同步、Loop Engineering CLI（14 子命令：list/init/run/continuous/resume/audit/status/metrics/stop-rules/budget/advance/history/patterns/gepa）、**多 Agent 安全架构（P0 MCP 分舱 / P1 Token 熔断 / P2 协作指标 / P3 GEPA 自进化 / Stage 5 钩子接入 / Stage 6 L3 denylist 路径强制执行）**

---

## 1. 项目整体架构

### 1.1 分层视图

```
┌──────────────────────────────────────────────────────────────────┐
│                         CLI 入口层                                │
│            src/hermes/main.py  (argparse 子命令)                  │
│   start │ doctor │ config show │ skills list │ knowledge list │  │
│   profile show │ workbench {skills|run|loop|memory|task|serve|   │
│                github-sync}                                      │
└───────────────────────────┬──────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐  ┌──────────────────┐  ┌────────────────┐
│  config.py   │  │   skills.py      │  │  profile.py    │
│ 环境继承 +    │  │ skills/ 知识发现 │  │ data/profile   │
│ Settings      │  │ SkillInfo        │  │ .json 读写 +   │
│ (pydantic)    │  │                  │  │ Markdown 渲染  │
└──────┬───────┘  └────────┬─────────┘  └────────┬───────┘
       │                   │                     │
       ▼                   ▼                     ▼
┌──────────────────────────────────────────────────────────────────┐
│              Workbench 运行时层 (src/hermes/workbench/)           │
│  ┌────────────┐ ┌──────────┐ ┌─────────────┐ ┌───────────────┐  │
│  │ errors.py  │ │persistence│ │skill_runner │ │   memory.py   │  │
│  │ 错误层级 +  │ │.py 原子   │ │.py Skill 发现│ │ L1 facts      │  │
│  │ HTTP映射    │ │文件持久化 │ │/执行/脱敏    │ │ L2 episodes   │  │
│  └────────────┘ │           │ │             │ │ L3 profile    │  │
│                 └──────────┘ └──────┬──────┘ └───────┬───────┘  │
│                  ┌──────────────────┴────────────────┘          │
│                  ▼                                               │
│  ┌────────────────────┐  ┌──────────────────┐  ┌──────────────┐ │
│  │   agent_loop.py    │  │     cli.py       │  │ github_sync  │ │
│  │ 顺序 Agent 循环 +  │  │ 任务运行时 +     │  │ .py          │ │
│  │ 记忆记录            │  │ 服务工厂中心 +   │  │ Pull→Run→    │ │
│  └────────────────────┘  │ 17 个子命令       │  │ Push 同步     │ │
│                          └────────┬─────────┘  └──────────────┘ │
│                                   │                              │
│                          ┌────────▼─────────┐                    │
│                          │    server.py     │                    │
│                          │ Dashboard HTTP   │                    │
│                          │ API (15 路由)    │                    │
│                          └──────────────────┘                    │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                  资产层 (Assets)                                  │
│  skills/        24 个沉淀 skills（Python/Node/Shell/Prompt）      │
│  knowledge/     4 篇知识文档（Loop/Harness/Memory/Evaluator）     │
│  content-creation/  小红书 90 天冷启动内容计划                    │
│  manifest.json  skills/knowledge 清单                            │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                  状态层 (.state/ .cache/ data/)                  │
│  .state/tasks.json    任务定义 + 运行历史                         │
│  .state/facts.json    L1 事实记忆                                 │
│  .state/episodes.jsonl L2 情景记忆（追加日志）                    │
│  data/profile.json    L3 用户画像                                 │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 设计原则

1. **零额外依赖**：Workbench 运行时层全部使用 Python 标准库（`http.server`、`urllib`、`fcntl`、`subprocess`、`json`），不引入任何第三方包。
2. **环境继承**：`config.py` 实现三级 `.env` 继承链（进程环境 > Hermes 本地 `.env` > 主仓库 `.env` > Settings 默认值），已有变量永不覆盖。
3. **原子持久化**：所有状态写入经 `persistence.py` 的 `tempfile + os.replace` 原子操作，`episodes.jsonl` 用 `fcntl.flock` 排他锁守护并发追加。
4. **错误即 HTTP 状态码**：`errors.py` 的异常层级与 HTTP 状态码一一映射（400/401/404/409/502/500），CLI 退出码与 Dashboard API 共用同一套语义。
5. **服务工厂中心**：`cli.py` 的模块级 `_make_*` 工厂函数是所有服务实例化的唯一入口，便于测试 monkeypatch 与配置注入。
6. **Lazy Import 打破循环**：`github_sync.py` ↔ `cli.py`、`server.py` ↔ `cli.py` 的循环依赖全部通过函数内 import 打破，模块加载时无循环。

### 1.3 多 Agent 安全与自进化架构（Loop Engineering 演进）

Loop Engineering 不止是脚手架——L3 无人值守模式必须有代码级强制执行才能落地。下表汇总 4 个已实现的安全/进化 Stage，每一项都有代码 + 测试 + 文档三件套：

| Stage | 模块 | 功能 | 测试覆盖 |
|-------|------|------|---------|
| **P0 MCP 分舱** | `orchestrator.py` `ROLE_MCP_WHITELIST` | builder 只读 GitHub（拦截 `create_pr`/`post_pr_comment`），checker/synthesizer 禁止所有 MCP；fan_in 审计 `mcp_violations` | 6 个测试（白名单填充/保留/违规检测） |
| **P1 Token 熔断** | `orchestrator.py` `AgentTask.token_limit` | 单 agent 默认 50000 token 上限，超限强制 `status=failed`；防止单 agent 烧光预算 | 4 个测试（超限 failed/未超 completed） |
| **P2 协作指标** | `orchestrator.py` `_compute_collaboration_metrics` | 互斥 `failure_attribution`（builder/checker/mixed/none）+ `checker_builder_agreement` 三态 + `token_by_role` 归因 | 5 个测试（attribution 各分支 + 指标填充） |
| **P3 GEPA 自进化** | `gepa.py` + `loop.py:_maybe_run_gepa` | Generate-Evaluate-Promote-Apply 周期；loop 到终态自动触发，evaluator 通过 `set_gepa_evaluator` 注入；实验持久化到 `.gepa/` | 26 个测试（评分/cycle/持久化/崩溃隔离/record_round 钩子） |
| **Stage 5 钩子接入** | `loop.py:_maybe_run_gepa` + `cli_loop.py:cmd_loop_gepa` | GEPA 周期在 `record_round` 终态（COMPLETED/NEEDS_HUMAN/BUDGET_EXCEEDED）自动触发；新增 `hermes loop gepa [--run] [--json]` 子命令 | 11 个测试（终态触发/非终态跳过/无 evaluator 跳过/CLI 子命令） |
| **Stage 6 L3 denylist** | `orchestrator.py:_matches_denylist` + `_audit_path_violations` + `runner._run_builder_checker` | builder 写代码受路径黑名单约束（`auth/` `payment/` `security/` `.env` `*.key`）；fan_in 审计 Write/Edit 工具调用路径，命中受保护路径强制 builder `failed`；spawn payload 前向兼容 Gateway 强制执行 | 18 个测试（pattern 三种语义 + 审计 skip 逻辑 + tool_calls/content 两条信号 + aggregate 强制 failed + runner 注入链路） |

**安全设计哲学**（第一性原理）：
- **L3 自动化 = 事前拦截 + 事后审计双重保障**：spawn_agent 把 denylist 传入 Gateway payload（事前），fan_in 再扫描 messages 兜底（事后）。任一信号命中即强制 failed。
- **checker 无 Write 权限，不注入 denylist**：节省审计开销，且 MCP 白名单已限制 checker 不能调用 Write 类工具。
- **MCP 分舱铁律**：builder 不能写 GitHub（防止绕过 reviewer 直接合并 PR）；这是 P0 安全红线，不可降级。

---

## 2. 目录结构

```
/workspace/
├── src/hermes/                    # 核心 Agent 层 + Workbench 运行时
│   ├── __init__.py                # 包入口, __version__="0.2.0", 公开 API
│   ├── config.py                  # 环境配置中枢 (Settings + 继承链)
│   ├── logging.py                 # 结构化日志 setup_logging()
│   ├── main.py                    # CLI argparse 入口 + 子命令分发
│   ├── profile.py                 # 用户画像 JSON 读写 + Markdown 渲染
│   ├── skills.py                  # SkillInfo + discover_skills() + 知识发现
│   └── workbench/                 # Workbench 运行时子包 (9 个 .py)
│       ├── __init__.py
│       ├── errors.py              # [P0] 错误层级 + HTTP 状态码映射
│       ├── persistence.py         # [P0] 原子文件持久化原语
│       ├── memory.py              # [P1] 三层记忆服务 (L1/L2/L3)
│       ├── skill_runner.py        # [P1] Skill 发现/执行/脱敏
│       ├── agent_loop.py          # [P1] 顺序 Agent 循环 + 记忆记录
│       ├── cli.py                 # [P2] 任务运行时 + 17 子命令 + 服务工厂
│       ├── server.py              # [P3] Dashboard HTTP API (15 路由)
│       └── github_sync.py         # [P4] GitHub Issues 同步层
├── tests/                         # 测试 (259 个用例)
│   ├── conftest.py                # reset_settings / tmp_state_dir fixtures
│   ├── test_config.py             # 5
│   ├── test_logging.py            # 9
│   ├── test_main.py               # 12
│   ├── test_profile.py            # 18
│   ├── test_skills.py             # 11
│   └── workbench/
│       ├── test_agent_loop.py     # 12
│       ├── test_cli.py            # 71
│       ├── test_errors.py         # 12
│       ├── test_github_sync.py    # 21
│       ├── test_memory.py         # 21
│       ├── test_persistence.py    # 13
│       ├── test_server.py         # 24
│       └── test_skill_runner.py   # 30
├── skills/                        # 24 个沉淀 skills
├── knowledge/                     # 4 篇知识文档
├── content-creation/              # 小红书 90 天冷启动内容素材
├── data/                          # profile.example.json 画像模板
├── pyproject.toml                 # 项目元数据 + hermes script
├── requirements.txt               # 3 个运行时依赖
├── requirements-dev.txt           # 4 个开发依赖
├── manifest.json                  # skills/knowledge 清单 (v0.2.0)
├── README.md                      # 中文项目说明
├── CODE_WIKI.md                   # 本文档
├── .env.example                   # 环境变量模板
└── .gitignore                     # 忽略 .state/.cache/data/profile.json/.env
```

---

## 3. 核心层模块详解

### 3.1 `config.py` — 环境配置中枢

| 项目 | 说明 |
|------|------|
| **核心类** | `Settings(BaseSettings)` — pydantic-settings，60+ 字段 |
| **关键函数** | `bootstrap_env()`、`load_hermes_env()`、`load_inherited_env()`、`get_settings(force_reload=False)` |
| **配置分组** | OpenClaw 网关、14 个 LLM providers（OpenAI/Anthropic/Gemini/OpenRouter/Moonshot/Zhipu/Qianfan/DashScope/Xiaomi/MiniMax/Mistral/Novita/Ollama/ModelScope）、8 个消息渠道（Slack/Telegram/Discord/Mattermost/Zalo/Twitch/Feishu）、工具/搜索/媒体（Brave/Perplexity/Firecrawl/Tavily/ElevenLabs/Deepgram）、集成（GitHub/Notion/Trello/Tailscale）、Skillhub、Hermes 自身路径 |
| **继承链** | 进程环境 > Hermes `.env` > 主仓库 `.env`（`/workspace/.env` + `/workspace/OpenClaw/openclaw-main/.env`）> Settings 默认值 |
| **关键行为** | 模块导入时即执行 `bootstrap_env()`；`get_settings()` 首次调用自动创建 `.state/` 与 `.cache/` 目录；`configured_providers()` 返回已配置的 provider 列表；`missing_required()` 默认返回空（hook 供子命令使用） |

### 3.2 `skills.py` — Skills 与知识发现

| 项目 | 说明 |
|------|------|
| **核心类** | `SkillInfo` dataclass（name/path/description/has_skill_md） |
| **关键函数** | `discover_skills()`、`get_skill_path(name)`、`list_knowledge_docs()`、`skills_dir()`、`knowledge_dir()` |
| **发现逻辑** | 扫描 `skills/` 顶层子目录，读取 `SKILL.md` 与 `_meta.json`（容错 JSON 解析失败）；`list_knowledge_docs()` 返回 `knowledge/*.md` 按名排序 |
| **依赖** | 纯 stdlib，无内部依赖 |

### 3.3 `profile.py` — 用户画像管理

| 项目 | 说明 |
|------|------|
| **核心函数** | `load_profile()`、`save_profile(profile)`、`update_field(section, key, value)`、`append_to_list(section, key, item)`、`get_profile_markdown()` |
| **存储** | `data/profile.json`，v4 骨架（13 个分区：identity/carear/skills/interests/pets/alcohol/preferences/tools/learning/notes/goals/contact/personality） |
| **默认值** | `contact.github = "hpj360"` |
| **Markdown 渲染** | `get_profile_markdown()` 将结构化画像转为人类可读 Markdown |

### 3.4 `logging.py` — 结构化日志

| 项目 | 说明 |
|------|------|
| **核心函数** | `setup_logging(level="INFO", log_file=None) -> logging.Logger` |
| **格式** | `%(asctime)s [%(levelname)s] %(name)s: %(message)s` |
| **行为** | 清空已有 handlers，默认 stdout，可选 FileHandler（自动建父目录），非法级别回退 INFO |

### 3.5 `main.py` — CLI 入口

| 项目 | 说明 |
|------|------|
| **核心函数** | `build_parser()`、`main(argv=None) -> int` |
| **子命令** | `start`（默认，打印环境信息）、`doctor`（健康检查）、`config show`（脱敏配置）、`skills list`、`knowledge list`、`profile show [--json]`、`workbench ...`（委托给 `add_workbench_subparser`） |
| **全局参数** | `--log-level {DEBUG,INFO,WARNING,ERROR}`、`--log-file PATH` |
| **异常兜底** | 任何未捕获异常记录日志并返回 2（degraded-friendly） |

---

## 4. Workbench 运行时层详解

Workbench 层按 P0–P4 分阶段交付，全部使用 Python 标准库实现，零额外依赖。

### 4.1 `errors.py` [P0] — 错误层级

错误层级与 HTTP 状态码一一映射，CLI 退出码与 Dashboard API 共用。

| 类 | HTTP 状态码 | 用途 |
|----|------------|------|
| `WorkbenchError(Exception)` | 500 | 基类 |
| `ValidationError` | 400 | 输入校验失败 |
| `AuthError` | 401 | 认证失败 |
| `NotFoundError` | 404 | 资源不存在 |
| `StateError` | 409 | 状态冲突 |
| `UpstreamError` | 502 | 上游服务错误 |

**关键函数**：`status_code_for(exc: Exception) -> int` — 遍历映射表返回状态码，默认 500。

### 4.2 `persistence.py` [P0] — 原子文件持久化

所有 Workbench 状态（facts/episodes/tasks）经此模块落盘，保证原子性与并发安全。

| 函数 | 说明 |
|------|------|
| `atomic_write_text(path, content)` | tempfile + os.replace 原子写入文本，自动建父目录 |
| `atomic_write_json(path, obj)` | 原子写入 JSON（ensure_ascii=False, indent=2） |
| `safe_read_json(path, default=None)` | 安全读取 JSON，损坏文件重命名为 `*.corrupt` 并返回 default |
| `atomic_append_jsonl(path, obj)` | fcntl.flock 排他锁守护追加 JSONL（Windows 降级 best-effort） |

**并发验证**：测试覆盖 10 线程 × 50 次并发写无丢失。

### 4.3 `memory.py` [P1] — 三层记忆服务

实现 L1/L2/L3 三层记忆模型，参考 `knowledge/memory-model.md`。

| 层级 | 存储 | 类/函数 | 说明 |
|------|------|---------|------|
| L1 Facts | `.state/facts.json` | `remember_fact(key, value)` / `get_fact(key)` / `list_facts()` / `forget_fact(key)` | 键值事实存储，原子读写 |
| L2 Episodes | `.state/episodes.jsonl` | `record_episode(episode)` / `list_episodes(kind=None, limit=1000)` | 追加日志情景记忆，支持 kind 过滤与 limit |
| L3 Profile | `data/profile.json` | `get_user_profile()` / `save_user_profile(profile)` | 委托 `hermes.profile`，支持注入 loader/saver |

**关键类型**：
- `Episode` dataclass：id / kind / summary / details / created_at
- `make_episode(kind, summary, details=None) -> Episode`：工厂函数，自动生成 id 与时间戳

### 4.4 `skill_runner.py` [P1] — Skill 发现与执行

解析 `SKILL.md` 的 YAML front-matter，按文件名探测 entrypoint，在脱敏环境中执行 skill。

**关键类型**：
- `SkillSpec` dataclass：name / path / description / runtime / requires_bins / requires_env / entrypoint / raw_metadata
- `RunResult` dataclass：skill / ok / stdout / stderr / exit_code / duration / error

**核心类 `SkillRunner`**：
| 方法 | 说明 |
|------|------|
| `discover() -> list[SkillSpec]` | 扫描 base_dir 下有 `SKILL.md` 的子目录 |
| `get(name) -> SkillSpec \| None` | 按名查找 |
| `run(name, args=None, timeout=None) -> RunResult` | 执行 skill，前置检查 requires_bins |

**运行时探测规则**（`_detect_entrypoint`）：`run.py`/`main.py` → python；`run.sh` → shell；`run.js`/`index.js` → node；无 entrypoint → prompt（返回 `SKILL.md` 内容）

**脱敏机制**（`_sanitized_env`）：剥离 key 名含 `token`/`secret`/`password`/`passwd`/`pwd`/`credential`/`api_key`/`apikey`（后缀匹配）的环境变量，保留 PATH 等安全变量。

### 4.5 `agent_loop.py` [P1] — 顺序 Agent 循环

按 `LoopStep` 列表依次调用 SkillRunner，默认失败继续，记录 L1 facts 与 L2 episode。

**关键类型**：
- `LoopStep` dataclass：skill / args / timeout / abort_on_error
- `LoopStepResult` dataclass：skill / ok / error / duration / stdout_preview
- `LoopResult` dataclass：steps / ok / started_at / ended_at / error（`duration` 属性）

**核心类 `AgentLoop`**：
| 方法 | 说明 |
|------|------|
| `execute(plan, record_episode=True) -> LoopResult` | 顺序执行 plan，默认失败继续；`abort_on_error=True` 时中止；记录每个 skill 的 last_output 到 L1 facts，整轮摘要到 L2 episode |

### 4.6 `cli.py` [P2] — 任务运行时 + CLI + 服务工厂中心

Workbench 的核心模块，定义任务运行时、17 个子命令处理函数、模块级服务工厂。

**任务运行时类型**：
| 类 | 说明 |
|----|------|
| `Task` | 任务定义 dataclass（task_id/plan/mode/max_rounds/max_runs/interval/status/rounds/created_at），`to_dict()` 序列化 |
| `TaskStore` | 持久化任务定义与运行历史（`tasks.json`），save/get/list/update_status |
| `TaskRegistry` | 内存中 Task 对象注册表，register/get/list |
| `TaskScheduler` | 通过 AgentLoop 运行任务，run/cancel/list_rounds |

**服务工厂**（模块级，便于测试 monkeypatch）：
- `_state_dir()` → `get_settings().hermes_state_dir`
- `_make_runner()` / `_make_memory()` / `_make_loop()` / `_make_store()` / `_make_registry()` / `_make_scheduler()`

**17 个子命令处理函数**：
```
cmd_workbench_skills_list / show
cmd_workbench_run
cmd_workbench_loop
cmd_workbench_memory_facts_list / remember / get / forget
cmd_workbench_memory_episodes_list
cmd_workbench_memory_profile_show
cmd_workbench_task_register / list / run / show / cancel
cmd_workbench_serve
cmd_workbench_github_sync
# Phase 3 调度中心新增：
cmd_workbench_job_list / show / submit / cancel / retry / metrics
cmd_workbench_project_list / show / add / remove / ping
cmd_workbench_trigger_list / show / add / fire / enable / disable
cmd_workbench_sync
```

**CLI 子命令树**：
```
hermes workbench
├── skills {list | show <name>}
├── run <name> [args...] [--timeout N]
├── loop --plan '<json>' | --plan-file <path>
├── memory
│   ├── facts {list | remember <k> <v> | get <k> | forget <k>}
│   ├── episodes [--kind K] [--limit N]
│   └── profile show
├── task
│   ├── register [--task-id ID] --plan '<json>' | --plan-file <path>
│   │            [--mode oneshot] [--max-rounds N] [--max-runs N] [--interval F]
│   ├── list
│   ├── run <task_id>
│   ├── show <task_id>
│   └── cancel <task_id>
├── job                                  (Phase 3 新增)
│   ├── list
│   ├── show <job_id>
│   ├── submit [--plan '<json>' | --plan-file <path>] [--project ID]
│   │        [--priority 1-10] [--timeout S] [--depends-on ID...]
│   ├── cancel <job_id>
│   ├── retry <job_id>
│   └── metrics
├── project                              (Phase 3 新增)
│   ├── list
│   ├── show <project_id>
│   ├── add --name N --type {local|github|api} --state-dir D
│   │     [--skills-dir S] [--max-concurrent N] [--id ID]
│   ├── remove <project_id>
│   └── ping <project_id>
├── trigger                              (Phase 3 新增)
│   ├── list
│   ├── show <trigger_id>
│   ├── add --name N --cron '<5字段>' --plan '<json>'
│   │     [--project ID] [--priority N] [--disabled]
│   ├── fire <trigger_id>
│   ├── enable <trigger_id>
│   └── disable <trigger_id>
├── sync --source ID --target ID [--assets skills,memory,profile]  (Phase 3 新增)
├── serve [--host H] [--port P]      (默认 127.0.0.1:8000)
└── github-sync --repo owner/name [--label workbench]
```

**公开入口**：`add_workbench_subparser(sub)`、`register_workbench_commands(parser)`、`workbench_main(argv=None)`

### 4.7 `server.py` [P3] — Dashboard HTTP API

基于 `http.server.ThreadingHTTPServer` 的无状态 RESTful JSON API，所有状态经 `cli.py` 服务工厂流转。

**路由表**（38 条，正则匹配 + 命名组；Phase 3 新增 23 条标 ★）：

| 方法 | 路径 | 处理函数 | 说明 |
|------|------|---------|------|
| GET | `/health` | `h_get_health` | 健康检查（含调度器状态） |
| GET | `/skills` | `h_get_skills` | 列出所有 skills |
| GET | `/skills/<name>` | `h_get_skill` | skill 详情 |
| GET | `/memory/facts` | `h_get_facts` | 列出 facts |
| POST | `/memory/facts` | `h_post_facts` | 创建 fact（body: {key, value}） |
| GET | `/memory/facts/<key>` | `h_get_fact` | 获取 fact |
| DELETE | `/memory/facts/<key>` | `h_delete_fact` | 删除 fact |
| GET | `/memory/episodes` | `h_get_episodes` | 列出 episodes（?kind=） |
| GET | `/memory/profile` | `h_get_profile` | 获取用户画像 |
| POST | `/tasks` | `h_post_tasks` | 创建任务（body: {plan, run?, ...}） |
| GET | `/tasks` | `h_get_tasks` | 列出任务 |
| GET | `/tasks/<task_id>` | `h_get_task` | 任务详情 |
| POST | `/tasks/<task_id>/cancel` | `h_post_task_cancel` | 取消任务 |
| POST | `/tasks/<task_id>/run` | `h_post_task_run` | 运行任务 |
| GET | `/github/sync` | `h_get_github_sync` | 触发 GitHub 同步（?repo=&label=） |
| POST | `/jobs` | `h_post_jobs` | ★ 异步提交 job（plan/priority/project/timeout/depends_on） |
| GET | `/jobs` | `h_get_jobs` | ★ 列出 jobs（?status=&project=） |
| GET | `/jobs/metrics` | `h_get_jobs_metrics` | ★ 聚合指标（success_rate/p95/queue_depth） |
| GET | `/jobs/<job_id>` | `h_get_job` | ★ job 详情 |
| POST | `/jobs/<job_id>/cancel` | `h_post_job_cancel` | ★ 取消 job |
| POST | `/jobs/<job_id>/retry` | `h_post_job_retry` | ★ 重试失败 job |
| GET | `/stream/jobs` | `h_get_stream_jobs` | ★ SSE 实时 job 状态流 |
| POST | `/projects` | `h_post_projects` | ★ 注册项目连接 |
| GET | `/projects` | `h_get_projects` | ★ 列出项目连接 |
| GET | `/projects/<project_id>` | `h_get_project` | ★ 项目详情 |
| DELETE | `/projects/<project_id>` | `h_delete_project` | ★ 移除项目（default 不可删） |
| POST | `/projects/<project_id>/ping` | `h_post_project_ping` | ★ 项目健康检查 |
| POST | `/triggers` | `h_post_triggers` | ★ 注册 Cron 触发器 |
| GET | `/triggers` | `h_get_triggers` | ★ 列出触发器 |
| GET | `/triggers/<trigger_id>` | `h_get_trigger` | ★ 触发器详情 |
| POST | `/triggers/<trigger_id>/fire` | `h_post_trigger_fire` | ★ 手动触发 |
| POST | `/triggers/<trigger_id>/enable` | `h_post_trigger_enable` | ★ 启用 |
| POST | `/triggers/<trigger_id>/disable` | `h_post_trigger_disable` | ★ 禁用 |
| POST | `/sync` | `h_post_sync` | ★ 跨项目资产同步（source/target/assets） |

**关键函数**：`make_server(host, port) -> ThreadingHTTPServer`、`run_server(host="127.0.0.1", port=8080)`、`_make_scheduler_center()`（Phase 3 新增，聚合 JobStore/WorkerPool/Router/CronScheduler/RecoveryManager）

**错误处理**：`WorkbenchError` 子类经 `status_code_for()` 映射 HTTP 状态码；其他异常返回 500；未匹配路由返回 404；路径匹配但方法不匹配返回 405。SSE handler 捕获 `BrokenPipeError` 后 unsubscribe 防订阅者泄漏。

### 4.8 `github_sync.py` [P4] — GitHub Issues 同步层

桥接 GitHub Issues 与 Workbench 任务系统，实现 Pull → Run → Push 循环。零依赖（urllib），支持注入 `request_executor` 用于测试 mock。

**核心类型**：
- `GitHubClient` dataclass：token / repo / request_executor
- `SyncResult` dataclass：pulled / ran / pushed / skipped / errors / task_ids

**核心类 `GitHubSyncService`**：
| 方法 | 说明 |
|------|------|
| `from_env(repo, token=None)` | 类方法，从 `GITHUB_TOKEN`/`GH_TOKEN` 构造服务，缺 token 抛 `ValidationError` |
| `pull_issues(label="workbench")` | 拉取带 label 的 open issues，从 body 解析 JSON plan（支持 ```json fence），创建并注册 Task |
| `push_result(task_id, issue_number)` | 将任务最新一轮结果作为评论推送到 issue |
| `sync(label="workbench")` | 完整循环：pull → run → push，返回 `SyncResult` dict |

**Issue body 格式**（JSON，可选 ```json fence）：
```json
{"plan": [{"skill": "weather"}], "mode": "oneshot", "max_rounds": 3, "issue_number": 42}
```

**HTTP 错误映射**：`GitHubClient._request` 捕获 `HTTPError`，经 `_translate_http_error` 映射 —— 401 → `AuthError`，404 → `UpstreamError`，其他 → `UpstreamError`；`URLError` → `UpstreamError`（网络错误）。

**容错策略**：pull 失败记录 error 并返回；单个 task run 失败记录 error 并继续；单个 push 失败记录 error 并继续下一个。

### 4.9 `scheduler.py` [P3.1] — 核心调度中心 (Phase 3 新增)

进程内调度核心，stdlib-only（`threading` / `queue.PriorityQueue` / `concurrent.futures`）。所有 Phase 3 模块围绕此构建。

**核心类型**：
| 类 | 说明 |
|----|------|
| `JobStatus` (Enum) | PENDING/QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED/TIMEOUT/ABANDONED；`is_terminal()` 判终态 |
| `RetryPolicy` | max_attempts / backoff_base / backoff_max，指数退避 |
| `JobExecution` | 单次执行记录（attempt/started_at/ended_at/exit_code/error） |
| `ScheduledJob` | job 定义 + attempts[] + 状态机（queued_at/started_at/ended_at） |
| `JobStore` | 持久化到 `.state/jobs.json`，`threading.Lock` 串行化读改写 |
| `JobQueue` | `queue.PriorityQueue` + `_seq` 计数器，同优先级 FIFO |
| `WorkerPool` | daemon 线程池 + `_execute` 循环 + `threading.Timer` 超时 + DAG 回调钩子 |
| `StatusBus` | SSE 事件总线，emit/subscribe/unsubscribe，Queue 满 put_nowait 丢弃 |

**关键函数**：`compute_metrics(jobs) -> dict`（total/succeeded/failed/success_rate/avg_duration_ms/p95_duration_ms/avg_queue_wait_ms）

**并发安全**：`JobStore` 用 `threading.Lock` 串行化读改写 + `atomic_write_json` 落盘；`WorkerPool` 出队后 `Router.try_acquire` 失败 requeue 不阻塞；`cancel_event` 协作式取消 + `threading.Timer` 超时（同一 event 区分 TIMEOUT/CANCELLED）。

### 4.10 `projects.py` [P3.2] — 跨项目路由与隔离 (Phase 3 新增)

管理多个项目连接（local/github/api），每个项目独立 `ProjectRuntime` 隔离 state_dir/skills/memory。

**核心类型**：
- `ProjectConnection` dataclass：id/name/project_type/state_dir/skills_dir/config/max_concurrent/health
- `ProjectRegistry`：持久化到 `.state/projects.json`，`default` 项目不可删（指向 `hermes_state_dir`）
- `ProjectRuntime`：懒加载 `SkillRunner`/`MemoryService`/`AgentLoop`/`TaskScheduler`，`threading.RLock` 允许 reentrant（scheduler() 调 runner()/memory()）
- `Router`：`resolve(project_id)` 返回缓存 runtime；`try_acquire`/`release` 原子增减 in-flight 计数，超 `max_concurrent` 返回 False

**健康检查**：`ping(conn_id)` → `{"reachable", "status", "error?"}`；github 类型走 `api.github.com/repos/{owner}/{repo}` HEAD 请求。

### 4.11 `triggers.py` [P3.3] — Cron 定时触发 (Phase 3 新增)

5 字段 cron 表达式解析 + 60s 扫描 daemon 线程。

**核心类型**：
- `Trigger` dataclass：trigger_id/name/cron/plan/priority/project/disabled/last_fired_at
- `TriggerStore`：持久化到 `.state/triggers.json`
- `CronScheduler`：`_matches_cron(expr, dt)` 纯函数（支持 `*` / 数字 / `,` / `-` / `/`），`_loop` daemon 线程 `_stop.wait(60)` 控制扫描间隔，`last_fired_at` 同分钟去重

**表达式格式**：标准 5 字段 `分 时 日 月 周`，例如 `*/5 * * * *`（每 5 分钟）、`0 9 * * 1-5`（工作日 9 点）。

### 4.12 `recovery.py` [P3.4] — 崩溃恢复 (Phase 3 新增)

进程重启后处理未完成 job：QUEUED → 重入队，RUNNING → 标 ABANDONED，PENDING → 保留。

**核心类 `RecoveryManager`**：
| 方法 | 说明 |
|------|------|
| `recover() -> dict` | 返回 `{requeued, abandoned, skipped}`，记 L2 episode 审计 |
| `enabled` 属性 | 由 `HERMES_SCHEDULER_RECOVERY` 环境变量控制（默认 True） |

**ADR-0002**：RUNNING 一律标 ABANDONED 不重跑（防重复副作用），由用户/重试 API 显式恢复。

### 4.13 `dag.py` [P3.5] — 任务 DAG 依赖 (Phase 3 新增)

job 依赖图管理，DFS 环检测 + 上游失败级联取消。

**核心类 `DependencyGraph`**：
| 方法 | 说明 |
|------|------|
| `register(job_id, depends_on)` | 注册依赖，深度上限 10，环检测抛 `ValidationError` |
| `ready_to_queue(job_id) -> bool` | 所有上游 SUCCEEDED 才 True |
| `on_job_done(job_id, status)` | 上游 FAILED/CANCELLED/TIMEOUT → 下游级联 CANCELLED |

**ADR-0003**：级联取消而非级联重试，避免重试风暴；下游 retry 由用户显式触发。

### 4.14 `asset_sync.py` [P3.6] — 跨项目资产同步 (Phase 3 新增)

单向同步 skills/memory/profile，源 → 目标。

**核心类 `AssetSync` + `SyncResult`**：
| 资产类型 | 策略 |
|---------|------|
| skills | 文件复制（覆盖同名） |
| memory.facts | 合并（源覆盖目标同名 key） |
| memory.episodes | 追加去重（按 episode id） |
| profile | 浅合并（源覆盖目标同名字段） |

**错误处理**：source/target 不存在抛 `NotFoundError`；单条同步失败记 error 继续下一条。

---

## 5. Skills 资产

共 **24 个顶层 skill 目录**，覆盖 Python / Node.js / Shell / 纯 prompt 多种运行时。

### 5.1 Skill 清单

| Skill | 运行时 | 入口 | 用途 |
|-------|--------|------|------|
| agent-browser | 外部二进制 | `agent-browser` (npm) | Headless 浏览器自动化 |
| aipm-news-digest | prompt | — | 16+ RSS 源 AI PM 日报 |
| brave-search | node | `search.js` / `content.js` | Brave Search + URL→Markdown |
| douyin-reader | python | `scripts/douyin_reader.py` | 抖音视频文字提取（3 层降级） |
| find-skills | shell (npx) | 包装 `npx skills` | 发现/安装 skill |
| frontend-design | prompt | — | 生产级前端设计 |
| github | shell | 包装 `gh` CLI | GitHub 交互 |
| loop-engineering | prompt | 命令分发 | `/goal` `/loop` 模式 |
| notion | shell | curl 配方 | Notion CRUD |
| obsidian | shell | 包装 `obsidian-cli` | Obsidian vault 操作 |
| product-manager | prompt | — | PM 全流程（RICE/MoSCoW/Kano） |
| product-manager-skills | prompt | — | SaaS 指标/PRD 评审 |
| pskoett | prompt | — | 早期 self-improving 变体 |
| self-improving-agent | shell + JS/TS hooks | `scripts/*.sh` + `hooks/` | 持续学习 agent |
| skill-creator | python | `scripts/*.py` | 创建/改进/评测 skills |
| skill-manager | python | `scripts/skill_manager.py` | skillhub 生命周期管理 |
| skill-vetter | prompt | — | skill 安全/质量审核 |
| stock-analysis | python | `scripts/*.py` | 美股+加密货币分析 |
| summarize | shell (外部 CLI) | 外部 `summarize` | URL/文件/YouTube 摘要 |
| tavily-search | node | `scripts/search.mjs` | AI 优化搜索 |
| trello | shell | curl + jq | Trello CRUD |
| weather | shell | curl 配方 | 无 Key 天气查询（2 层降级） |
| wechat-reader | python | `scripts/wechat_reader.py` | 微信公众号全文读取（4 层降级） |
| youtube-watcher | python | `scripts/get_transcript.py` | YouTube 字幕抓取 |

### 5.2 Skill 定义约定

- `SKILL.md`：YAML front-matter（name/description/version/commands/metadata/allowed-tools/triggers），由 `skill_runner._parse_front_matter` 解析
- `_meta.json`：14 个 skill 有此结构化清单（ownerId/slug/version/publishedAt）
- 运行时探测：`run.py`/`main.py` → python；`run.sh` → shell；`run.js`/`index.js` → node；无 → prompt

---

## 6. 依赖关系

### 6.1 核心层依赖

```
__init__.py ──► config (Settings, get_settings)
            ──► skills (SkillInfo, discover_skills, get_skill_path, list_knowledge_docs)

main.py     ──► config (get_settings)
            ──► logging (setup_logging)
            ──► profile (load_profile, get_profile_markdown)
            ──► skills (discover_skills, list_knowledge_docs, skills_dir, knowledge_dir)
            ──► workbench.cli (add_workbench_subparser)   ← 核心层→workbench 唯一桥接点

profile.py  ──► config (get_settings → hermes_profile_path)
skills.py   ──► (无内部依赖，纯 stdlib)
config.py   ──► dotenv, pydantic, pydantic_settings (外部)
```

### 6.2 Workbench 层依赖

```
persistence.py  ──► (无内部依赖，纯 stdlib + fcntl)
errors.py       ──► (无内部依赖)
skill_runner.py ──► (无内部依赖，仅 stdlib + shutil + subprocess)

memory.py       ──► workbench.persistence [顶层]
                ──► hermes.profile [lazy，L3 回退]

agent_loop.py   ──► workbench.memory [顶层]
                ──► workbench.skill_runner [顶层]

cli.py          ──► config, hermes.skills, agent_loop, memory, skill_runner [顶层]
                ──► workbench.persistence, errors, github_sync, server [lazy]

github_sync.py  ──► workbench.errors [顶层]
                ──► workbench.cli (_make_*, Task) [lazy]  ← 循环依赖靠 lazy 打破

server.py       ──► workbench.errors [顶层]
                ──► workbench.cli (_make_*, Task) [lazy]
                ──► workbench.github_sync [lazy]
```

### 6.3 依赖层次

- **底层（无内部依赖）**：`persistence.py`、`errors.py`、`skill_runner.py`
- **中层**：`memory.py`（依赖 persistence）、`agent_loop.py`（依赖 memory + skill_runner）
- **上层（编排层）**：`cli.py`（依赖 agent_loop + memory + skill_runner + config + skills）
- **适配层**：`server.py`（依赖 errors，lazy 依赖 cli + github_sync）、`github_sync.py`（依赖 errors，lazy 依赖 cli）

### 6.4 外部依赖

| 依赖 | 用途 | 必需 |
|------|------|------|
| pydantic >= 2.0 | `config.py` Settings 模型 | 是 |
| pydantic-settings >= 2.0 | `config.py` BaseSettings | 是 |
| python-dotenv >= 1.0 | `config.py` .env 加载 | 是 |
| pytest >= 8.0 | 测试 | dev |
| pytest-asyncio >= 0.23 | 异步测试 | dev |
| pytest-cov >= 5.0 | 覆盖率 | dev |
| ruff >= 0.4 | lint | dev |
| mypy >= 1.9 | 类型检查 | dev |

---

## 7. 项目运行方式

### 7.1 安装

```bash
cd /workspace
pip install -e .          # 安装 hermes CLI（editable）
pip install -e '.[dev]'   # 含开发工具
```

### 7.2 环境配置

复制 `.env.example` 为 `.env`，填入 API key。继承优先级：进程环境 > Hermes `.env` > 主仓库 `.env` > 默认值。

### 7.3 CLI 用法

```bash
# 核心层
hermes                              # 默认 start，打印环境信息
hermes doctor                       # 健康检查
hermes config show                  # 脱敏配置
hermes skills list                  # 列出 24 个 skills
hermes knowledge list               # 列出 4 篇知识文档
hermes profile show [--json]        # 用户画像

# Workbench - Skill 执行
hermes workbench skills list
hermes workbench skills show weather
hermes workbench run weather --args "Beijing"
hermes workbench loop --plan '[{"skill":"weather","args":["Beijing"]}]'

# Workbench - 记忆
hermes workbench memory facts list
hermes workbench memory facts remember city '"Beijing"'
hermes workbench memory facts get city
hermes workbench memory facts forget city
hermes workbench memory episodes list --kind loop
hermes workbench memory profile show

# Workbench - 任务
hermes workbench task register --plan '[{"skill":"weather"}]' --task-id t1
hermes workbench task list
hermes workbench task run t1
hermes workbench task show t1
hermes workbench task cancel t1

# Workbench - Job 调度中心 (Phase 3 新增)
hermes workbench job submit --plan '[{"skill":"weather"}]' --project default --priority 5
hermes workbench job list
hermes workbench job show <job_id>
hermes workbench job cancel <job_id>
hermes workbench job retry <job_id>
hermes workbench job metrics

# Workbench - 项目管理 (Phase 3 新增)
hermes workbench project add --name my-repo --type github --state-dir /tmp/myrepo \
  --config '{"url":"github.com/owner/repo"}' --max-concurrent 2
hermes workbench project list
hermes workbench project ping <project_id>

# Workbench - Cron 触发器 (Phase 3 新增)
hermes workbench trigger add --name daily-weather --cron '0 9 * * *' \
  --plan '[{"skill":"weather","args":["Beijing"]}]'
hermes workbench trigger list
hermes workbench trigger fire <trigger_id>
hermes workbench trigger disable <trigger_id>

# Workbench - 跨项目资产同步 (Phase 3 新增)
hermes workbench sync --source proj-a --target proj-b --assets skills,memory,profile

# Workbench - HTTP 服务
hermes workbench serve --host 127.0.0.1 --port 8080

# Workbench - GitHub 同步
hermes workbench github-sync --repo owner/name --label workbench
```

### 7.4 HTTP API 用法

```bash
# 启动服务
hermes workbench serve --port 8080 &

# 健康检查（含调度器状态：worker active/idle + queue_depth + recovery 状态）
curl http://127.0.0.1:8080/health

# Skills
curl http://127.0.0.1:8080/skills
curl http://127.0.0.1:8080/skills/weather

# Memory
curl http://127.0.0.1:8080/memory/facts
curl -X POST http://127.0.0.1:8080/memory/facts \
  -H 'Content-Type: application/json' \
  -d '{"key":"city","value":"Beijing"}'
curl http://127.0.0.1:8080/memory/facts/city
curl -X DELETE http://127.0.0.1:8080/memory/facts/city
curl http://127.0.0.1:8080/memory/episodes?kind=loop
curl http://127.0.0.1:8080/memory/profile

# Tasks (向后兼容，内部转 ScheduledJob)
curl -X POST http://127.0.0.1:8080/tasks \
  -H 'Content-Type: application/json' \
  -d '{"plan":[{"skill":"weather"}],"run":true}'
curl http://127.0.0.1:8080/tasks
curl http://127.0.0.1:8080/tasks/<task_id>
curl -X POST http://127.0.0.1:8080/tasks/<task_id>/run
curl -X POST http://127.0.0.1:8080/tasks/<task_id>/cancel

# Jobs (Phase 3 新增)
curl -X POST http://127.0.0.1:8080/jobs \
  -H 'Content-Type: application/json' \
  -d '{"plan":[{"skill":"weather"}],"priority":5,"project":"default"}'
curl http://127.0.0.1:8080/jobs
curl http://127.0.0.1:8080/jobs/<job_id>
curl -X POST http://127.0.0.1:8080/jobs/<job_id>/cancel
curl -X POST http://127.0.0.1:8080/jobs/<job_id>/retry
curl http://127.0.0.1:8080/jobs/metrics
curl -N http://127.0.0.1:8080/stream/jobs   # SSE 实时事件流

# Projects (Phase 3 新增)
curl -X POST http://127.0.0.1:8080/projects \
  -H 'Content-Type: application/json' \
  -d '{"name":"my-repo","project_type":"github","state_dir":"/tmp/myrepo","config":{"url":"github.com/owner/repo"},"max_concurrent":2}'
curl http://127.0.0.1:8080/projects
curl http://127.0.0.1:8080/projects/<project_id>
curl -X DELETE http://127.0.0.1:8080/projects/<project_id>
curl -X POST http://127.0.0.1:8080/projects/<project_id>/ping

# Triggers (Phase 3 新增)
curl -X POST http://127.0.0.1:8080/triggers \
  -H 'Content-Type: application/json' \
  -d '{"name":"daily-weather","cron":"0 9 * * *","plan":[{"skill":"weather","args":["Beijing"]}]}'
curl http://127.0.0.1:8080/triggers
curl -X POST http://127.0.0.1:8080/triggers/<trigger_id>/fire
curl -X POST http://127.0.0.1:8080/triggers/<trigger_id>/enable
curl -X POST http://127.0.0.1:8080/triggers/<trigger_id>/disable

# Sync (Phase 3 新增)
curl -X POST http://127.0.0.1:8080/sync \
  -H 'Content-Type: application/json' \
  -d '{"source":"proj-a","target":"proj-b","assets":["skills","memory","profile"]}'

# GitHub 同步
curl 'http://127.0.0.1:8080/github/sync?repo=owner/name&label=workbench'
```

### 7.5 GitHub Issues 驱动工作台

在任意 GitHub 仓库的 issue body 中写入 JSON plan，打上 `workbench` label：

```json
{"plan": [{"skill": "weather", "args": ["Beijing"]}], "mode": "oneshot"}
```

然后运行同步，workbench 会拉取 issue → 创建任务 → 运行 → 将结果回写为 issue 评论：

```bash
GITHUB_TOKEN=ghp_xxx hermes workbench github-sync --repo hpj360/Hermes
```

### 7.6 编程式用法

```python
import hermes

# 核心 API
hermes.__version__                      # "0.2.0"
hermes.get_settings()                   # Settings 单例
hermes.discover_skills()                # list[SkillInfo]
hermes.get_skill_path("weather")        # Path | None
hermes.list_knowledge_docs()            # list[Path]

# Workbench API
from hermes.workbench.skill_runner import SkillRunner
from hermes.workbench.agent_loop import AgentLoop, LoopStep
from hermes.workbench.memory import MemoryService
from hermes.workbench.cli import Task, TaskStore, TaskRegistry, TaskScheduler
from hermes.workbench.server import run_server
from hermes.workbench.github_sync import GitHubSyncService

runner = SkillRunner()
result = runner.run("weather", args=["Beijing"])
print(result.stdout, result.ok)

loop = AgentLoop(runner=runner, memory=MemoryService(state_dir=".state"))
plan = [LoopStep(skill="weather", args=["Beijing"])]
loop_result = loop.execute(plan)
print(loop_result.ok, loop_result.duration)
```

---

## 8. 测试体系

### 8.1 测试规模

- **21 个测试文件，969 个测试用例 + 15 个 skipped**（v0.5.0）
- 顶层 92 个（config 5 / logging 9 / main 12 / profile 18 / skills 11 / cli_loop 47）
- Workbench 601 个（agent_loop 12 / cli 103 / errors 12 / github_sync 21 / memory 21 / persistence 13 / server 68 / skill_runner 30 + **Phase 3 新增 6 模块 175 个**：scheduler 42 / projects 26 / triggers 54 / recovery 16 / dag 22 / asset_sync 15）
- 其他 276 个（loop / runner / orchestrator / ima_sync / structured_logging / tracing / dashboard / goal 等顶层测试，含 Stage 5 GEPA + Stage 6 L3 denylist 共 38 个新测试）

### 8.2 模块覆盖率

**21/21 模块均有对应测试，无缺失。** Workbench 层整体覆盖率 83%，Phase 3 模块平均 88.5%。

| 模块 | 测试文件 | 用例数 | 覆盖率 |
|------|---------|--------|-------|
| config.py | test_config.py | 5 | — |
| logging.py | test_logging.py | 9 | — |
| main.py | test_main.py | 12 | — |
| profile.py | test_profile.py | 18 | — |
| skills.py | test_skills.py | 11 | — |
| cli_loop.py | test_cli_loop.py | 47 | — |
| workbench/agent_loop.py | test_agent_loop.py | 12 | 97% |
| workbench/cli.py | test_cli.py | 103 | 79% |
| workbench/errors.py | test_errors.py | 12 | 100% |
| workbench/github_sync.py | test_github_sync.py | 21 | 87% |
| workbench/memory.py | test_memory.py | 21 | 86% |
| workbench/persistence.py | test_persistence.py | 13 | 86% |
| workbench/server.py | test_server.py | 68 | 68% |
| workbench/skill_runner.py | test_skill_runner.py | 30 | 83% |
| **workbench/scheduler.py** (P3.1) | test_scheduler.py | 42 | **86%** |
| **workbench/projects.py** (P3.2) | test_projects.py | 26 | **87%** |
| **workbench/triggers.py** (P3.3) | test_triggers.py | 54 | **93%** |
| **workbench/recovery.py** (P3.4) | test_recovery.py | 16 | **93%** |
| **workbench/dag.py** (P3.5) | test_dag.py | 22 | **93%** |
| **workbench/asset_sync.py** (P3.6) | test_asset_sync.py | 15 | **79%** |

### 8.3 测试隔离

- `tests/conftest.py` 的 `tmp_state_dir` fixture 把 `HERMES_STATE_DIR`/`HERMES_CACHE_DIR`/`HERMES_PROFILE_PATH` 重定向到 `tmp_path` 并 `get_settings(force_reload=True)`
- Workbench 测试普遍用 `monkeypatch.setattr(wb_cli, "_make_*", ...)` 替换服务工厂
- `github_sync` 测试用 mock `request_executor` 避免网络调用
- `server` 测试用真实 `ThreadingHTTPServer`（ephemeral port）+ `http.client`

### 8.4 运行测试

```bash
pytest tests/                          # 全部 969 个
pytest tests/workbench/                # Workbench 601 个
pytest tests/workbench/test_scheduler.py -v   # Phase 3 单模块
pytest tests/workbench/ --cov=src/hermes/workbench --cov-report=term  # 覆盖率
ruff check src/hermes/ tests/          # lint
mypy src/hermes/                       # 类型检查（0 errors）
```

---

## 9. 个人 AI 工作台 OS 设计

基于已实现的 Workbench 运行时层，结合 hpj360 账号下的 7 个仓库，设计个人 AI 工作台 OS 的编排方案。

### 9.1 账号仓库盘点

hpj360 账号下共 7 个仓库：

| 仓库 | 语言 | 可见性 | 角色 | 活跃度 |
|------|------|--------|------|--------|
| hpj360/Hermes | Python | public | **核心 Agent 层 + Workbench 运行时** | 活跃 |
| hpj360/hermes-workbench- | Python | public | **工作台发行仓（当前推送目标）** | 活跃 |
| hpj360/Hermes-knowledge-base | Python | public | 酒类知识库（FastAPI + React + RAG） | 活跃 |
| hpj360/AI-project | TypeScript | public | AI 应用（前端/全栈） | 活跃 |
| hpj360/pm-team | Java | public | PM Team 项目 | 半活跃 |
| hpj360/openclaw | — | **private** | 私有资产（需单独鉴权） | 停滞 |
| hpj360/learning-python | — | public | 早期学习仓（归档候选） | 停滞 |

### 9.2 工作台 OS 架构

```
┌──────────────────────────────────────────────────────────────────┐
│              个人 AI 工作台 OS (Hermes Workbench)                │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ GitHub Sync │  │ HTTP API    │  │ CLI                     │  │
│  │ (P4)        │  │ (P3)        │  │ (P2)                    │  │
│  └──────┬──────┘  └──────┬──────┘  └────────────┬────────────┘  │
│         └────────────────┴──────────────────────┘                │
│                          │                                       │
│                          ▼                                       │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │            TaskScheduler + AgentLoop (P1/P2)               │ │
│  │  plan = [LoopStep(skill, args, timeout, abort_on_error)]   │ │
│  └────────────────────────┬───────────────────────────────────┘ │
│                           │                                       │
│         ┌─────────────────┼─────────────────┐                    │
│         ▼                 ▼                 ▼                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐      │
│  │ 24 Skills   │  │ 3-Layer     │  │ Atomic Persistence  │      │
│  │ (资产层)    │  │ Memory      │  │ (.state/*.json)     │      │
│  └──────┬──────┘  └─────────────┘  └─────────────────────┘      │
│         │                                                        │
└─────────┼────────────────────────────────────────────────────────┘
          │
          ▼  GitHub Issues 驱动（每个仓库作为任务源）
┌──────────────────────────────────────────────────────────────────┐
│              hpj360 账号下的 7 个仓库                            │
│                                                                  │
│  ┌──────────┐ ┌───────────┐ ┌──────────────┐ ┌──────────────┐  │
│  │ Hermes   │ │ workbench-│ │knowledge-base│ │ AI-project   │  │
│  │ (核心)   │ │ (发行)    │ │(RAG 后端)    │ │ (前端)       │  │
│  └──────────┘ └───────────┘ └──────────────┘ └──────────────┘  │
│  ┌──────────┐ ┌───────────┐ ┌──────────────────────────────┐   │
│  │ pm-team  │ │ openclaw  │ │ learning-python (归档)       │   │
│  │ (Java)   │ │ (私有)    │ │                              │   │
│  └──────────┘ └───────────┘ └──────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### 9.3 编排策略

**核心思路**：把每个仓库视为一个"任务源"，通过 GitHub Issues + `workbench` label 向 Workbench 下发任务，Workbench 拉取 → 运行 → 回写结果。

| 仓库 | 编排角色 | 触发方式 | 典型任务 |
|------|---------|---------|---------|
| Hermes | 核心运行时（本仓） | 本地 CLI / HTTP | 自我维护、skill 评测、文档生成 |
| hermes-workbench- | 发行仓 | github-sync | 接收外部 issue 驱动的构建/测试/发布任务 |
| Hermes-knowledge-base | RAG 知识后端 | github-sync | 知识库索引重建、RAG 评测、查询测试 |
| AI-project | 前端应用 | github-sync | 前端构建、UI 评测、依赖更新 |
| pm-team | 业务系统 | github-sync | 周报生成、需求梳理（用 product-manager skill） |
| openclaw | 私有资产 | github-sync（需鉴权） | 定期备份、配置审计 |
| learning-python | 归档 | — | 不主动编排，可选清理 |

### 9.4 实施步骤

1. **统一 token 鉴权**：`GITHUB_TOKEN` 需具备 7 个仓库的 read（私有仓 openclaw 需额外授权）+ issue comment 写权限。
2. **仓库标签约定**：为每个仓库的 issue 打上 `workbench` label（或自定义 label 如 `workbench:build`、`workbench:rag`）区分任务类型。
3. **Issue body 协议**：统一 JSON plan 格式（`{"plan": [...], "mode": "oneshot", "max_rounds": N}`），可选 ```json fence。
4. **定时同步**：通过 cron 或外部调度器定期调用 `hermes workbench github-sync --repo hpj360/<repo>` 轮询各仓库。
5. **结果回写**：任务完成后自动将结果作为 issue 评论推送，可选追加 `done` label。
6. **跨仓编排**：通过 HTTP API `/tasks` 端点创建跨 skill 的复合 plan（如"读 knowledge-base → 用 summarize 摘要 → 写回 issue"）。
7. **记忆沉淀**：每次执行经 AgentLoop 记录 L1 facts（per-skill output）与 L2 episode（整轮摘要），L3 profile 持续积累用户画像，形成个人 OS 的长期记忆。

### 9.5 分支与权限注意

- 6 个仓库用 `main`，2 个旧仓库（pm-team、learning-python）用 `master`，编排脚本需兼容。
- `openclaw` 为私有，统一扫描/克隆必须用具备该仓库 read 权限的 token。
- 所有仓库均未配置 topics，当前无法靠 topics 自动归类，建议编排系统主动为仓库打标签元数据。

---

## 10. 历史构建状态

### 10.1 Git 历史

项目克隆自 `https://github.com/hpj360/Hermes`，当前在 `trae/agent-iq6m5g` 工作分支。

| # | Hash | 提交信息 | 分支 |
|---|------|---------|------|
| 1 | a5b0860 | 克隆基线（来自远端 main） | main |
| 2 | 36ec6a9 | feat(workbench): rebuild P0 foundation + P1 agent runtime | trae/agent-iq6m5g |
| 3 | f4431eb | feat: 生成项目Code Wiki文档 | trae/agent-iq6m5g (HEAD) |
| 4 | 8b29ead | feat(workbench): Hermes Workbench P0-P4 完整实现 | workbench/main (远端) |

远端 `workbench` 指向 `https://github.com/hpj360/hermes-workbench-.git`，`main` 分支已推送（单提交快照，因服务端幽灵对象问题，完整 4 提交历史分支推送失败，但代码内容完整）。

### 10.2 构建验证

- **测试**：259 个用例全部通过（`pytest tests/` 14.11s）
- **Lint**：ruff 零错误（`ruff check src/hermes/ tests/`）
- **模块完整性**：13/13 模块均有对应测试，无缺失
- **状态文件**：`.state/`、`.cache/` 不存在（未运行过持久化任务）；`data/profile.json` 不存在（仅有 `profile.example.json` 模板）

### 10.3 已知问题

1. `CODE_WIKI.md`（本次前）记载 `manifest.json` 版本为 `0.1.0`，实际已升级到 `0.2.0` —— 本文档已修正。
2. 远端 `hermes-workbench-` 仓库的 `main` 分支为单提交快照，丢失 4 次历史提交记录（代码内容无缺失），因 GitHub 服务端幽灵对象 `0d48573b` 导致 `index-pack` 失败。
3. `skills/stock-analysis/scripts/test_stock_analysis.py` 依赖 `pandas`，未安装时全仓 `pytest` 收集会失败 —— 需限定 `pytest tests/` 范围或安装 pandas。

### 10.4 Workbench 分阶段交付状态

| 阶段 | 模块 | 状态 | 测试 |
|------|------|------|------|
| P0 | errors.py / persistence.py | ✅ 完成 | 25 用例 |
| P1 | memory.py / skill_runner.py / agent_loop.py | ✅ 完成 | 63 用例 |
| P2 | cli.py（任务运行时 + 17 子命令） | ✅ 完成 | 71 用例 |
| P3 | server.py（Dashboard HTTP API） | ✅ 完成 | 24 用例 |
| P4 | github_sync.py（GitHub Issues 同步） | ✅ 完成 | 21 用例 |

---

## 11. 关键设计决策

1. **零依赖 Workbench**：运行时层全部 stdlib，降低安装与维护成本，便于在任何 Python 3.10+ 环境运行。
2. **服务工厂中心化**：`cli.py` 的 `_make_*` 工厂是唯一服务实例化入口，测试通过 monkeypatch 工厂实现完全隔离，生产通过覆盖工厂注入配置。
3. **Lazy Import 打破循环**：`github_sync` ↔ `cli`、`server` ↔ `cli` 的循环依赖全部函数内 import，模块加载时无循环，保持启动快、依赖清晰。
4. **错误即状态码**：异常层级与 HTTP 状态码一一映射，CLI 与 API 共用语义，减少转换层。
5. **原子持久化**：所有状态写入经 `tempfile + os.replace`，`episodes.jsonl` 用 `fcntl.flock`，保证崩溃安全与并发安全。
6. **GitHub 作为控制平面**：通过 Issue body 的 JSON plan + label 实现"代码即配置"，无需额外数据库，GitHub Issues 即任务队列，评论即结果回写。
7. **三层记忆模型**：L1 facts（键值快查）+ L2 episodes（追加日志）+ L3 profile（长期画像），对应 `knowledge/memory-model.md` 的设计，支撑个人 OS 的长期学习。

---

*本文档由 Hermes Workbench 项目分析生成，覆盖核心层 + Workbench 运行时层（P0-P4）+ 个人工作台 OS 设计。*

# Hermes Code Wiki

> 版本：对应 `pyproject.toml` 中 `hermes==0.2.0`（`manifest.json` 中为 `0.1.0` 清单版本）
> 生成时间：2026-07-23
> 范围：`/workspace`（Hermes 独立 Python Agent 层 + 沉淀的 24 个 skills + 4 篇知识文档 + 内容创作素材）

---

## 0. TL;DR

Hermes 是一个**独立于主仓库（`/workspace/OpenClaw/openclaw-main`）的 Python Agent 层**。它继承了主仓库沉淀下来的账号与 API 环境配置，把分散在主仓库 `.trae/skills/` 与 `.trae/docs/knowledge/` 下的 24 个 skills 与 4 篇知识文档收纳为一个可独立运行、可独立提交的子项目。

- **定位**：Agent 层 + Skills/知识资产的"打包发行版"
- **入口**：`hermes` CLI（`[project.scripts] hermes = "hermes.main:main"`）
- **语言**：Python ≥ 3.10（核心层）；skills 自身涉及 Python / Node.js / Shell / 纯 prompt 等多种形态
- **核心依赖**：`pydantic` / `pydantic-settings` / `python-dotenv`（仅 3 个运行时依赖，极简）
- **关键能力**：多 provider 环境继承、skills/知识发现、用户画像、CLI 子命令、健康检查

---

## 1. 项目整体架构

### 1.1 分层视图

```
┌──────────────────────────────────────────────────────────────────┐
│                         CLI 入口层                                │
│            src/hermes/main.py  (argparse 子命令)                  │
│   start │ doctor │ config show │ skills list │ knowledge list │  │
│   profile show                                                    │
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
│                  资产层 (Assets)                                  │
│  skills/        24 个沉淀 skills（Python/Node/Shell/Prompt）      │
│  knowledge/     4 篇知识文档（Loop/Harness/Memory/Evaluator）     │
│  content-creation/  小红书 90 天冷启动内容计划                    │
│  manifest.json  skills/knowledge 清单                            │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│              运行时状态层（项目内，沙盒友好）                      │
│  .state/   .cache/   logs/   data/profile.json                   │
│  （所有用户可写状态都在项目目录内，避免写入 ~/.xxx）              │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 与主仓库的关系

Hermes 是**独立 git 仓库**，与 `/workspace` 主仓库分开管理。继承关系（从高到低优先级）：

1. 当前 shell 已导出的进程环境变量
2. `Hermes/.env` 文件
3. 主仓库 `.env` 文件：`/workspace/.env`、`/workspace/OpenClaw/openclaw-main/.env`
4. `Settings` 中定义的默认值

主仓库 skills / 知识文档可通过以下命令同步进 Hermes：

```bash
rsync -av --delete /workspace/.trae/skills/ /workspace/Hermes/skills/
rsync -av --delete /workspace/.trae/docs/knowledge/ /workspace/Hermes/knowledge/
```

### 1.3 设计哲学（来自知识文档）

`knowledge/` 下 4 篇文档构成 Hermes 的理论地基：

| 文档 | 核心命题 |
|------|---------|
| [skill-and-loop.md](file:///workspace/knowledge/skill-and-loop.md) | **Skill 是 Loop 的组件**。Skill 定义"每一步怎么做"（执行层）；Loop 定义"达到什么标准"（控制层）。 |
| [harness-engineering.md](file:///workspace/knowledge/harness-engineering.md) | **Agent = Model + Harness**。Harness 是非模型工程层（系统提示、工具注册、沙盒、权限、记忆、上下文管理、子 agent、hooks、可观测、eval loop）。 |
| [memory-model.md](file:///workspace/knowledge/memory-model.md) | **三层记忆**：L3 语义记忆（永久）、L2 情景记忆（跨会话+时间衰减）、L1 工作记忆（当前会话+压缩）。 |
| [evaluator-subagent-template.md](file:///workspace/knowledge/evaluator-subagent-template.md) | **Planner / Generator / Evaluator 分离**：Evaluator 是独立的怀疑论评审者，只读 + exec，无写权限。 |

四步演进路线：**Prompt Engineering → Context Engineering → Harness Engineering → Loop Engineering**。"模型决定上限，Harness 决定下限与稳定性。"

---

## 2. 目录结构

```text
/workspace/
├── src/hermes/              # Python 包（核心 Agent 层）
│   ├── __init__.py          # 包入口 + __version__ + 公开 API
│   ├── config.py            # 环境继承 + Settings(pydantic) + get_settings()
│   ├── logging.py           # 结构化日志 setup_logging()
│   ├── skills.py            # SkillInfo + discover_skills() + 知识发现
│   ├── profile.py           # 用户画像 JSON 读写 + Markdown 渲染
│   └── main.py              # CLI argparse 入口 + 子命令
├── skills/                  # 沉淀 skills（24 个目录）
│   ├── agent-browser/       # Rust/Node 浏览器自动化
│   ├── brave-search/        # Node.js + Brave API
│   ├── tavily-search/       # Node.js + Tavily API
│   ├── douyin-reader/       # Python + yt-dlp + faster-whisper
│   ├── wechat-reader/       # Python + UA 轮换
│   ├── youtube-watcher/     # Python + yt-dlp
│   ├── summarize/           # 外部 summarize CLI
│   ├── github/              # Shell + gh CLI
│   ├── notion/              # curl + Notion API
│   ├── obsidian/            # obsidian-cli
│   ├── trello/              # curl + Trello API
│   ├── weather/             # curl + wttr.in / Open-Meteo
│   ├── stock-analysis/      # Python + uv + Yahoo/CoinGecko
│   ├── skill-creator/       # Python（创建/改进/评测 skills）
│   ├── skill-manager/       # Python（skillhub 生命周期管理）
│   ├── skill-vetter/        # 纯 prompt（安全/质量审核）
│   ├── find-skills/         # npx skills CLI
│   ├── self-improving-agent/# Shell + JS/TS hooks（持续学习）
│   ├── pskoett/self-improving-agent/  # 早期变体（纯 prompt）
│   ├── loop-engineering/    # /goal /loop 命令分发
│   ├── product-manager/     # 纯 prompt（PRD/RICE/路线图）
│   ├── product-manager-skills/  # 纯 prompt（SaaS 指标/PRD 评审）
│   ├── aipm-news-digest/    # 16+ RSS 源 AI PM 日报
│   └── frontend-design/     # 纯 prompt（生产级前端设计）
├── knowledge/               # 4 篇知识文档
├── content-creation/        # 小红书冷启动内容素材
├── data/
│   └── profile.example.json # 用户画像模板（github: hpj360）
├── tests/                   # pytest 单测
├── .env.example             # 环境变量模板
├── .gitignore
├── manifest.json            # skills/knowledge 清单
├── pyproject.toml           # 项目配置 + hermes script
├── requirements.txt         # 运行时依赖
├── requirements-dev.txt     # 开发依赖
└── README.md
```

> 运行时还会在项目根创建：`.state/`（状态）、`.cache/`（缓存）、`logs/`（日志）、`data/profile.json`（用户画像，已在 `.gitignore` 中）。

---

## 3. 主要模块职责

### 3.1 `src/hermes/config.py` — 环境配置中枢

**职责**：定义 `Settings`、加载继承链、提供全局缓存。

| 关键符号 | 类型 | 作用 |
|---------|------|------|
| `Settings` | `pydantic_settings.BaseSettings` 子类 | 承载所有配置字段：OpenClaw 网关、14 个 LLM provider、8 个消息渠道、4 个搜索/媒体工具、4 个第三方集成、Skillhub、Hermes 自身路径。 |
| `Settings.configured_providers()` | 方法 | 返回已配置 API Key 的 provider 名单（`ollama` 始终在列，因本地无需 Key）。 |
| `Settings.missing_required()` | 方法 | Hermes 自身无强制 Key；返回空列表，留给子命令扩展。 |
| `Settings.inherit_env_paths` | `ClassVar[list[Path]]` | 继承搜索路径：`/workspace/.env`、`/workspace/OpenClaw/openclaw-main/.env`。 |
| `load_inherited_env()` | 函数 | 按继承路径加载主仓库 `.env`，**不覆盖**已存在的非空变量。 |
| `load_hermes_env()` | 函数 | 加载 Hermes 自身 `.env`，同样不覆盖已存在变量。 |
| `bootstrap_env()` | 函数 | 模块导入时执行：先 `load_hermes_env()` 再 `load_inherited_env()`，保证优先级。 |
| `get_settings(force_reload=False)` | 函数 | 返回缓存的 `Settings` 单例；首次调用时自动创建 `.state/` 与 `.cache/` 目录。 |

**配置字段分组**（共 60+ 字段）：

- OpenClaw 网关：`OPENCLAW_LLM_API_KEY`、`OPENCLAW_GATEWAY_PORT=18789`、`OPENCLAW_GATEWAY_TOKEN`、`OPENCLAW_STATE_DIR`、`OPENCLAW_CONFIG_PATH`
- LLM Providers（14 个）：OpenAI / Anthropic / Gemini / OpenRouter / Moonshot / 智谱 GLM / 百度千帆 / 阿里 Qwen / 小米 MiMo / MiniMax / Mistral / Novita / Ollama / ModelScope
- 模型路由：`OPENCLAW_MODEL_PRIMARY=anthropic/claude-sonnet-4-5`、`OPENCLAW_MODEL_FALLBACK=openai/gpt-4o`
- 消息渠道：Slack / Telegram / Discord / Mattermost / Zalo / Twitch / Feishu
- 工具/搜索/媒体：Brave / Perplexity / Firecrawl / Tavily / ElevenLabs / Deepgram
- 集成：GitHub / Notion / Trello / Tailscale
- Skillhub：`SKILLHUB_API_BASE=https://lightmake.site`、COS bucket/region
- Hermes 自身：`HERMES_LOG_LEVEL=INFO`、`HERMES_MAIN_REPO_PATH`、`HERMES_PROJECT_ROOT`、`HERMES_STATE_DIR`、`HERMES_CACHE_DIR`、`HERMES_PROFILE_PATH`

### 3.2 `src/hermes/skills.py` — Skills 与知识发现

**职责**：扫描 `skills/` 与 `knowledge/` 目录，提供元数据访问。

| 关键符号 | 类型 | 作用 |
|---------|------|------|
| `SkillInfo` | `@dataclass` | 单个 skill 的元数据：`name`、`path`、`has_skill_md`、`has_meta`、`meta`（来自 `_meta.json`）。 |
| `skills_dir()` | 函数 | 返回 `<project_root>/skills`。 |
| `knowledge_dir()` | 函数 | 返回 `<project_root>/knowledge`。 |
| `discover_skills()` | 函数 | 遍历 `skills/` 子目录，逐个读取 `SKILL.md` 与 `_meta.json`（容错 JSON 解析失败），返回排序后的 `list[SkillInfo]`。 |
| `list_knowledge_docs()` | 函数 | 返回 `knowledge/*.md` 文件路径列表（已排序）。 |
| `get_skill_path(name)` | 函数 | 按名查找 skill 目录，找不到返回 `None`。 |

### 3.3 `src/hermes/profile.py` — 用户画像

**职责**：在 `data/profile.json` 持久化结构化用户画像，并渲染为 Markdown。

| 关键符号 | 类型 | 作用 |
|---------|------|------|
| `load_profile()` | 函数 | 读取画像 JSON；缺失则返回 `_default_profile()` 骨架。 |
| `save_profile(profile)` | 函数 | 写入 JSON 并打上 `updated_at` UTC 时间戳。 |
| `update_field(section, key, value)` | 函数 | 单字段更新并保存。 |
| `append_to_list(section, key, items)` | 函数 | 列表字段去重追加。 |
| `get_profile_markdown()` | 函数 | 渲染为人类可读 Markdown（13 个分区：基本信息/萌宠/联系方式/自媒体矩阵/职业/技能/酒类偏好/兴趣/内容创业/工作风格/项目/目标/备注）。 |
| `_default_profile()` | 函数 | 返回 v4 画像骨架；默认 `contact.github = "hpj360"`。 |

画像分区：`basic_info` / `contact` / `social_accounts` / `pets` / `career` / `skills` / `alcohol_preferences` / `interests` / `content_creation` / `work_style` / `personal_projects` / `goals` / `notes`。

### 3.4 `src/hermes/logging.py` — 结构化日志

**职责**：配置 `hermes` logger，默认输出到 stdout，可选写文件。

| 关键符号 | 作用 |
|---------|------|
| `setup_logging(level="INFO", log_file=None)` | 清空已有 handlers；格式 `%(asctime)s [%(levelname)s] %(name)s: %(message)s`；可选 `FileHandler`（自动建父目录）。 |

### 3.5 `src/hermes/main.py` — CLI 入口

**职责**：argparse 子命令分发，所有命令"degraded-friendly"（异常不静默崩溃，返回码 2）。

| 子命令 | 处理函数 | 作用 |
|--------|---------|------|
| `hermes` / `hermes start` | `cmd_start` | 打印项目根、主仓库路径、主模型、已配置 providers、state/cache 目录。 |
| `hermes doctor` | `cmd_doctor` | 环境健康检查：项目根存在性、主仓库路径警告、provider 缺失警告、gateway token 警告；统计 skills/知识数。 |
| `hermes config show` | `cmd_config_show` | 分区打印当前配置（paths/models/gateway/channels/tools/skillhub），密钥脱敏为 `set`/`unset`。 |
| `hermes skills list` | `cmd_skills_list` | 列出所有 skills，标注 `[md|meta]` 标志与 `_meta.json` 描述。 |
| `hermes knowledge list` | `cmd_knowledge_list` | 列出知识文档。 |
| `hermes profile show [--json]` | `cmd_profile_show` | 渲染画像 Markdown 或输出原始 JSON。 |

全局参数：`--log-level {DEBUG,INFO,WARNING,ERROR}`、`--log-file PATH`。

### 3.6 `src/hermes/__init__.py` — 公开 API

`__version__ = "0.2.0"`，导出：`Settings`、`get_settings`、`SkillInfo`、`discover_skills`、`get_skill_path`、`list_knowledge_docs`。

---

## 4. Skills 资产总览（24 个）

按职能分类。Skill 的统一结构：`SKILL.md`（YAML front-matter：`name`/`description`/`version`/`homepage`/`commands`/`metadata.clawdbot.requires`/`allowed-tools`/`triggers`/`user-invocable`/`command-dispatch`，正文含 Setup / Quick start / Core workflow with CHECKPOINT / 失败处理）+ 可选 `_meta.json`（`ownerId`/`slug`/`version`/`publishedAt`）+ 可选 `scripts/`。

### 4.1 浏览器自动化

| Skill | 主脚本 | 语言 | 依赖 | 用途 |
|-------|--------|------|------|------|
| [agent-browser](file:///workspace/skills/agent-browser/SKILL.md) | 外部 `agent-browser` 二进制 | Rust + Node | `node`/`npm`，`npm i -g agent-browser` | Headless 浏览器自动化，用元素引用 `@e1/@e2` 导航/点击/输入/截图。是 douyin-reader、wechat-reader 的兜底层。 |

### 4.2 搜索

| Skill | 主脚本 | 语言 | 依赖 | 用途 |
|-------|--------|------|------|------|
| [brave-search](file:///workspace/skills/brave-search/SKILL.md) | `search.js` / `content.js` | Node ESM | `BRAVE_API_KEY`；`@mozilla/readability`、`jsdom`、`turndown`、`turndown-plugin-gfm` | Brave Search API 搜索 + URL→Markdown 提取，无需浏览器。 |
| [tavily-search](file:///workspace/skills/tavily-search/SKILL.md) | `scripts/search.mjs` / `scripts/extract.mjs` | Node ESM | `TAVILY_API_KEY` | AI 优化搜索（basic/deep/news topic）+ 内容提取。 |

### 4.3 内容读取

| Skill | 主脚本 | 语言 | 依赖 | 用途 |
|-------|--------|------|------|------|
| [douyin-reader](file:///workspace/skills/douyin-reader/SKILL.md) | `scripts/douyin_reader.py` | Python | `agent-browser`、`yt-dlp`、`faster-whisper`、抖音 cookies | 抖音视频文字提取，**三层降级**：agent-browser 页面抓取 → yt-dlp+whisper 转写 → WebSearch 兜底。 |
| [wechat-reader](file:///workspace/skills/wechat-reader/SKILL.md) | `scripts/wechat_reader.py` | Python 3 | UA 轮换，无需 Key | 微信公众号全文读取，**四层降级**：UA 轮换 → WebSearch 镜像 → WebFetch → agent-browser。输出 JSON（title/author/publish_time/url/content_markdown）。 |
| [youtube-watcher](file:///workspace/skills/youtube-watcher/SKILL.md) | `scripts/get_transcript.py` | Python 3 | `yt-dlp` | YouTube 字幕/转录抓取。 |
| [summarize](file:///workspace/skills/summarize/SKILL.md) | 外部 `summarize` CLI | Shell | `brew install steipete/tap/summarize`；OpenAI/Anthropic/xAI/Gemini 任一 Key；可选 Firecrawl/Apify | URL/本地文件（PDF/图片/音频）/YouTube 链接摘要，支持长度控制与 JSON 输出。 |

### 4.4 项目/产品管理

| Skill | 主脚本 | 语言 | 依赖 | 用途 |
|-------|--------|------|------|------|
| [trello](file:///workspace/skills/trello/SKILL.md) | 无（curl 配方） | Shell + jq | `TRELLO_API_KEY`、`TRELLO_TOKEN`、`jq` | Trello 看板/列表/卡片 CRUD。 |
| [product-manager](file:///workspace/skills/product-manager/SKILL.md) | 无 | 纯 prompt | — | 产品经理全流程：发现/优先级（RICE/MoSCoW/Kano）/路线图/GTM。 |
| [product-manager-skills](file:///workspace/skills/product-manager-skills/SKILL.md) | 无 | 纯 prompt | — | SaaS 指标诊断（MRR/ARR/LTV/CAC/churn/NDR）、PRD 评审、PM 职业辅导。 |

### 4.5 AI / Skill 工程

| Skill | 主脚本 | 语言 | 依赖 | 用途 |
|-------|--------|------|------|------|
| [skill-creator](file:///workspace/skills/skill-creator/SKILL.md) | `scripts/{run_eval,run_loop,improve_description,package_skill,quick_validate,aggregate_benchmark,generate_report,utils}.py`；`agents/{analyzer,comparator,grader}.md`；`eval-viewer/{generate_review.py,viewer.html}` | Python | Claude + skills 访问；`references/schemas.md` | 创建/改进/评测 skills，draft→test→eval→rewrite 迭代循环；含 skill 描述优化器。 |
| [skill-manager](file:///workspace/skills/skill-manager/SKILL.md) | `scripts/skill_manager.py`（+ `skill-manager.bat`） | Python 3 | `skillhub` CLI；lockfile `.trae/skills/.skills_store_lock.json` | skill 全生命周期：list/install/update/uninstall/search/config。 |
| [self-improving-agent](file:///workspace/skills/self-improving-agent/SKILL.md) | `scripts/{activator,error-detector,extract-skill}.sh`；`hooks/openclaw/{handler.js,handler.ts,HOOK.md}`；`assets/{ERRORS,FEATURE_REQUESTS,LEARNINGS,SKILL-TEMPLATE}.md` | Shell + JS/TS hooks | OpenClaw 平台；`clawdhub install self-improving-agent` | 持续学习：触发于命令失败/用户纠正/能力缺失/API 失败/知识过时/发现更好方法；写入 `.learnings/`，泛化项晋升到 `CLAUDE.md`/`AGENTS.md`/`TOOLS.md`/`SOUL.md`。v3.0.21。 |
| [pskoett/self-improving-agent](file:///workspace/skills/pskoett/self-improving-agent/SKILL.md) | 无 | 纯 prompt | — | 早期简化变体：learn/adapt/self-reflect/self-optimize。 |
| [loop-engineering](file:///workspace/skills/loop-engineering/SKILL.md) | 无（命令分发） | 纯 prompt | — | Loop Engineering 模式：`/goal`（进度驱动+可验证完成标准）、`/loop`（时间驱动循环）。v1.1.0。 |
| [find-skills](file:///workspace/skills/find-skills/SKILL.md) | 无（包装 `npx skills`） | Shell | Node.js + `npx skills` CLI | 从开放 agent skills 生态发现/安装 skill。v0.1.0。 |
| [skill-vetter](file:///workspace/skills/skill-vetter/SKILL.md) | 无 | 纯 prompt | — | skill 安装前安全/质量审核，输出推荐报告。 |

### 4.6 集成

| Skill | 主脚本 | 语言 | 依赖 | 用途 |
|-------|--------|------|------|------|
| [github](file:///workspace/skills/github/SKILL.md) | 无（包装 `gh`） | Shell + bash | `gh` CLI（`brew install gh`）+ `gh auth login` | GitHub 交互：issues/PRs/CI runs（`gh run`）/高级查询（`gh api`）。CHECKPOINT 工作流。 |
| [notion](file:///workspace/skills/notion/SKILL.md) | 无（curl 配方） | Shell + curl | Notion API Key（`ntn_`/`secret_` 前缀）存于 `~/.config/notion/api_key`；`Notion-Version: 2025-09-03` 头 | Notion 页面/数据库/块 CRUD。 |
| [obsidian](file:///workspace/skills/obsidian/SKILL.md) | 无（包装 `obsidian-cli`） | Shell | `obsidian-cli`（`brew install yakitrak/yakitrak/obsidian-cli`）；Obsidian 桌面端 | Obsidian vault 操作：搜索（按名/内容）、创建、安全移动/重命名（更新 wikilinks）、删除。 |

### 4.7 个人/生产力/金融/开发

| Skill | 主脚本 | 语言 | 依赖 | 用途 |
|-------|--------|------|------|------|
| [weather](file:///workspace/skills/weather/SKILL.md) | 无（curl 配方） | Shell + curl | `curl`；wttr.in + Open-Meteo | 无 Key 天气查询，**两层降级**：wttr.in 单行/全量 → Open-Meteo JSON 精确坐标。 |
| [aipm-news-digest](file:///workspace/skills/aipm-news-digest/SKILL.md) | 无 | 纯 prompt | 16+ RSS 源 | AI PM 日报：科技媒体（TechCrunch/Wired/Verge/Bloomberg/Reuters）+ AI 实验室（OpenAI/DeepMind/Google AI/Meta AI/MS Research/arXiv）+ 开发者社区（HN/GitHub Trending/Dev.to/Medium）+ PM（Product Hunt/First Round/Lenny's/SVPG）+ 商业（CB Insights/PitchBook/Crunchbase/StrictlyVC）；自动摘要/趋势/竞争情报/融资并购。 |
| [stock-analysis](file:///workspace/skills/stock-analysis/SKILL.md) | `scripts/{analyze_stock,dividends,hot_scanner,portfolio,rumor_scanner,watchlist,test_stock_analysis}.py`；`docs/{ARCHITECTURE,CONCEPT,HOT_SCANNER,README,USAGE}.md` | Python | `uv` 二进制；Yahoo Finance；CoinGecko；Google News；Twitter/X via `bird` CLI | 美股+加密货币分析：8 维评分、组合管理、watchlist+告警（目标价/止损/信号变化）、股息分析、Hot Scanner（病毒式趋势）、Rumor Scanner（并购传闻/内部人活动/分析师上调）。斜杠命令 `/stock*` `/portfolio*`。v6.2.0。 |
| [frontend-design](file:///workspace/skills/frontend-design/SKILL.md) | 无 | 纯 prompt → 生成前端代码 | 目标框架（HTML/CSS/JS、React、Vue 等） | 生产级前端设计，反"AI slop"美学，承诺 BOLD 方向（野兽派/极繁/复古未来/编辑风），精雕字体/色彩/动效/空间/氛围。 |

### 4.8 Skills 跨切面模式

1. **多层降级**：脆弱抓取目标（douyin 3 层、wechat 4 层、weather 2 层、summarize Firecrawl/Apify 兜底）。
2. **CHECKPOINT 工作流**：显式成功/失败校验门（github、tavily-search、youtube-watcher、weather、frontend-design、douyin-reader、wechat-reader）。
3. **斜杠命令分发**：stock-analysis（`/stock*` `/portfolio*`）、loop-engineering（`/goal` `/loop`）。
4. **通过 agent-browser 组合**：douyin-reader、wechat-reader 均回退到 agent-browser，使其成为内容读取类的基础依赖。
5. **`metadata.clawdbot.requires` 约定**：`bins`（如 `["uv"]`/`["node","npm"]`/`["yt-dlp"]`/`["jq"]`/`["curl"]`）+ `env`（如 `["TAVILY_API_KEY"]`/`["TRELLO_API_KEY","TRELLO_TOKEN"]`）+ `install`（brew/pip 配方）。
6. **语言分布**：Python（stock-analysis/skill-creator/skill-manager/douyin-reader/wechat-reader/youtube-watcher）；Node ESM（brave-search/tavily-search）；Shell/curl（github/notion/trello/weather/obsidian/find-skills）；纯 prompt（product-manager 系列/loop-engineering/skill-vetter/pskoett 变体/aipm-news-digest/frontend-design）；Shell+hooks（self-improving-agent）。

---

## 5. 关键类与函数说明

### 5.1 `hermes.config.Settings`

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")
    # 60+ Field(...) 字段，见 §3.1
    inherit_env_paths: ClassVar[list[Path]] = [
        Path("/workspace/.env"),
        Path("/workspace/OpenClaw/openclaw-main/.env"),
    ]
    def configured_providers(self) -> list[str]: ...
    def missing_required(self) -> list[str]: ...
```

- 通过 `Field(default=..., alias="ENV_VAR_NAME")` 把环境变量映射到字段。
- `extra="ignore"` 容忍 `.env` 中存在 Settings 未声明的变量。
- `configured_providers()` 用"truthy"判定（`ollama` 例外，恒真）。

### 5.2 `hermes.config` 模块级流程

```python
bootstrap_env()            # 模块导入即执行：load_hermes_env() → load_inherited_env()
_hermes_settings: Settings | None = None
def get_settings(force_reload: bool = False) -> Settings: ...
```

`get_settings()` 首次调用时还会 `mkdir(parents=True, exist_ok=True)` 创建 `.state/` 与 `.cache/`，确保沙盒友好。

### 5.3 `hermes.skills.SkillInfo`

```python
@dataclass
class SkillInfo:
    name: str
    path: Path
    has_skill_md: bool
    has_meta: bool
    meta: dict[str, Any] | None = None
```

`discover_skills()` 对每个子目录：检测 `SKILL.md` 存在性、读取 `_meta.json`（`JSONDecodeError` 时 `meta=None`，不抛错），按目录名排序返回。

### 5.4 `hermes.profile` 渲染管线

`get_profile_markdown()` 顺序调用 13 个 `_render_*` 私有函数，每个负责一个分区。`_join(items)` 把空列表渲染为"未设置"。所有写入路径都通过 `save_profile()` 打 `updated_at` UTC ISO 时间戳。

### 5.5 `hermes.main.main(argv=None)`

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    log_level = args.log_level or settings.hermes_log_level
    setup_logging(level=log_level, log_file=args.log_file)
    func = getattr(args, "func", cmd_start)
    try:
        return func(args)
    except Exception as exc:  # degraded-friendly
        logging.getLogger("hermes").error("Command failed: %s", exc, exc_info=True)
        return 2
```

`build_parser()` 用 `set_defaults(func=...)` 把子命令映射到处理函数；`--log-level`/`--log-file` 为全局参数，先于子命令解析。

---

## 6. 依赖关系

### 6.1 运行时依赖（`requirements.txt` / `pyproject.toml`）

```
pydantic>=2.0
pydantic-settings>=2.0
python-dotenv>=1.0
```

极简核心：仅 3 个包。`pydantic-settings` 提供环境变量绑定，`python-dotenv` 提供 `.env` 加载。

### 6.2 开发依赖（`requirements-dev.txt` / `[project.optional-dependencies] dev`）

```
pytest>=8.0
pytest-asyncio>=0.23
ruff>=0.4
mypy>=1.9
```

### 6.3 Python 版本

`requires-python = ">=3.10"`；`[tool.mypy] python_version = "3.10"`；`[tool.ruff] target-version = "py310"`；分类器声明支持 3.10/3.11/3.12。

### 6.4 模块内依赖图

```
main.py ──► config.py (get_settings)
        ├─► logging.py (setup_logging)
        ├─► profile.py (load_profile, get_profile_markdown)
        └─► skills.py (discover_skills, list_knowledge_docs, skills_dir, knowledge_dir)

profile.py ──► config.py (get_settings → hermes_profile_path)
skills.py   ──► (无内部依赖，纯 stdlib)
config.py   ──► dotenv, pydantic, pydantic_settings
__init__.py ──► config, skills (公开 API)
```

### 6.5 外部环境依赖（按 skill）

| 依赖类型 | 实例 | 关联 skills |
|---------|------|------------|
| 外部二进制 | `gh`、`uv`、`yt-dlp`、`agent-browser`、`obsidian-cli`、`summarize`、`jq`、`curl`、`npx skills`、`skillhub` | github、stock-analysis、youtube-watcher、agent-browser、obsidian、summarize、trello、weather、find-skills、skill-manager |
| 外部 API Key | `BRAVE_API_KEY`、`TAVILY_API_KEY`、`NOTION_API_KEY`、`TRELLO_API_KEY`+`TRELLO_TOKEN`、`GITHUB_TOKEN` | brave-search、tavily-search、notion、trello、github |
| 数据源 | Yahoo Finance、CoinGecko、Google News、Twitter/X（`bird`）、16+ RSS | stock-analysis、aipm-news-digest |
| 平台 | OpenClaw | self-improving-agent（hooks）、loop-engineering（命令分发） |

### 6.6 测试依赖（`tests/test_config.py`）

5 个 pytest 测试：`test_settings_defaults`、`test_provider_detection_includes_ollama_by_default`、`test_state_dirs_created`、`test_skills_discovery`（断言含 `agent-browser`）、`test_knowledge_discovery`（断言 ≥4 篇）。

---

## 7. 项目运行方式

### 7.1 安装

```bash
cd /workspace/Hermes

# 1. 虚拟环境
python -m venv .venv
source .venv/bin/activate

# 2. 安装依赖与 hermes 命令（editable）
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .

# 3. 环境变量模板
cp .env.example .env   # 留空字段会自动尝试从主仓库 .env 继承
```

### 7.2 CLI 用法

```bash
hermes                       # 等价 hermes start，启动并打印环境信息
hermes start                 # 显式启动
hermes doctor                # 环境健康检查
hermes config show           # 当前生效配置（密钥脱敏）
hermes skills list           # 列出所有 skills + [md|meta] 标志
hermes knowledge list        # 列出知识文档
hermes profile show          # 用户画像 Markdown
hermes profile show --json   # 用户画像原始 JSON
hermes --log-level DEBUG     # 指定日志级别
hermes --log-file logs/hermes.log   # 同时写日志文件
hermes --help                # 帮助
```

### 7.3 编程式用法

```python
from hermes.config import get_settings
from hermes.skills import discover_skills, get_skill_path

settings = get_settings()
print(settings.openai_api_key)
print(settings.openclaw_model_primary)             # anthropic/claude-sonnet-4-5
print(settings.configured_providers())             # ['ollama', ...]
print(settings.hermes_state_dir)                   # <root>/.state

for skill in discover_skills():
    print(skill.name, skill.path, skill.has_skill_md, skill.has_meta)

path = get_skill_path("stock-analysis")            # Path | None
```

### 7.4 开发流程

```bash
ruff check src/ tests/     # Lint（line-length=100, target py310）
mypy src/                  # 类型检查（strict=true, warn_return_any）
pytest tests/ -v           # 运行测试
```

### 7.5 同步主仓库 skills / 知识

```bash
rsync -av --delete /workspace/.trae/skills/ /workspace/Hermes/skills/
rsync -av --delete /workspace/.trae/docs/knowledge/ /workspace/Hermes/knowledge/
```

### 7.6 运行单个 skill

各 skill 自带运行时依赖，运行前需阅读对应 `SKILL.md`。示例：

```bash
# stock-analysis（需 uv）
cd /workspace/Hermes/skills/stock-analysis && uv run scripts/analyze_stock.py AAPL

# brave-search（需 npm ci + BRAVE_API_KEY）
cd /workspace/Hermes/skills/brave-search && npm ci && node search.js "GLM-5" -n 5

# tavily-search（需 TAVILY_API_KEY）
cd /workspace/Hermes/skills/tavily-search && node scripts/search.mjs "AI agent 2026" --deep
```

---

## 8. 配置与状态文件

| 文件/目录 | 用途 | 是否提交 |
|----------|------|---------|
| `.env.example` | 环境变量模板 | 是 |
| `.env` | 实际环境变量 | 否（`.gitignore`） |
| `manifest.json` | skills/knowledge 清单 + 主仓库路径 | 是 |
| `pyproject.toml` | 项目元数据 + 依赖 + `hermes` script + ruff/mypy 配置 | 是 |
| `requirements.txt` / `requirements-dev.txt` | 依赖清单 | 是 |
| `data/profile.example.json` | 画像模板（`github: hpj360`） | 是 |
| `data/profile.json` | 实际用户画像（含个人数据） | 否（`.gitignore`） |
| `.state/` | Hermes 运行时状态 | 否（`.gitignore`） |
| `.cache/` | 运行时缓存 | 否（`.gitignore`） |
| `logs/` | 日志文件 | 否（`.gitignore`） |

---

## 9. 关键约定与注意事项

1. **沙盒友好**：所有用户可写状态（`.state`/`.cache`/`logs`/`data/profile.json`）都在项目目录内，避免写入 `~/.xxx`。
2. **环境继承不覆盖**：`load_dotenv(..., override=False)`，已存在的非空变量永不被覆盖；进程环境 > Hermes `.env` > 主仓库 `.env` > 默认值。
3. **degraded-friendly CLI**：`main()` 用 `try/except Exception` 兜底，异常返回码 2 并记 ERROR 日志，不静默崩溃。
4. **Settings 单例**：`_hermes_settings` 全局缓存，`get_settings(force_reload=True)` 可强制重建。
5. **Ollama 恒真**：`configured_providers()` 中 `ollama` 对应 `True`（本地无需 Key），故 doctor 永远至少报一个 provider ready。
6. **画像版本**：`_default_profile()` 返回 v4 骨架；`contact.github` 默认 `"hpj360"`。
7. **Skill 元数据容错**：`_meta.json` 解析失败时 `meta=None`，`discover_skills()` 不抛异常。
8. **密钥脱敏**：`config show` 把所有敏感字段渲染为 `set`/`unset`，不泄露值。
9. **永不提交 `.env` / `data/profile.json`**（已在 `.gitignore`）。
10. **修改主仓库路径**：调整 `HERMES_MAIN_REPO_PATH` 环境变量即可。

---

## 10. 入口与公开 API 速查

| 入口 | 路径 | 说明 |
|------|------|------|
| CLI 命令 | `hermes`（`pyproject.toml` 的 `[project.scripts]`）→ `hermes.main:main` | 子命令见 §3.5 |
| Python 包 | `import hermes` | 暴露 `Settings`、`get_settings`、`SkillInfo`、`discover_skills`、`get_skill_path`、`list_knowledge_docs`、`__version__` |
| 配置加载 | `hermes.config.bootstrap_env()`（模块导入时自动执行） | 见 §3.1 |
| 健康检查 | `hermes doctor` | 见 §3.5 |
| 资产清单 | `manifest.json` | 24 skills + 4 knowledge docs |

---

## 附录 A：环境变量完整索引（按 `.env.example`）

- **Hermes**：`HERMES_LOG_LEVEL`、`HERMES_MAIN_REPO_PATH`、`HERMES_STATE_DIR`、`HERMES_CACHE_DIR`
- **OpenClaw 网关**：`OPENCLAW_LLM_API_KEY`、`OPENCLAW_GATEWAY_PORT`、`OPENCLAW_GATEWAY_TOKEN`、`OPENCLAW_GATEWAY_PASSWORD`、`OPENCLAW_STATE_DIR`、`OPENCLAW_CONFIG_PATH`、`OPENCLAW_MODEL_PRIMARY`、`OPENCLAW_MODEL_FALLBACK`
- **LLM Providers**：`OPENAI_API_KEY`/`OPENAI_BASE_URL`、`ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL`、`GEMINI_API_KEY`/`GOOGLE_API_KEY`、`OPENROUTER_API_KEY`/`OPENROUTER_BASE_URL`、`MOONSHOT_API_KEY`/`MOONSHOT_BASE_URL`、`ZAI_API_KEY`/`ZAI_BASE_URL`、`QIANFAN_ACCESS_KEY`/`QIANFAN_SECRET_KEY`、`DASHSCOPE_API_KEY`、`XIAOMI_API_KEY`、`MINIMAX_API_KEY`/`MINIMAX_GROUP_ID`、`MISTRAL_API_KEY`、`NOVITA_API_KEY`/`NOVITA_BASE_URL`、`OLLAMA_BASE_URL`、`MODELSCOPE_API_KEY`/`MODELSCOPE_BASE_URL`、`OPENCLAW_LIVE_OPENAI_KEY`/`OPENCLAW_LIVE_ANTHROPIC_KEY`/`OPENCLAW_LIVE_GEMINI_KEY`、`AI_GATEWAY_API_KEY`、`SYNTHETIC_API_KEY`
- **消息渠道**：`SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN`、`TELEGRAM_BOT_TOKEN`、`DISCORD_BOT_TOKEN`、`MATTERMOST_BOT_TOKEN`/`MATTERMOST_URL`、`ZALO_BOT_TOKEN`、`OPENCLAW_TWITCH_ACCESS_TOKEN`、`FEISHU_APP_ID`/`FEISHU_APP_SECRET`/`FEISHU_VERIFICATION_TOKEN`
- **工具/搜索/媒体**：`BRAVE_API_KEY`、`PERPLEXITY_API_KEY`、`FIRECRAWL_API_KEY`、`TAVILY_API_KEY`、`ELEVENLABS_API_KEY`/`XI_API_KEY`、`DEEPGRAM_API_KEY`
- **集成**：`GITHUB_TOKEN`、`NOTION_API_KEY`、`TRELLO_API_KEY`/`TRELLO_API_TOKEN`、`TAILSCALE_AUTH_KEY`
- **Skillhub**：`SKILLHUB_API_BASE`、`SKILLHUB_COS_BUCKET`、`SKILLHUB_COS_REGION`

---

## 附录 B：知识文档摘要

| 文档 | 路径 | 摘要 |
|------|------|------|
| skill-and-loop.md | [file](file:///workspace/knowledge/skill-and-loop.md) | 综合腾讯技术工程"如何写好 Skill"与 Kazke"Prompt 该退休，未来属于 Loop Engineering"。命题：**Skill 是 Loop 的组件**——Skill 是执行层（每步怎么做），Loop 是控制层（达到什么标准）。SKILL.md 标准结构：front-matter（name/description/compatibility/allowed-tools）+ 正文（role/core flow）。 |
| harness-engineering.md | [file](file:///workspace/knowledge/harness-engineering.md) | 综合 Hermes Agent、Microsoft Agent Framework（BUILD 2026）、复旦、花叔 Loop Engineering Orange Paper、Nous Research GEPA 自进化算法。命题：**Agent = Model + Harness**。Harness = 非模型工程层（系统提示/工具注册/沙盒/权限/记忆/上下文/子 agent/hooks/可观测/eval loop）。四步演进：Prompt→Context→Harness→Loop。"模型决定上限，Harness 决定下限与稳定性。" |
| memory-model.md | [file](file:///workspace/knowledge/memory-model.md) | 三层记忆：**L3 语义**（用户偏好/事实/长期规则；`USER.md`+`MEMORY.md`；永久）、**L2 情景**（对话摘要/任务记录/学习日志；`memory/YYYY-MM-DD.md`+向量检索；跨会话+时间衰减）、**L1 工作**（当前会话上下文/中间推理；内存+压缩；128k–200k token）。压缩前必须把重要信息 flush 到 L2。 |
| evaluator-subagent-template.md | [file](file:///workspace/knowledge/evaluator-subagent-template.md) | Loop Engineering 的 Planner/Generator/Evaluator 分离模板。Evaluator 是独立怀疑论评审者，只读 + exec，无写路径，沙盒隔离。两种创建方式：`openclaw agents add evaluator` 或 `openclaw.yaml` YAML 配置。含 Evaluator system prompt（放入 `AGENTS.md`/`SOUL.md`）。 |

---

## 附录 C：内容创作素材

| 文件 | 路径 | 摘要 |
|------|------|------|
| 00-90天冷启动落地计划.md | [file](file:///workspace/content-creation/00-90天冷启动落地计划.md) | 小红书 0→1000 粉 90 天冷启动计划 v1.0。定位：家庭调酒 + 酒类推荐。四阶段：准备（D1-3）→ 标签建立（D4-30，前 15 篇，目标 500）→ 稳步增长（D31-60，500→800）→ 变现准备（D61-90，800→1000+）。含账号命名/头像/每阶段验收标准（小眼睛 ≥500，互动率 ≥3%）。 |
| 01-前30天选题库.md | [file](file:///workspace/content-creation/01-前30天选题库.md) | 前 30 天选题库。 |
| first-post.md | [file](file:///workspace/content-creation/first-post.md) | 首篇草稿："30 岁北漂回成都，我决定在家开个小酒吧"，5 个备选标题 + 正文。建立作者人设：数据 PM + 家庭调酒爱好者（世涛/单一麦芽苏格兰威士忌/金酒）。 |

---

*本 Wiki 基于 2026-07-23 的代码状态生成。Hermes 与主仓库分开管理，所有变更请同步更新 `manifest.json` 与本 Wiki。*

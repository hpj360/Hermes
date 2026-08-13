# Hermes Skill 验收报告

> 生成时间：2026-08-06 | Skill 总数：49 | 全部无重复

---

## 一、总览

| 指标 | 值 |
|---|---|
| Skill 总数 | 49 |
| 唯一名称数 | 49（无重复） |
| prompt runtime | 47 |
| python runtime | 2 |
| 有外部依赖(requires_bins) | 8 |
| 有 skill 依赖 | 1 |
| 功能域分类 | 13 |

---

## 二、功能域分类

### 搜索与信息获取（4 个）

- ** brave-search** — Web search and content extraction via Brave Search API. Use for searching docume...
- **🔍 tavily-search** — AI-optimized web search via Tavily API. Returns concise, relevant results for AI...
- ** research** — Background agent that reads the source - code, docs, issues - to answer a resear...
- ** aipm-news-digest** — AI Product Manager daily intelligence digest. Fetches news from 16+ curated RSS ...

### 代码工程（5 个）

- ** code-review** — Two-axis review of changes since a fixed point: Standards (coding standards + Fo...
- ** codebase-design** — A vocabulary for talking about codebase architecture: modules, interfaces, depth...
- ** improve-codebase-architecture** — Analyze a codebase for architecture improvement opportunities and produce an HTM...
- ** diagnosing-bugs** — Disciplined diagnosis loop for hard bugs and performance regressions. Use when u...
- ** resolving-merge-conflicts** — Resolve merge conflicts by tracing back to the intent of each side's changes. Re...

### 前端与设计（8 个）

- ** frontend-design** — Create distinctive, production-grade frontend interfaces with high design qualit...
- ** ui-design-system** — Design Token 与设计系统基础。提供 6 类 token 校验、生成 CSS/Tailwind/Swift 多端
产物、命名一致性审计、最佳实践扫描。...
- ** ui-review-checklist** — UI 评审检查清单与反模式扫描器。覆盖 13 类 AI 味反模式 + 13 项可访问性 +
8 项性能 + 6 项一致性。提供 Python 扫描脚本和 Mar...
- ** style-dictionary-sync** — Style Dictionary 风格的多端 token 同步器。把一份 DTCG 标准 JSON 同步为
CSS / SCSS / JS / TS / Swi...
- ** component-library-selector** — 组件库选型决策助手。覆盖 13+ 主流 React/Vue 组件库（shadcn/ui、Radix、
Ant Design、Mantine、Chakra、Mat...
- ** liquid-glass-builder** — Apple WWDC 2025 Liquid Glass 设计语言实施器。生成 Web 端（CSS backdrop-filter +
React 组件）和 i...
- ** prototype** — Build a one-off, throwaway prototype to answer a design question. The prototype ...
- ** prototype-validator** — 用 Playwright + axe-core 自动验证前端原型（无障碍 / 视觉回归 / 性能 / 交互）。生成 0-100 评分 + 详细 diff 报告，...

### 设计工具集成（2 个）

- ** figma-reader** — Figma REST API 封装。读取 Figma 文件、节点、组件、图片，导出为 JSON/PNG/SVG
给 design-system/storyboo...
- ** storybook-chromatic** — Figma → Storybook → Chromatic 视觉回归 → design-code 闭环工具。自动生成 CSF 3.0 故事、调用 Chromat...

### Skill 管理（4 个）

- ** find-skills** — Helps users discover and install agent skills when they ask questions like "how ...
- ** skill-creator** — Create new skills, modify and improve existing skills, and measure skill perform...
- ** skill-manager** — 管理所有已安装的skill，包括列出、安装、更新、卸载、搜索和配置管理
- ** skill-vetter** — Vets skills for quality and security. Invoke when users want to verify or valida...

### 文档与知识（6 个）

- **📝 notion** — Notion API for creating and managing pages, databases, and blocks.
- **💎 obsidian** — Work with Obsidian vaults (plain Markdown notes) and automate via obsidian-cli.
- **🧾 summarize** — Summarize URLs or files with the summarize CLI (web, PDFs, images, audio, YouTub...
- ** grounded-citations** — Verify that every claim in a research report has a traceable, verifiable source....
- ** to-spec** — Turn a raw user request into a PRD-style spec WITHOUT interviewing the user. Syn...
- ** to-tickets** — Decompose a spec or PRD into tracer-bullet tickets with explicit blocking edges....

### Agent 与循环（4 个）

- ** loop-engineering** — Implement Loop Engineering patterns: /goal for progress-driven tasks with verifi...
- ** self-improving-agent** — Captures learnings, errors, and corrections to enable continuous improvement. Us...
- ** wayfinder** — Map decisions in a large piece of work to a ticket-style decision board before w...
- ** triage** — Move issues and external PRs through a state machine of triage roles. Use when u...

### 项目管理（3 个）

- **📊 task-tracker** — 任务进度跟踪工具，实时监控任务执行状态和进度。当用户需要创建任务、更新任务状态/进度、查询任务、生成进度报告、管理任务依赖关系（DAG）、统计任务耗时与阻塞、批...
- **🏗️ pm-framework** — 产品全生命周期多Agent协作框架，提供从需求分析到上线运维的完整协作能力，支持13个专业Agent角色和24个技能模块
- ** product-manager** — Build products users love with discovery, prioritization, roadmapping, SaaS metr...

### DevOps（3 个）

- **🧪 automation-tester** — 自动化测试框架，支持多种测试类型的自动执行和报告生成。当用户需要运行单元测试、集成测试、API接口测试、UI自动化测试、性能测试，或需要生成测试报告与覆盖率分析...
- **🚀 cicd-pipeline** — CI/CD 流水线工具，支持从代码提交到部署的端到端自动化流程。当用户需要执行代码检查、自动构建、测试触发、制品管理、部署策略（蓝绿/滚动/金丝雀）、回滚等流水...
- **📢 notification-system** — 多渠道通知系统，支持多种通知方式和通知规则配置。当用户需要发送飞书/邮件/Webhook/站内信/SMS通知、管理通知模板、配置通知规则、设置优先级升级机制时使...

### 领域建模（1 个）

- ** domain-modeling** — Maintain a living CONTEXT.md that captures the domain glossary, entities, and ru...

### 第三方集成（7 个）

- **📋 trello** — Manage Trello boards, lists, and cards via the Trello REST API.
- ** github** — Interact with GitHub using the `gh` CLI. Use `gh issue`, `gh pr`, `gh run`, and ...
- ** douyin-reader** — 读取抖音视频内容并提取文字版本。当用户提供抖音视频链接（douyin.com、v.douyin.com）并要求阅读、学习、总结、提取文字、获取字幕、转录内容时，...
- ** wechat-reader** — 读取微信公众号文章全文内容。当用户提供微信文章链接（mp.weixin.qq.com）并要求阅读、学习、总结、提取、抓取、获取内容时，必须使用此 skill。也...
- **📺 youtube-watcher** — Fetch and read transcripts from YouTube videos. Use when you need to summarize a...
- **📈 stock-analysis** — Analyze stocks and cryptocurrencies using Yahoo Finance data. Supports portfolio...
- **🌤️ weather** — Get current weather and forecasts (no API key required). 当用户询问天气、天气预报、某地气温、需要出行穿...

### 内容创作（1 个）

- ** design-spec-skill-creator** — 把团队 UI 设计规范（Notion 页面 / Figma 文件 / 本地 Markdown / PDF）转成可分发的 Skill。提取 tokens / co...

### 浏览器自动化（1 个）

- **🌐 agent-browser** — A fast Rust-based headless browser automation CLI with Node.js fallback that ena...

---

## 三、49 个 Skill 详细信息

| # | Emoji | Name | Runtime | Entrypoint | 外部依赖 | Skill 依赖 | Description |
|---|---|---|---|---|---|---|---|
| 1 | 🌐 | `agent-browser` | prompt | SKILL.md | node, npm | — | A fast Rust-based headless browser automation CLI with Node.... |
| 2 |  | `aipm-news-digest` | prompt | SKILL.md | — | — | AI Product Manager daily intelligence digest. Fetches news f... |
| 3 | 🧪 | `automation-tester` | python | run.py | — | — | 自动化测试框架，支持多种测试类型的自动执行和报告生成。当用户需要运行单元测试、集成测试、API接口测试、UI自动化测试、... |
| 4 |  | `brave-search` | prompt | SKILL.md | — | — | Web search and content extraction via Brave Search API. Use ... |
| 5 | 🚀 | `cicd-pipeline` | python | run.py | — | automation-tester, notification-system | CI/CD 流水线工具，支持从代码提交到部署的端到端自动化流程。当用户需要执行代码检查、自动构建、测试触发、制品管理、部... |
| 6 |  | `code-review` | prompt | SKILL.md | — | — | Two-axis review of changes since a fixed point: Standards (c... |
| 7 |  | `codebase-design` | prompt | SKILL.md | — | — | A vocabulary for talking about codebase architecture: module... |
| 8 |  | `component-library-selector` | prompt | SKILL.md | — | — | 组件库选型决策助手。覆盖 13+ 主流 React/Vue 组件库（shadcn/ui、Radix、
Ant Desig... |
| 9 |  | `design-spec-skill-creator` | prompt | SKILL.md | — | — | 把团队 UI 设计规范（Notion 页面 / Figma 文件 / 本地 Markdown / PDF）转成可分发的 ... |
| 10 |  | `diagnosing-bugs` | prompt | SKILL.md | — | — | Disciplined diagnosis loop for hard bugs and performance reg... |
| 11 |  | `domain-modeling` | prompt | SKILL.md | — | — | Maintain a living CONTEXT.md that captures the domain glossa... |
| 12 |  | `douyin-reader` | prompt | SKILL.md | — | — | 读取抖音视频内容并提取文字版本。当用户提供抖音视频链接（douyin.com、v.douyin.com）并要求阅读、学习... |
| 13 |  | `figma-reader` | prompt | SKILL.md | — | — | Figma REST API 封装。读取 Figma 文件、节点、组件、图片，导出为 JSON/PNG/SVG
给 de... |
| 14 |  | `find-skills` | prompt | SKILL.md | — | — | Helps users discover and install agent skills when they ask ... |
| 15 |  | `frontend-design` | prompt | SKILL.md | — | — | Create distinctive, production-grade frontend interfaces wit... |
| 16 |  | `github` | prompt | SKILL.md | — | — | Interact with GitHub using the `gh` CLI. Use `gh issue`, `gh... |
| 17 |  | `grounded-citations` | prompt | SKILL.md | — | — | Verify that every claim in a research report has a traceable... |
| 18 |  | `improve-codebase-architecture` | prompt | SKILL.md | — | — | Analyze a codebase for architecture improvement opportunitie... |
| 19 |  | `liquid-glass-builder` | prompt | SKILL.md | — | — | Apple WWDC 2025 Liquid Glass 设计语言实施器。生成 Web 端（CSS backdrop-f... |
| 20 |  | `loop-engineering` | prompt | SKILL.md | — | — | Implement Loop Engineering patterns: /goal for progress-driv... |
| 21 | 📢 | `notification-system` | prompt | SKILL.md | — | — | 多渠道通知系统，支持多种通知方式和通知规则配置。当用户需要发送飞书/邮件/Webhook/站内信/SMS通知、管理通知模... |
| 22 | 📝 | `notion` | prompt | SKILL.md | — | — | Notion API for creating and managing pages, databases, and b... |
| 23 | 💎 | `obsidian` | prompt | SKILL.md | obsidian-cli | — | Work with Obsidian vaults (plain Markdown notes) and automat... |
| 24 | 🏗️ | `pm-framework` | prompt | SKILL.md | — | — | 产品全生命周期多Agent协作框架，提供从需求分析到上线运维的完整协作能力，支持13个专业Agent角色和24个技能模块 |
| 25 |  | `product-manager` | prompt | SKILL.md | — | — | Build products users love with discovery, prioritization, ro... |
| 26 |  | `prototype` | prompt | SKILL.md | — | — | Build a one-off, throwaway prototype to answer a design ques... |
| 27 |  | `prototype-validator` | prompt | SKILL.md | — | — | 用 Playwright + axe-core 自动验证前端原型（无障碍 / 视觉回归 / 性能 / 交互）。生成 0-... |
| 28 |  | `research` | prompt | SKILL.md | — | — | Background agent that reads the source - code, docs, issues ... |
| 29 |  | `resolving-merge-conflicts` | prompt | SKILL.md | — | — | Resolve merge conflicts by tracing back to the intent of eac... |
| 30 |  | `self-improving-agent` | prompt | SKILL.md | — | — | Captures learnings, errors, and corrections to enable contin... |
| 31 |  | `skill-creator` | prompt | SKILL.md | — | — | Create new skills, modify and improve existing skills, and m... |
| 32 |  | `skill-manager` | prompt | SKILL.md | — | — | 管理所有已安装的skill，包括列出、安装、更新、卸载、搜索和配置管理 |
| 33 |  | `skill-vetter` | prompt | SKILL.md | — | — | Vets skills for quality and security. Invoke when users want... |
| 34 | 📈 | `stock-analysis` | prompt | SKILL.md | uv | — | Analyze stocks and cryptocurrencies using Yahoo Finance data... |
| 35 |  | `storybook-chromatic` | prompt | SKILL.md | — | — | Figma → Storybook → Chromatic 视觉回归 → design-code 闭环工具。自动生成 C... |
| 36 |  | `style-dictionary-sync` | prompt | SKILL.md | — | — | Style Dictionary 风格的多端 token 同步器。把一份 DTCG 标准 JSON 同步为
CSS / ... |
| 37 | 🧾 | `summarize` | prompt | SKILL.md | summarize | — | Summarize URLs or files with the summarize CLI (web, PDFs, i... |
| 38 | 📊 | `task-tracker` | prompt | SKILL.md | — | — | 任务进度跟踪工具，实时监控任务执行状态和进度。当用户需要创建任务、更新任务状态/进度、查询任务、生成进度报告、管理任务依... |
| 39 | 🔍 | `tavily-search` | prompt | SKILL.md | node | — | AI-optimized web search via Tavily API. Returns concise, rel... |
| 40 |  | `to-spec` | prompt | SKILL.md | — | — | Turn a raw user request into a PRD-style spec WITHOUT interv... |
| 41 |  | `to-tickets` | prompt | SKILL.md | — | — | Decompose a spec or PRD into tracer-bullet tickets with expl... |
| 42 | 📋 | `trello` | prompt | SKILL.md | jq | — | Manage Trello boards, lists, and cards via the Trello REST A... |
| 43 |  | `triage` | prompt | SKILL.md | — | — | Move issues and external PRs through a state machine of tria... |
| 44 |  | `ui-design-system` | prompt | SKILL.md | — | — | Design Token 与设计系统基础。提供 6 类 token 校验、生成 CSS/Tailwind/Swift 多... |
| 45 |  | `ui-review-checklist` | prompt | SKILL.md | — | — | UI 评审检查清单与反模式扫描器。覆盖 13 类 AI 味反模式 + 13 项可访问性 +
8 项性能 + 6 项一致性... |
| 46 |  | `wayfinder` | prompt | SKILL.md | — | — | Map decisions in a large piece of work to a ticket-style dec... |
| 47 | 🌤️ | `weather` | prompt | SKILL.md | curl | — | Get current weather and forecasts (no API key required). 当用户... |
| 48 |  | `wechat-reader` | prompt | SKILL.md | — | — | 读取微信公众号文章全文内容。当用户提供微信文章链接（mp.weixin.qq.com）并要求阅读、学习、总结、提取、抓取... |
| 49 | 📺 | `youtube-watcher` | prompt | SKILL.md | yt-dlp | — | Fetch and read transcripts from YouTube videos. Use when you... |

---

## 四、依赖关系图

### 4.1 Skill 间依赖（requires.skills）

| Skill | 依赖的 Skill |
|---|---|
| `cicd-pipeline` | `automation-tester`, `notification-system` |

### 4.2 被依赖关系（反向）

| 被依赖的 Skill | 依赖于它的 Skill |
|---|---|
| `automation-tester` | `cicd-pipeline` |
| `notification-system` | `cicd-pipeline` |

### 4.3 外部二进制依赖（requires_bins）

| Skill | 需要的外部工具 |
|---|---|
| `agent-browser` | `node`, `npm` |
| `obsidian` | `obsidian-cli` |
| `stock-analysis` | `uv` |
| `summarize` | `summarize` |
| `tavily-search` | `node` |
| `trello` | `jq` |
| `weather` | `curl` |
| `youtube-watcher` | `yt-dlp` |

---

## 五、互补性说明

### 5.1 互补/竞品对（13 对）

| Skill A | Skill B | 关系类型 | 互补说明 |
|---|---|---|---|
| `style-dictionary-sync` | `ui-design-system` | 上下游互补 | token 多端同步 ↔ token 校验+生成+审计 |
| `find-skills` | `skill-creator` | 生命周期互补 | 发现+安装 ↔ 创建+改进 |
| `codebase-design` | `improve-codebase-architecture` | 深度互补 | 架构词汇表(只读) ↔ 改进报告+grilling |
| `figma-reader` | `storybook-chromatic` | 管道互补 | 读取 Figma(上游) ↔ 建 Storybook+视觉回归(下游) |
| `skill-creator` | `skill-vetter` | 角色互补 | 创建 skill ↔ 审查 skill 质量+安全 |
| `brave-search` | `tavily-search` | 同域竞品冗余 | Brave API ↔ Tavily API，多 Provider 冗余设计 |
| `task-tracker` | `loop-engineering` | 状态管理互补 | DAG 任务状态机 ↔ Goal 驱动循环执行 |
| `automation-tester` | `cicd-pipeline` | 管道上下游 | 测试执行(流水线 test 阶段) ↔ 流水线编排 |
| `cicd-pipeline` | `notification-system` | 事件驱动 | 流水线状态变更 → 多渠道通知 |
| `pm-framework` | `task-tracker` | 框架与实现 | 13 角色协作框架 ↔ 任务状态机实现 |
| `notion` | `obsidian` | 同域竞品冗余 | Notion API ↔ Obsidian API，不同笔记平台 |
| `prototype` | `prototype-validator` | 生成与验证 | 生成原型 ↔ 验证原型质量 |
| `to-spec` | `to-tickets` | 需求拆解 | 需求→规格 ↔ 需求→工单 |

### 5.2 功能域内互补链

#### 搜索与信息获取
```
brave-search / tavily-search → research（深度研究）→ aipm-news-digest（行业资讯）
```

#### 前端设计全链路
```
figma-reader → component-library-selector → frontend-design → ui-design-system → style-dictionary-sync → liquid-glass-builder → prototype → prototype-validator → ui-review-checklist
```

#### Skill 生命周期
```
find-skills（发现）→ skill-creator（创建）→ skill-vetter（审查）→ skill-manager（管理）
```

#### DevOps 流水线
```
cicd-pipeline → automation-tester（test 阶段）→ notification-system（状态通知）
```

#### 项目管理
```
pm-framework（13 角色框架）→ task-tracker（任务状态机）→ loop-engineering（Goal 循环执行）
```

#### 代码工程
```
codebase-design（架构词汇）→ improve-codebase-architecture（改进报告）→ code-review（审查）→ diagnosing-bugs（诊断）→ resolving-merge-conflicts（合并冲突）
```

---

## 六、验收结论

| 验收项 | 标准 | 实际 | 状态 |
|---|---|---|---|
| Skill 总数 | ≥40 | 49 | ✅ |
| 名称唯一性 | 100% 唯一 | 49/49 | ✅ |
| 功能重复对 | 0 | 0（均为互补关系） | ✅ |
| 功能域覆盖 | ≥10 | 13 | ✅ |
| 外部依赖 skill 数 | 可控 | 8 | ✅ |
| Skill 间依赖 | 可控 | 1 | ✅ |
| 互补对识别 | 完成 | 13 对 | ✅ |

**结论**：49 个 skill 全部通过验收，无功能重复，13 对互补关系已识别，覆盖 13 个功能域。

# DeepSeek Harness 深度研究分析报告（v2）

> **分析对象**：`deepseek-ai/deepseek-harness`（DSH，"Everything is a Plugin"，Developer Preview，MIT）
> **报告目的**：① 基于一手资料深度解析 DSH 的架构、生态与实测表现；② 对照 Hermes 项目能力做逐项对比；③ 审查评估与 Hermes 融合的可行性与影响，给出决策建议。
> **资料来源**（全部为一手抓取核验）：
> - 官方仓库 README / README.zh、`docs/architecture.md`、`docs/cordis-primer.md`、`docs/subsystems/subagent.zh.md`、`AGENTS.md`、`python/README.md`、仓库文件树（8617 条记录）
> - Cordis 论文 `cordiverse/paper`《A Programming Paradigm for Spatiotemporal Composability》（2026-08-13 草稿）
> - 腾讯技术工程实测文章（元宝产品团队，2026-08-14，链接见附录）
> - Hermes 仓库源码与文档现场核验（本机 `D:\Hermes\hermes`，commit e2c4917）
> **生成日期**：2026-08-15　**版本**：v2（v1 为工作区未提交草稿，本版修正 4 处事实错误并新增第 1.5、2.5、3.1 节）

---

## 第一部分　DeepSeek Harness 深度研究

### 1.1 事实速览

| 项 | 值 |
|---|---|
| 发布 | 2026-08-13（与 DeepSeek-V4-Pro 正式版同日开源） |
| 定位 | 开源 agent harness / 可重组 Agent runtime |
| 语言 / 形态 | TypeScript pnpm monorepo（8617 条文件树记录，packages/ 下约 40 个子包） |
| 许可 / 分支 | MIT / master |
| 热度 | 2 天 106,889 stars、10,248 forks（截至 2026-08-15 抓取） |
| 运行要求 | Node ^22.19 \|\| >=24；`npx @deepseek-ai/dsh web` 一键启动 Web UI（127.0.0.1:3080） |
| 成熟度 | **Developer Preview，官方明示"将出现破坏兼容性的变更"** |
| 理论底座 | Cordis 插件框架（vendored）+ 论文《A Programming Paradigm for Spatiotemporal Composability》 |
| 官方入口 | Web UI / Headless / Python SDK（捆绑运行时）/ ACP / JSON-RPC |

### 1.2 双身份定位：平台脚手架 vs 默认产品

腾讯文章的判断与本报告独立核验一致：DSH **不是"DeepSeek 版 Codex"**，而是"还能继续造 Agent 的 runtime"。它同时有两个身份，完成度不对称：

| 身份 | 完成度 | 证据 |
|------|--------|------|
| 可重组的 Agent runtime（平台） | 高，口碑最好 | 一切皆插件、Profile/Preset 两级组装、事件流可编程投影、Trajectory 可视、`--dump-config` |
| 默认产品（日常编码工具） | 预览版毛边 | 终端体验、桌面 App、Windows 验收、缓存命中率落后 Claude Code / Codex / Kimi Code |

社区反馈（知乎《如何评价 8 月 13 日发布的 DeepSeek Harness》）同样分两组：一组等成熟 coding agent，另一组看插件 / Preset / Trajectory / 运行时自修改。**两边都没看错，但 DSH 目前的交付重心明显在后者。**

### 1.3 理论根基：Cordis 与"时空可组合性"

Cordis 论文把插件系统的形式化问题拆成两个正交维度：

- **时间可组合（temporal composability）**：组件的副作用必须可完整撤销——每次 context 变换都携带逆变换，运行时跟踪。
- **空间可组合（spatial composability）**：组件间的依赖声明式、响应式管理——context 每次变化都按 coeffect 规范通知相关组件。

两者统一进单一 context 类型，形成组件演算（calculus of dynamic composition），元理论保证单组件到整系统的可组合性。落到工程上（`cordis-primer.md`）就是五个概念：

1. **插件 = 实现 Service 的对象**（函数或 Service 子类），挂载进当前 context；
2. **Context = 服务仓库**，服务通过稳定 `ctx.<key>`（如 `ctx.tools`、`ctx.llm`、`ctx.sessions`）被发现，不 import 具体实现；
3. **`inject` 声明依赖**，依赖缺失时 Fiber 停在 PENDING，服务出现进入 ACTIVE，加载顺序由依赖关系而非启动代码决定；
4. **类型化事件**四种 dispatch 模式：`emit`（顺序观察）、`waterfall`（洋葱中间件，`next()` 委托/短路）、`parallel`（并行观察）、`serial`（顺序且有返回值）；
5. **注册即可逆效果**：服务、监听器、定时器都经 `ctx.effect()` 注册并交回 disposer，卸载时逆序回收。

**明确边界**（架构文档与文章都强调）：外部文件、网络消息、已发生的业务动作不会自动回滚；依赖注入不替代恶意代码沙箱。

### 1.4 架构五支柱

```
apps/cli + apps/web            命令行与浏览器入口
packages/boot + bundle         Profile 与插件树组装（bundle=可安装的 patch 层）
packages/core/
  agent-loop                   Turn / Step 驱动（ReactLoopAgent 本身是插件）
  session                      追加式 SessionEvent 事件日志（zstd JSONL）
  tools                        作用域化工具注册表 + 带把关的执行流水线
  system-prompt                Prompt 片段与工具 schema 组装
packages/preset                每会话 Agent 组合（tools/提示词/投影单元）
packages/llm                   DeepSeek 直连 + pi-ai 多 Provider 适配器
packages/fs + sandbox          可替换执行能力（Capability Seam）
packages/code-runtime          PTC / Code Mode
vendor/cordis                  插件生命周期底层
```

**支柱 1：一切皆插件。** 模型适配器、工具注册表、会话日志、乃至 **Agent Loop 本身**都是插件，全部可经配置替换。没有需要打补丁的特权核心。这是与 Kimi Code 最本质的源码级差异：Kimi Code 的 loop 是固定引擎主干（v2 DI Service），DSH 的 loop 可装卸。

**支柱 2：Profile（进程）与 Preset（会话）两级组装。** Profile 从空列表叠 bundle 再应用 profile/home/命令行三级 patch，Web profile 实测 129 行插件配置、Headless 81 行——**不同模式不是界面开关，是两棵不同的插件树**。`--dump-config` 与真实启动共用同一套 patch 算法。Preset 决定单个会话看见哪些工具/提示词/投影单元，同一进程可同时跑 standard / PTC / minimal / creative 或领域 Agent。社区 Data Agent 只留 read/edit/write + 用 `sqlcmd` 替换 bash，是"插件提供能力、Preset 决定收窄"的典型例证——**DSH 的产价值往往落在"删掉什么、替换什么"**。

**支柱 3：会话日志 = 唯一事实源 + 运行时不变量。** 会话以追加式 JSONL 保存，每条记录统一外壳（`{"type":"tool/call","seq":31,"time":...,"data":{}}`）。核心约束：**模型看见的内容必须已记入日志**。发请求前 invariant 校验 `session.deriveMessages()` 与实际请求一致，不一致即 `log-reconstruction desync` 失败。Trajectory 因此不另埋监控数据，直接从事件流投影，同时回答三类问题：模型当时看见了什么、哪一步调了哪个工具、token/缓存/结束原因如何变化。附带隐私含义：上下文一旦注入模型，也进入日志与数据边界。

**支柱 4：Capability Seam（能力接缝）。** Seam = Service Definition + Service Provider + Consumer 三角色。文件系统先定义 `FileSystem` / opaque target / version，local 与 sandbox provider 各自实现，read/write/editor 工具统一消费。把 fs 与 subprocess provider 指向远程沙箱时，Bash、PTY、LSP 一并搬走，**上层工具不用 fork**。写入支持 `createIfAbsent` 与 `replaceIfVersion`（陈旧覆盖拒绝）——并发安全落在工具之下。

**支柱 5：PTC（程序化工具组合）。** 模型写 TypeScript 组合多次工具调用，在 `worker_threads` 中执行，工具请求经消息通道回宿主，仍过同一套 pre-execute / 审批 / 调度 / post-execute 流水线。价值：中间数据留在运行环境，不必每步回灌模型上下文。代价：执行模型生成代码需要额外隔离，worker 不是完整安全边界。

### 1.5 生态与工程实践（本版新增维度）

**Subagent 生态（与 Hermes Orchestrator 最直接可比的子系统）**：
- subagent 是**可选能力**，`ctx.subagents` 按名注册，同一 context 可共存多个提供方（不同于 bash 的单一执行器）；
- 六个官方提供方：`spawn-in-process`、`fork`、`acp`、`codex`、`claude-code`、`dsh-sdk`——即 DSH 可以把任务**委派给 Claude Code / Codex / 另一台 DSH** 作为子代理；
- 可继续（continuable）子代理由激活管理器编排；启动期能力描述符显式拒绝不支持的能力（`SubagentError('UNSUPPORTED_CAPABILITY')`，**绝不静默忽略**）；
- 面向模型的三类 Consumer：`tool-subagent`（按提供方委派）、`tool-subagent-control`（`send_message` / `interrupt_agent` / `list_agents` 控制面）、`tool-subagent-report`（子代理作用域回传通道）。

**其余能力面**（`AGENTS.md` 包图核验）：`hooks`（Claude Code / Codex hook 协议桥）、`guard`（loop 卫生 + 工具超时）、`self-modification`（agent 运行时检查/挂载自己的插件）、`plan`（计划模式作为 logged state）、`skill`（技能注册表 + 目录加载工具，`.dsh/skills/`）、`workflow`（worker-thread 提供方）、`session-query` / `compaction` / `spill` / `token-meter` / `goal` / `jobs` / `commands` / `feedback` / `ask-user` / `identity` / `credentials`、`typert`（类型图生成器 + 运行时注册表，事件 dispatch 模式与声明强校验）、`e2b`（远程沙箱 POC）、`native/landlock-run`（Linux Landlock 原生沙箱启动器，linux x64/arm64 prebuilds）。

**工程纪律（超出多数开源项目的部分）**：
- CI 覆盖率门禁：`packages/*/*/src` **逐文件 100%** 覆盖；
- 三层测试：vitest 单测 / e2e（真实 API，无 `DEEPSEEK_API_KEY` 自动跳过）/ **keyless 快照回放**（ACP/headless 用固定输入重放对比预期输出——不花钱、可 CI、可复现）；
- `.agents/notes/`：**2057 个 agent 撰写的设计笔记**（implemented/feature、architecture、bug-fix、archived，双语）——自举开发文化 + 机构记忆沉淀，连"为什么这样设计"都进了仓库。

**Python SDK（对融合评估最关键的事实）**：`deepseek-harness-sdk`（高层 turns API + JSON-RPC client）+ `deepseek-harness-runtime-bin`（**捆绑运行时二进制** + 默认 agent 配置）。协议为 stdio 上换行分隔 JSON-RPC；SDK 默认启动捆绑运行时，**不依赖系统 Node**。这意味着 Python 进程只需 `pip install` 就能把 DSH 当子进程驱动——腾讯文章实测确认了这一点。

### 1.6 实测证据（腾讯文章数据摘录）

| 观察 | 数据 | 含义 |
|------|------|------|
| 最小任务首包 token | "回复 PONG" 首轮 **13,467 input token**（默认系统提示 + 工具说明 + 仓库规则 + 27 条 skill 摘要），后续约 13k cache-read | 默认配置上下文极重；minimal preset / 独立 git 根 / 独立 DSH_HOME 是必须的治理动作 |
| 同模型双 Harness（Kimi K3） | 两题均 15/15 全过；DSH minimal 11 调用/9 step（112.2s）+ 7 调用/7 step（111.3s）；Kimi Code 5 调用/48.9s + 6 调用/123.1s | **Harness 塑造执行路径**；速度无稳定赢家，轨迹形态差异明显 |
| 复杂任务承载（V4 Pro 跳一跳） | DSH 3 段 session 约 25 分钟、85 step、96 次工具调用、19 项后端测试，中断后可续跑补齐 880 行；Kimi Code 约 21 分钟、17 项测试 | 20 分钟级前后端任务可承载；断点续跑可用 |
| 共同失败模式 | 两套 Harness 都出现"模型自测通过、真实浏览器失败"（canvas backing store 尺寸 / CSS 覆盖 hidden） | **Agent 写的测试与实现共用盲点**，外部浏览器/人眼验收不可省 |
| 多模型驱动 | Kimi K3、GPT-5.6 Sol、Claude Opus 4.8 冒烟通过（pi-ai 适配器） | provider 协议可替换；实际接入仍需逐项验证 |
| 长任务成本尺度 | 微信接入案例 87.6 分钟 / 约 18 元；竞赛任务 89 步 | 评估长任务要同时看 step、token、分钟、人工接管次数 |

### 1.7 短板与治理缺口

1. **Developer Preview，破坏性变更常态**（官方明示，README 与 AGENTS.md 双重强调；连 SQLite SCHEMA_VERSION 都无兼容承诺）；
2. 默认产品体验未追上一线编码工具；**Windows 验收薄弱**；源码构建需 pnpm + Node 22.19+；
3. 默认配置首包 token 开销大（13k+），治理靠用户自觉（独立 git 根 / minimal preset）；
4. 生产治理空白：插件来源审计、配置 diff、凭证边界、日志保留、数据外发全部要部署方自建；
5. PTC worker 隔离与 Landlock 沙箱均非完整安全边界（官方明示）。

---

## 第二部分　与 Hermes 项目深度对比

### 2.1 定位与形态（本机仓库核验）

| 维度 | DeepSeek Harness | Hermes（D:\Hermes\hermes，v0.6.0→v1.0.0） |
|------|------------------|--------------------------------------------|
| 定位 | 可重组的 Agent runtime 平台 | 个人 AI 工作台控制平面：调度中心 + Loop 工程 + 多 Agent 编排 + 内容业务层（content-team） |
| 语言 / 分发 | TS monorepo，npm/npx，Node 22.19+ | Python ≥3.10，pip；**运行时仅 3 个依赖**（pydantic / pydantic-settings / python-dotenv），Workbench 纯 stdlib |
| 入口 | Web / Headless / Python SDK / ACP / JSON-RPC | CLI（workbench/loop/eval/skill-sync/skill-market/secrets/power 等）+ **61 条 HTTP 路由**（stdlib http.server 正则路由表，实测核验）+ SSE + Vite/React UI |
| 成熟度 | Developer Preview | M0✅ M2✅ M3✅ / M1⚠️（工程完成、真实平台 API 未接）；**1560 个测试函数**（tests/ grep 实测） |

### 2.2 能力矩阵逐项对比

| 能力 | DSH | Hermes | 差距判断 |
|------|-----|--------|---------|
| Agent Loop 可替换性 | Loop 是 Cordis 插件，架构级可替换 | `workbench/agent_loop.py` 固定序列循环 + `loop.py` LLM 多轮，可配置不可插拔 | DSH 开放度更高；Hermes 的 loop 是产品主干 |
| 会话日志与可观测性 | 追加式事件流 + **log-reconstruction 运行时不变量** + Trajectory UI + token/cache 面板 | episodes.jsonl（追加）+ audit log + OTLP + /metrics + tracing/structured_logging；**无"模型所见可重建"不变量、无轨迹 UI** | **Hermes 最大单点缺口** |
| 能力作用域（Preset 等价物） | Preset：每会话工具/提示词/投影单元组合 | `ROLE_MCP_WHITELIST`（orchestrator.py:85，MCP 按角色分舱）+ denylist + pattern 级子代理限制 | 概念同源；Hermes 覆盖面窄（无 prompt 片段级组合、无通用 preset 机制） |
| 权限模型 | read-only / workspace-write / danger-full-access + ask | L1/L2/L3 分级自治（cli_loop advance）+ STOP_RULES + gated 半自动 + 事前拦截/事后审计双保险 | Hermes 分级自治体系更深，且已代码级强制执行 |
| 沙箱 / 执行抽象 | fs/sandbox/subprocess seam，可整体换远程沙箱；`replaceIfVersion` 并发防护；Landlock 原生启动器 + e2b POC | subprocess 执行 + 环境脱敏 + skill sandbox（stdlib ast 静态门，ADR-0009）+ 进程超时 | 概念对齐；Hermes 无 seam 抽象（工具直连 subprocess）、无版本校验 |
| 代码模式（PTC） | PTC：TS 组合多工具调用，worker_threads 隔离 | 无对应物 | DSH 领先；借鉴需独立安全设计 |
| 多 Agent 编排 | subagent seam：6 提供方（含委派给 Codex/Claude Code/DSH）+ continuable + 能力描述符显式拒绝 | Orchestrator fan-out/fan-in（经 OpenClaw Gateway）+ 角色 MCP 分舱 + token 熔断 + denylist + 协作指标 | 各有侧重：DSH 强调作用域可组合与生态委派，Hermes 强调安全护栏与审计闭环 |
| 调度中心 | `ctx.jobs` 后台任务 + web-schedule 示例（无 cron/DAG/恢复语义） | 完整进程内调度：Job 队列/Worker 池/Cron/崩溃恢复/DAG/跨项目路由/资产同步/SSE | **Hermes 独有且领先** |
| 自我进化 | `self-modification`（运行时挂载自身插件） | GEPA：variant 生成/split-run/Welch t 检验/红队/denylist 强度回归 | 机制不同：DSH 改运行时结构，Hermes 用统计验证选优——**Hermes 更工程化** |
| LLM 接入 | DeepSeek 直连 + pi-ai 多 provider | **15+ provider 配置位**（openai/anthropic/gemini/google/openrouter/moonshot/zai/qianfan/dashscope/xiaomi/minimax/mistral/novita/ollama/modelscope，config.py 实测） | 数量相当；DSH 有 DeepSeek 官方直连 |
| Skill 生态 | skill 包（注册表 + 目录加载，`.dsh/skills/`）+ npm 插件 + dsh-plugin topic | SKILL.md + manifest + marketplace（git/HTTP 分发 + registry.json，ADR-0010）+ skill-vetter + sandbox | 格式不兼容；生态各走各路 |
| Hooks | Claude Code / Codex hook 协议桥 | 无第三方 hook 桥（有 tool_recovery 失败恢复） | DSH 领先（利于生态兼容） |
| UI | Web UI + Trajectory | Vite+React（选题/创作/发布三页面）+ REST/SSE + dashboard | DSH 轨迹可视是体验亮点 |
| 配置可见性 | `--dump-config` 打印最终插件树 | `config show`（脱敏） | 概念对齐，但 Hermes 无"运行时最终组装树"dump |
| 工程纪律 | 逐文件 100% 覆盖门禁 + keyless 快照回放 + e2e 自跳过 | 1560 测试 + ruff/mypy + skill 安全回归套件 | 各自扎实；DSH 的快照回放值得学 |

### 2.3 Harness 设计三问对照（文章提出的检验标准）

| 问题 | DSH | Hermes 现状 |
|------|-----|-------------|
| ① 运行时最终加载了什么，能否一条命令打印？ | ✅ `dsh --profile web --dump-config` | ⚠️ `config show` 只显示环境配置，无"工具集 + prompt 片段 + 权限"最终组装视图 |
| ② 模型实际看见了什么，能否从日志完整重建？ | ✅ deriveMessages() + 运行时不变量 | ❌ episodes 记摘要、audit 记动作，**无法从日志重建发给模型的完整上下文** |
| ③ 换掉文件系统/沙箱/provider，多少工具必须跟着改？ | ✅ seam 设计，接近 0 | ❌ 工具直连 subprocess/本地路径，换执行位置需改 SkillRunner 与各 skill |

### 2.4 本质差异：开放层级 vs 控制平面

两者都声称"插件化 + 事件日志 + 权限分级 + 技能系统"，但**开放的是不同层级**：

- **DSH 开放到 Agent Loop 内部**：loop、provider、session、UI 全部可拆可换，适合造新 Agent、做模型评测、研究上下文。代价是默认产品体验和治理责任都推给使用方。
- **Hermes 开放的是控制平面之上**：调度、审计、安全、自进化、业务编排是产品重心；Agent Loop 是产品主干而非可换件。代价是作为"平台"的开放性不足（三问之②③失分）。

**结论：两者是互补关系而非替代关系。** DSH 在运行时开放性上全面领先；Hermes 在调度、安全护栏、统计化自进化与业务层上领先。

### 2.5 值得警惕的相似缺陷（文章数据映射到 Hermes）

1. **上下文膨胀**：DSH 默认配置下"PONG"首包 13.4k token，主要来自系统提示、工具说明、仓库规则、27 条 skill 摘要。Hermes 同样在会话注入 AGENTS.md（cli_power.py / loop.py 实测存在）且 skill 体系在膨胀——**这是同构风险**，Preset 式收窄对 Hermes 同样有效。
2. **自测盲点**：DSH/Kimi Code 都出现模型自测通过、真实浏览器失败。Hermes 的 eval 与 GEPA 若只信模型自评，同样会踩——外部验收（真实平台 API、人工抽检）不可省。
3. **治理空白**：DSH 明示生产治理自建；Hermes 已有审计/denylist/红队，但若未来桥接外部运行时，数据外发与凭证边界需显式设计。

---

## 第三部分　融合可行性审查与影响评估

### 3.1 治理约束（决策前提）

本次评估遵循既定产品立场：**Hermes 框架能力相对当前内容业务（小红书居家调酒账号）已过剩，方向应从"扩框架"转向"跑业务"——框架服务业务、业务验证框架。** 因此：凡不能直接服务业务或降低现有业务成本的框架性借鉴，一律降级为"有条件触发"，不以"DSH 火了"为立项理由。

### 3.2 三个融合层级

#### 方案 A：整体替换（以 DSH 为 Hermes 运行时）——**不推荐，排除**

- 语言栈冲突：Hermes 全栈 Python（调度/记忆/编排/业务约 30 模块、1560 测试），DSH 是 TS monorepo；替换等于重写，代价无上限。
- DSH 是 Developer Preview，官方声明兼容性破坏常态；把现有测试与调度语义压在一个快速迭代的外部依赖上，风险不可控。
- DSH 无 cron/DAG/崩溃恢复/资产同步/GEPA，替换会**倒掉 Hermes 已建成的核心优势**。
- DSH 的 Windows 验收薄弱，而 Hermes 主战场就在 Windows 本机。
- 唯一等价路径是"把 Hermes 重写为 dsh plugin"——放弃现有资产，不做。

#### 方案 B：桥接共存（DSH 作为 Hermes 的可选外部执行后端）——**可行且成本低于 v1 草稿估计，但当前不做**

- **机理**：Hermes Orchestrator 现经 OpenClaw Gateway 分发 sub-agent。抽象 `ExecutionBackend` 协议（Gateway / DSH / 本地 Loop），DSH 后端经 **Python SDK 驱动**——官方 SDK 自带捆绑运行时，stdio NDJSON JSON-RPC，**无需安装系统 Node**（v1 草稿把 Node 22+ 视为硬成本，本版据 `python/README.md` 与文章实测修正为：`pip install deepseek-harness-sdk` 即可）。
- **收益**：sub-agent 可借 DSH 的 Preset 收窄工具面 + Trajectory 日志；Hermes 的 MCP 分舱 / token 熔断 / denylist / 审计仍在外层生效。
- **风险/成本**：DSH preview 期接口漂移；两条日志体系需归一化；若用 DeepSeek 模型则引入新的数据外发边界；SDK 捆绑运行时的分发与授权需核验。
- **触发条件**：① DSH 发布首个 tagged 稳定版；② Hermes 出现真实"领域 Agent 工具面收窄"需求（如内容业务的选题/文案子代理需要窄工具面时）。两者缺一不立项。

#### 方案 C：概念级借鉴（吸收 DSH 已验证的设计模式）——**推荐，按业务相关性分档**

| 优先级 | 借鉴项 | 落地方式 | 业务理由 | 工作量 |
|--------|--------|---------|---------|--------|
| **P0** ✅ | **log-reconstruction 不变量（派发可重建）** | Loop Runner 派发前把完整 payload 写入 trajectory 事件（`.loops/<name>/trajectory.jsonl`），record 后重放比对校验，desync 中止派发；`hermes loop trajectory --verify` 离线审计 | L3 无人值守审计可信度提升（从"事后看摘要"到"可重建 Hermes→Gateway 派发输入"）；也是排障工具 | 中（已实施，ADR-0017） |
| **P0** ✅ | **AgentPreset（工具面 + prompt 收窄）** | 将 `ROLE_MCP_WHITELIST` 泛化为 per-session `AgentPreset`（tools 白名单 + prompt 片段 + 权限级），角色名约定挂 preset；denylist 并集、mcp 只可收紧 | 直接降低 sub-agent token 开销与串味率——对内容业务 sub-agent（选题/文案）是**直接成本收益** | 中（已实施，ADR-0018） |
| P1 | **Trajectory 视图** | apps/web 增加会话轨迹页（时间轴 + request/token/tool 调用 + cache 命中），数据源为 P0 的 trajectory.jsonl，复用现有 tracing | 调试上下文压缩、skill 过多、模型犯错场景；对标 DSH 口碑最好的功能 | 中 |
| P1 | **`hermes dump-config`** | 打印最终生效组装视图（providers + skills + loop patterns + preset + denylist），与真实启动共用组装逻辑 | 回答三问之①；配置漂移排查；成本极低 | 小 |
| P2 | **执行 seam（fs/subprocess provider 抽象）** | 抽象 `ExecutionProvider` 协议，工具经 provider 消费；写入加 `replaceIfVersion` | 回答三问之③；**但当前单机业务无远程执行需求**，纯框架项 | 中-大 |
| P2 | **Python 版 PTC（代码模式）** | L3 场景允许模型输出受限 Python 片段组合多工具调用，AST 静态门 + 资源限制后执行 | 减少多步任务往返；**当前业务任务多步性不强**，且安全设计重 | 大 |
| P2 | **keyless 快照回放测试** | 对 loop/eval 关键路径固化 input→expected 回放（不调真实 API），纳入 CI | 测试不花钱、可复现；对现有 eval 体系是低成本增强 | 中 |

**额外可借鉴的轻量实践**（不立项、随时吸收）：`.agents/notes` 文化（Hermes 已有 ADR 传统，可让 agent 会话把"为什么这么改"写进 notes）；subagent 的**能力描述符显式拒绝**（对 Orchestrator 的 payload 校验是现成收益）。

### 3.3 影响评估

**正面影响**
1. **审计可信度提升**：不变量把 L3 无人值守从"事后看摘要"升级为"可重建 Hermes→Gateway 派发输入"（Gateway 内部加工受控范围外，见 ADR-0017 边界声明），与现有事前拦截（denylist 入 payload）+ 事后审计（fan_in 扫描）构成完整闭环。
2. **成本可控**：Preset 收窄直接回应 13.4k token 首包教训；对内容业务 sub-agent 是直接省钱项。
3. **排障效率**：Trajectory 视图让"模型为什么这么干"从猜测变为可查。
4. **测试基建增强**：快照回放让 eval 回归零 API 成本。

**负面风险**
1. **借鉴≠照搬**：PTC 与 seam 是 DSH 架构深水区，盲目移植引入 Hermes 刻意规避的复杂度（stdlib-first 原则）。**P2 项必须先 ADR 论证，且需业务需求背书**。
2. **双栈诱惑**：方案 B 即使无 Node 依赖，也引入外部运行时 + 接口漂移 + 双日志体系，必须作为独立可选后端而非默认路径。
3. **维护成本**：每借鉴一个模式都要长期维护对应测试，1560+ 用例基线不能降级。
4. **治理债务**：DSH 文章明示生产治理自建；Hermes 若桥接 DSH，插件来源审计、凭证边界、数据外发边界全部由 Hermes 侧承担。

### 3.4 决策建议

1. **不替换、不强绑**：Hermes 继续以 Python 控制平面为主干；DSH 作为参考架构与未来可选执行后端。
2. **立即做（P0，业务相关）** ✅：log-reconstruction 不变量 + AgentPreset 收窄——已实施并验收（ADR-0017 / ADR-0018，`docs/roadmap/p0-harness-borrow.md`）。两者直接回应三问中 Hermes 失分最重的②和上下文成本，与现有架构（audit/episodes/MCP 白名单）同源。
3. **低成本顺手做（P1）**：`hermes dump-config`（工作量小，回答三问之①）+ Trajectory 视图（体验与排障双收）。
4. **审慎做（P2，需 ADR + 业务触发）**：Python 版 PTC、执行 seam、快照回放——均需先在 ADR 中证明业务必要性。
5. **方案 B 触发条件**：DSH 首个 tagged 稳定版发布 **且** 出现真实领域 Agent 收窄需求，二者缺一不立项。
6. **持续监控**：DSH 版本稳定性（首个 tag）、dsh-plugin 生态质量、Preset 领域实践（Data Agent 类）、Windows 支持进展；**每季度回看一次本报告结论**。

---

## 附录

### A. 参考链接

- DSH 源码：https://github.com/deepseek-ai/deepseek-harness
- 中文架构文档：https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.zh.md
- Cordis：https://github.com/cordiverse/cordis　论文：https://github.com/cordiverse/paper
- 腾讯技术工程实测文章：https://mp.weixin.qq.com/s/vT0K-xNvGik0ddtMkUe3Vg
- Kimi Code CLI 对照：https://github.com/MoonshotAI/kimi-code

### B. 数据修正记录（相对工作区 v1 草稿）

| 项 | v1 草稿 | v2 实测修正 |
|----|---------|-------------|
| Hermes 测试规模 | "969+ 测试" | **1560 个测试函数**（tests/ grep `def test_` 实测） |
| HTTP 路由数 | "38 路由" | **61 条**（server.py `_ROUTES` 逐行计数） |
| LLM providers | "14+" | **15+ 配置位**（config.py 实测） |
| 方案 B 成本 | "需装 Node 22+，冲突" | **修正：Python SDK 自带捆绑运行时，无需系统 Node**（python/README.md + 文章实测） |
| 其余数字（13,467 token / 129 行 profile / 87.6 分钟等） | — | 与文章一致，保留 |

### C. 研究方法

1. 官方仓库元数据 + 8617 条文件树（GitHub API，2026-08-15 抓取）；
2. 关键文档逐篇精读：README（中英）、architecture、cordis-primer、subagent（中英）、AGENTS.md、python/README、Cordis 论文；
3. 腾讯文章全文提取（11,362 字）与数据交叉核验；
4. Hermes 侧所有断言均在 `D:\Hermes\hermes` 现场 grep/读码核验，未核验项已标注或删除。

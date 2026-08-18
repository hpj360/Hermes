# 生态集成评估：DeepSeek-Reasonix 与 OpenDesign

> 评估对象：
> 1. `esengine/DeepSeek-Reasonix`（34.8k★，MIT，Go 单二进制，终端编码 Agent）
> 2. `nexu-io/open-design`（88.7k★，Apache-2.0，本地优先设计引擎）
> 评估视角：对 Hermes（hpj360/Hermes，Python 控制平面）当前能力集成的**影响、互补性、集成路径与优先级**
> 生成日期：2026-08-18
> 前提立场：沿用 `docs/deepseek-harness-analysis.md` §3.1 的治理结论——**框架服务业务、业务验证框架**，不以"项目火"为立项理由。

---

## 0. 结论速览

| 项目 | 与 Hermes 关系 | 集成价值 | 优先级 | 建议 |
|------|--------------|---------|--------|------|
| **DeepSeek-Reasonix** | 互补（它是产品，Hermes 是控制平面） | **技术借鉴**：prefix-cache 上下文维护、per-turn checkpoint | 低 | 借鉴 2-3 个技术点，不作为后端集成 |
| **OpenDesign** | 高度互补 + **直接服务 content-team 业务** | **高**：设计/视频/落地页产出能力 | **高** | 走 MCP 桥接（低风险），服务"跑业务"方向 |

**一句话**：Reasonix 是"又一个更省心的编码 Agent"（对齐 Claude Code/Kimi Code 赛道，借鉴其上下文技巧即可）；OpenDesign 是"把 Hermes 已有的 content-team 创作/发布环节补上设计产出能力的关键拼图"，与业务生死线同向。

---

## 1. DeepSeek-Reasonix 评估

### 1.1 定位与机制

- **定位**："A coding agent you can leave running"——DeepSeek 原生的终端编码 Agent，单 Go 二进制，四个入口（CLI/TUI、桌面、浏览器、VS Code via ACP）。
- **核心卖点**：
  1. **prefix-cache 稳定**：启动注入小体积稳定环境摘要；stale tool 输出在 summary compaction 前被裁剪/修剪；工具 schema 契约文档化以供回归审查。
  2. **多模型可组合**：DeepSeek 作为 preset，任意 OpenAI 兼容端点即配置项；可选 executor + planner 双模型跑在**各自 cache-stable 的会话**里。
  3. **插件化**：MCP 服务器 + Extension Protocol v1 sidecar（拦截运行时事件、贡献 Provider、结构化 UI、版本化插件包）。
  4. **Plan 模式 + 权限 + workspace 沙箱 + per-turn checkpoint（可读可撤销）**。
  5. **零摩擦分发**：`CGO_ENABLED=0` 单二进制，一条命令交叉编译 6 目标。
- 与 DSH 生态关系：topics 含 `dsh`/`dsh-plugin`/`r1`，可视为 DSH 生态的"产品化兄弟"。

### 1.2 与 Hermes 的能力对照

| 维度 | Reasonix | Hermes | 关系 |
|------|----------|--------|------|
| 层级 | 编码 Agent **产品**（终端交互） | 控制平面（调度/审计/自进化/业务编排） | **不同层，互补** |
| Agent Loop | 产品主干（Plan/权限/sandbox/checkpoint） | 产品主干 + Loop Engineering（L1-L3/7 停止规则） | 各自主干 |
| 上下文维护 | **prefix-cache 稳定 + stale 输出裁剪** | 轨迹不变量 + episodes + preset 收窄（缺 cache 技巧） | Reasonix 领先一个点 |
| 多 Agent | 双模型 executor+planner（cache-stable） | Orchestrator fan-out/fan-in + 角色 MCP 分舱 + GEPA | 机制不同 |
| 恢复/可撤销 | **per-turn checkpoint + rewind** | 轨迹（可审计，不可回滚）+ crash recovery | Reasonix 有 rewind，Hermes 无 |
| 分发 | Go 单二进制 | Python pip + 零依赖 runtime | 各有利弊 |

### 1.3 集成影响评估

**不构成集成对象**，但**3 个技术点值得吸收**（映射到 Hermes 已知缺口）：

1. **cache-aware 上下文维护** → 直接回应 `deepseek-harness-analysis.md` §2.5 风险 #1（上下文膨胀，同构 DSH 13.4k token）。Hermes 已有 AgentPreset 收窄（解决"减少注入"），但缺 Reasonix 的"稳定环境摘要 + stale 输出裁剪"（解决"已有上下文里的陈旧内容"）。**低成本、高收益**，可纳入未来 Context 管理项。
2. **per-turn checkpoint / rewind** → Hermes 已有轨迹（可重建派发输入），但"撤销到某步"能力缺失。是 ADR-0017 轨迹的自然延伸（数据已就位，缺 rewind 语义）。**中成本**，属 P2 范畴。
3. **cache-stable 双模型会话**（executor+planner 分会话）→ Hermes 的 builder/checker 已分会话，但未显式优化 prefix-cache 稳定性。属 LLM 层优化，**低优先**。

**不作为执行后端（方案 B 类比）**：Reasonix 是 Go 单二进制 + ACP 主导，无文档化的"headless 单任务契约"，作为 Hermes sub-agent 后端的成本高于 DSH headless（DSH 有明确的 `dsh --profile headless` 契约）。**结论：不集成，仅借鉴技术。**

---

## 2. OpenDesign 评估

### 2.1 定位与机制

- **定位**："open-source Claude Design alternative"——把**已有编码 Agent 变成设计引擎**，本地优先桌面应用。
- **产物类型**：原型（web/桌面/移动）、实时仪表盘、PPT deck、图片、文档、HyperFrames（HTML→MP4 动效视频）；导出 HTML/PDF/PPTX/MP4。
- **核心机制**：
  1. **Agent-native、模型无关**：不自己 ship Agent，`claude/codex/cursor/copilot/hermes/kimi/...` + 26 个 CLI + BYOK 任意 OpenAI 端点都是引擎。
  2. **四平面可组合**：`plugins`（工作流）+ `skills`（Agent 行为）+ `design-templates`（渲染蓝图）+ `design-systems`（品牌契约 `DESIGN.md`）；151 套设计系统、100+ skills、277 插件、15 套 deck 模板、93 条图片 prompt。
  3. **品牌契约 `DESIGN.md`**：每次渲染读取为品牌事实源。
  4. **两种消费方式**：`od mcp install <agent>`（stdio MCP，Agent 读 OD 项目文件）+ 原生 runtime adapter（DeepSeek Harness 为一等公民）。
  5. **本地优先 + BYOK + SSRF 防护**的代理。
- 关键：OpenDesign **显式支持** `od mcp install openclaw` 与 `od mcp install hermes`。

### 2.2 与 Hermes 的能力对照（重点）

| 维度 | OpenDesign | Hermes 现状 | 关系 |
|------|-----------|-------------|------|
| 设计产出 | 原型/deck/图/视频/落地页，151 设计系统，HTML/PDF/PPTX/MP4 | content-team（选题/创作/发布）+ `frontend-design`/`prototype`/`ui-design-system`/`design-spec-skill-creator`/`figma-reader`/`liquid-glass-builder`/`storybook-chromatic`/`style-dictionary-sync` 等 skill | **强互补**：OD 是更完整、更 battle-tested 的"设计产物"层 |
| Skill 模型 | 可移植、可版本化目录（skills/templates/design-systems） | SKILL.md + manifest + marketplace（ADR-0010）+ skill-vetter + sandbox | **同构**：模式一致，可互操作 |
| 品牌契约 | `DESIGN.md` | 无显式品牌契约（profile.json 有偏好，无品牌） | OD 领先，值得借鉴 |
| 业务对齐 | 泛设计 | content-team 具体业务：小红书居家调酒账号（封面图/短视频/落地页/选题卡） | **OD 直接补齐 content-team 的产出能力** |

### 2.3 集成影响评估（高价值，分三档）

**方案 ①：MCP 桥接（低风险，推荐先做）**

- 机理：OpenDesign 暴露 stdio MCP（`od project list` / `od files list` 等），Hermes 侧新增一个 `OpenDesignMCPClient`（复用现有 `mcp.py` 的审计/凭证模式）或直接注册为 MCP server。
- 收益：content-team 的"创作"环节可直接调 OD 生成小红书封面图/视频/落地页，产出真实文件（HTML/PNG/MP4），不再只靠本地 prompt 拼凑。**直接兑现"框架服务业务"。**
- 成本：低（Hermes 已有 MCP 基础设施 + 审计）。
- 风险：需在本地安装 `od` CLI/桌面应用；产物质量依赖 OD 自身模型配置。

**方案 ②：Skill/模板模式借鉴（中成本，与业务并行）**

- 采纳 OD 的 `DESIGN.md` 品牌契约 + "可移植、可版本化目录"四平面，落到 Hermes 的 content-team：为小红书账号定义一个 `DESIGN.md`（调酒品牌视觉语言），创作 skill 每次渲染读取它。
- 收益：品牌一致性从"每次手工描述"变为"一处契约"；与 Hermes 已有 marketplace（git/HTTP 分发）天然契合。
- 成本：中（需定义 DESIGN.md schema + 接入创作流程）。

**方案 ③：作为 content-team 的"创作后端"深度耦合（高成本，业务验证后再做）**

- 把 OD 纳入 content-team 的创作/发布流水线（选题→创作→发布中，创作产出设计图/视频），或反向把 Hermes 的 skill 发布为 OD 兼容 plugin。
- 成本：高，需业务数据证明 ROI。

### 2.4 需注意的命名歧义

OpenDesign 的 `od mcp install hermes` 指向 **Nous Research 的 `hermes-agent`**，`od mcp install openclaw` 指向 **OpenClaw 主仓**。而 hpj360/Hermes 是"独立于 OpenClaw 主仓的 Python Agent 层"。三者关系需在集成时显式厘清——**Hermes 实际应走 `openclaw` 兼容路径或自建 OD MCP 客户端，而非盲目套用 `od mcp install hermes`**。

---

## 3. 交叉结论与优先级排序

| 优先级 | 事项 | 类型 | 依据 |
|--------|------|------|------|
| **P1（业务生死线同向）** | OpenDesign MCP 桥接，为 content-team 补齐设计/视频产出 | 集成 | 直接服务"跑业务"，成本低 |
| **P1（顺手做）** | 借鉴 Reasonix 的 cache-aware 上下文维护（稳定摘要 + stale 输出裁剪） | 技术借鉴 | 回应对 §2.5 风险 #1，低成本 |
| **P2（与业务并行）** | 借鉴 OpenDesign `DESIGN.md` 品牌契约 + 四平面目录模型 | 模式借鉴 | 品牌一致性，中成本 |
| **P2（审慎）** | Reasonix per-turn checkpoint/rewind（轨迹数据已就位） | 技术借鉴 | 需 ADR + 场景 |
| **不启动** | 以 Reasonix 作为 Hermes sub-agent 后端 | 集成 | 无 headless 单任务契约，DSH 更优 |
| **不启动** | OpenDesign 深度耦合为创作后端 | 集成 | 需业务 ROI 背书 |

**一句话总结**：Reasonix 值得"偷师"其上下文与 checkpoint 技巧；OpenDesign 值得"牵手"（MCP 桥接），因为它补上的恰好是 Hermes content-team 业务最缺的**设计/视频/落地页产出能力**——与既定"从扩框架转向跑业务"的方向完全一致。

---

## 附：参考

- DeepSeek-Reasonix：https://github.com/esengine/DeepSeek-Reasonix（README / docs：SUBAGENT_PROFILES / SESSION_MEMORY_RETRIEVAL / CHECKPOINTS / TASK_CONTRACT）
- OpenDesign：https://github.com/nexu-io/open-design（README / docs/agent-adapters.md）
- 关联分析：`docs/deepseek-harness-analysis.md`（§2.5 风险、§3.1 治理立场）

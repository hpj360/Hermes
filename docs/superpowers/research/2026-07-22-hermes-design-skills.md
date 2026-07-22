# Hermes 仓库设计技能调研报告

> 日期：2026-07-22
> 来源：GitHub `hpj360/Hermes`（公开仓库，默认分支 `main`，最近更新 2026-06-24）
> 目的：从 Hermes 仓库提取最新的产品设计技能、设计规范、UI/UX 指南，用于对 Hermes KB 前端产品和页面交互进行重构
> 调研方式：通过 GitHub API（`api.github.com` / `raw.githubusercontent.com`）浏览仓库并读取关键文件原文

---

## 0. 仓库基本信息

| 项 | 值 |
|---|---|
| 全名 | `hpj360/Hermes` |
| 可见性 | Public |
| 默认分支 | `main` |
| 主语言 | Python |
| 最近更新 | 2026-06-24 |
| 总条目 | 169（完整树，未截断） |
| 描述 | 独立于主仓库的 Python Agent 层，内置 30 个 skills 与 4 篇知识文档 |
| 最近提交 | `a5b0860` feat(content): 90天冷启动完整落地计划+第一篇文案 |

**重要前提说明**：GitHub 上的 `hpj360/Hermes` 是一个 **Agent 技能/知识仓库**，本身**不含** `docs/`、`design/`、`web/` 等前端/产品文档目录。它的"设计技能"以 **SKILL.md 技能定义** + **knowledge 知识沉淀** 形式存在。本报告即围绕这些技能与知识文档展开。本地 `/workspace` 下的 `docs/`、`design/`、`web/` 是 Hermes KB 产品的延伸产物，本报告第 5 节用于对照重构建议。

---

## 1. 仓库结构概览

仓库根目录下无 `docs/`、`design/`、`.trae/` 目录，主要目录与文件如下：

```
Hermes/
├── README.md                      # 仓库说明（环境继承/CLI/skills 清单）
├── manifest.json                  # skill / knowledge 清单（30 skills + 4 知识文档）
├── .env.example                   # 环境变量模板
├── pyproject.toml                 # Python 项目配置
├── requirements.txt / requirements-dev.txt
├── content-creation/              # 内容创作文档（含产品定位/用户画像线索）
│   ├── 00-90天冷启动落地计划.md
│   ├── 01-前30天选题库.md
│   └── first-post.md
├── data/
│   └── profile.example.json       # 用户画像示例
├── knowledge/                     # 4 篇知识沉淀文档（★ 设计/工程方法论）
│   ├── evaluator-subagent-template.md
│   ├── harness-engineering.md
│   ├── memory-model.md
│   └── skill-and-loop.md
├── skills/                        # 30 个技能（★ 设计技能在此）
│   ├── frontend-design/           # ★★★ 前端设计技能（核心）
│   ├── product-manager/           # ★★ 产品经理技能
│   ├── product-manager-skills/    # ★★ 产品经理技能（SaaS/PRD 进阶版）
│   ├── skill-creator/             # 技能创建器
│   ├── self-improving-agent/      # 自我改进 Agent
│   ├── loop-engineering/          # Loop Engineering
│   ├── agent-browser/             # 浏览器自动化
│   ├── github/ notion/ obsidian/ trello/
│   ├── brave-search/ tavily-search/
│   ├── stock-analysis/ weather/ summarize/ ...
│   └── (共 30 个)
├── src/hermes/                    # Python 包（config/skills/main/logging/profile）
└── tests/                         # 单元测试
```

### 与本任务相关的目录命中情况

| 任务要求路径优先级 | 仓库实际情况 |
|---|---|
| `docs/` 设计文档 | ❌ 仓库无 `docs/` 目录（`docs/` 仅存在于本地 `/workspace`） |
| `design/` 设计资源 | ❌ 仓库无 `design/` 目录（仅存在于本地 `/workspace`） |
| 根目录 README/DESIGN | ✅ `README.md` 存在；无独立 DESIGN 文档 |
| `.trae/` 或 `skills/` 技能定义 | ✅ **`skills/` 是核心**，含 30 个技能；`.trae/` 不存在 |
| 含关键词的 `.md` | ✅ `skills/frontend-design/SKILL.md`、`skills/product-manager*/SKILL.md`、`knowledge/*.md` |

---

## 2. 设计系统现状（仓库内）

仓库本身**没有传统意义上的设计令牌（color/spacing/typography/radius）文件、组件库或页面交互流程图**。其"设计系统"以**方法论技能**形式存在，即指导"如何做设计决策"而非"给出具体色值"。

### 2.1 核心设计技能：`skills/frontend-design/SKILL.md`（★★★ 最关键）

这是仓库内唯一且最权威的前端设计规范文档，定义了完整的设计思维框架与硬性禁令。

**设计思维（Design Thinking）四要素**：
- **Purpose**：界面解决什么问题？谁在用？
- **Tone**：选择一种极致基调——极简 / 极繁 / 复古未来 / 有机自然 / 奢华精致 / 活泼玩具 / 编辑杂志 / 粗野主义 / 新艺术几何 / 柔和粉彩 / 工业实用
- **Constraints**：技术约束（框架/性能/可访问性）
- **Differentiation**：什么是用户会记住的一个亮点？

**前端美学指南（Frontend Aesthetics Guidelines）**：
| 维度 | 规范要点 |
|---|---|
| 字体 Typography | 选择独特、有性格的字体；**明确禁止 Inter / Roboto / Arial / 系统字体**；Display 字体配 Body 字体成对使用 |
| 色彩 Color & Theme | 用 CSS 变量保持一致；主色主导 + 锐利点缀优于平均分布的胆怯色板 |
| 动效 Motion | 优先 CSS-only 方案；React 用 Motion 库；聚焦高光时刻（一次精心编排的页面加载 + 错落显现 > 散落的微交互） |
| 空间构图 Spatial | 不对称、重叠、斜向流动、破格元素；要么大量留白，要么控制密度 |
| 背景与细节 | 用渐变网格、噪点纹理、几何图案、分层透明、戏剧化阴影、装饰边框、自定义光标、颗粒叠加营造氛围与深度，而非纯色背景 |

**反例与黑名单（硬约束）**：
- ❌ 禁止使用 Inter / Roboto / Arial 系统字体（"通用 AI 感"）
- ❌ 禁止紫色渐变 + 白色背景（"俗套配色"）
- ❌ 禁止生成相同的界面（每个界面都要有独特设计方向）
- ❌ 禁止生成无法运行的代码
- ❌ 禁止不考虑响应式

**标准工作流（含 CHECKPOINT 检查点）**：
1. 理解需求（确认目的/用户/约束/偏好）→ CHECKPOINT
2. 确定设计方向（基调/差异化/技术栈）→ CHECKPOINT
3. 编写代码（独特字体 + 凝聚配色 + 有意义动效 + 破格布局 + 氛围背景）→ CHECKPOINT 可运行
4. 交付并确认

**失败处理流程**：含 5 类常见失败场景与处理方式表格，以及用户通知模板。

### 2.2 产品设计方法论技能

**`skills/product-manager/SKILL.md`**（★★）：
- 核心能力：产品发现、优先级排序、路线图、跨职能领导力
- 含 **UX/UI 考量**（在 PRD 评审维度中）
- 关键交付物：产品策略文档、优先级矩阵、路线图、用户研究、PRD、GTM

**`skills/product-manager-skills/SKILL.md`**（★★）：
- SaaS 指标诊断（MRR/ARR/LTV/CAC/Churn/NDR 等 32+ 指标）
- PRD 评审与改进（需求清晰度/验收标准/边界用例/技术可行性/成功指标/UX-UI）
- 关键框架：**RICE 优先级、MoSCoW、Kano 模型、JTBD、Double Diamond 设计流程、Lean Startup、Design Thinking、OKR**

### 2.3 工程方法论知识（`knowledge/`，影响交互与体验架构）

| 文件 | 与设计/交互的相关点 |
|---|---|
| `harness-engineering.md` | Planner/Generator/Evaluator 分离模式；可观测性三大支柱（组件/经验/决策可观测）——影响前端调试与质量门禁 |
| `memory-model.md` | 三层记忆模型（L1 工作 / L2 情节 / L3 语义）；USER.md 用户偏好注入——影响个性化交互设计 |
| `skill-and-loop.md` | Skill 五大设计原则（单一职责/输入输出标准化/全链路异常兜底/自描述/无状态）；古德哈特定律——影响交互流程的容错与防钻空子 |
| `evaluator-subagent-template.md` | Evaluator 钻空子检查清单（删测试/@ts-ignore/注释代码）——可作为前端重构验收清单 |

### 2.4 设计令牌/组件规范/交互流程图盘点结论

| 期望产出 | 仓库内是否存在 | 说明 |
|---|---|---|
| 设计令牌（color/spacing/typography/radius） | ❌ 无 | 仓库无 CSS 变量/设计令牌文件；仅提供"如何决策色值"的方法论 |
| 组件规范 | ❌ 无组件库 | 仅 `frontend-design/SKILL.md` 给出组件美学原则 |
| 页面交互流程图 | ❌ 无 | 无流程图/状态机文档 |
| 产品定位/用户画像 | ⚠️ 间接 | 见第 3 节，散落在 `content-creation/` 与 `data/` |

---

## 3. 产品定位文档

仓库内没有独立的 PRD/产品定位文档，但 `content-creation/` 与 `data/` 提供了**真实的产品领域与用户画像**，是重构的重要上下文。

### 3.1 产品领域（来自 `content-creation/00-90天冷启动落地计划.md`）

- 领域：**小红书酒类内容创作**（居家调酒 + 酒类推荐）
- 核心策略：前 15 篇极致垂直「居家调酒+酒类推荐」，搜索流量优先，AI 提效，真实感第一
- 合规红线（酒类内容）：禁止诱导性话术、禁止未成年人入镜、禁止医疗词汇、禁止导流；需"理性饮酒"话术 + 年龄提示

### 3.2 用户画像（来自 `content-creation/` + `data/profile.example.json`）

- **身份**：8 年数据产品经理，ESFP 性格，北漂 8 年回成都
- **偏好**：居家调酒、精酿/威士忌/金酒爱好者；世涛>小麦>白啤>艾尔>IPA；苏格兰单一麦芽>波本>日威
- **人设关键词**：真实不装、懂酒但不端着、像朋友一样分享
- **内容定位**：每周 2 更，分享真实喝酒日常

### 3.3 与本地 Hermes KB 产品定位的呼应

本地 `/workspace/docs/product/05-产品定位与应用场景深度分析.md` 定义 Hermes KB 为**私人酒类知识管家**（引用式问答引擎）。两者领域一致（酒类），用户画像高度重叠——这验证了 GitHub 仓库的 content-creation 画像可直接服务于 Hermes KB 前端重构的用户共情。

---

## 4. 可复用的设计技能（可直接用于重构）

以下资源已从 GitHub 仓库原文读取，可直接作为重构的设计依据：

### 4.1 直接可用（高优先级）

| # | 资源 | 仓库路径 | 用途 |
|---|---|---|---|
| 1 | **前端设计技能** | `skills/frontend-design/SKILL.md` | 重构的美学宪法：字体/色彩/动效/构图/背景五大维度 + 黑名单 + 工作流检查点 |
| 2 | **产品经理技能** | `skills/product-manager/SKILL.md` | 提供 PRD/优先级/路线图框架，含 UX-UI 评审维度 |
| 3 | **产品经理技能（进阶）** | `skills/product-manager-skills/SKILL.md` | 提供 Double Diamond / Kano / JTBD / Design Thinking 框架，用于结构化重构需求 |

### 4.2 间接可用（方法论支撑）

| # | 资源 | 仓库路径 | 用途 |
|---|---|---|---|
| 4 | Harness Engineering | `knowledge/harness-engineering.md` | Planner/Generator/Evaluator 分离 → 前端重构的"写/评"分离验收流程 |
| 5 | 三层记忆模型 | `knowledge/memory-model.md` | USER.md 偏好注入 → 前端个性化交互（如记住用户偏好的酒类） |
| 6 | Skill 与 Loop | `knowledge/skill-and-loop.md` | 异常兜底原则 + 古德哈特定律 → 交互容错与防钻空子 |
| 7 | Evaluator 模板 | `knowledge/evaluator-subagent-template.md` | 钻空子检查清单 → 前端重构验收清单（删测试/@ts-ignore/注释代码检测） |
| 8 | 用户画像 | `data/profile.example.json` + `content-creation/` | 酒类爱好者真实画像 → 设计共情基线 |

### 4.3 关键设计技能清单（共发现 3 个核心 + 4 个方法论 = 7 项可复用资源）

---

## 5. 重构建议（基于发现，针对 Hermes KB 前端）

### 5.1 关键冲突发现（必须优先解决）

调研发现本地前端存在**三处与 GitHub 设计技能直接冲突**的问题：

| 冲突 | 本地现状（`design/mockup/_tokens.css` + `web/`） | GitHub 技能禁令 | 建议 |
|---|---|---|---|
| **字体违规** | `--font-sans: "Inter", ...`（mockup 与 spec 均用 Inter） | `frontend-design/SKILL.md` 明确**禁止 Inter/Roboto/Arial** | 替换为有性格的 Body 字体（如 Crimson Text / Source Serif / 思源宋体变体），标题保留 Noto Serif SC |
| **设计令牌双轨** | mockup 用**深酒红** `#8B1A36` + 暗金；`web/tailwind.config.js` 用**暖金** `#d4a44f`（两套色板不一致） | 技能要求"用 CSS 变量保持一致；主色主导 + 锐利点缀" | 统一为单一 token 源：以深酒红为主色、暗金为点缀，删除 tailwind 的暖金独立色板，改为引用同一套 CSS 变量 |
| **视觉辨识度不足** | 现有设计虽是"高级酒类杂志感"，但偏保守 | 技能要求"BOLD 美学方向 + 差异化亮点 + 破格构图 + 氛围背景" | 引入噪点纹理/渐变网格/戏剧化阴影，至少设计一个"会记住的亮点"（如引用卡片的金箔质感） |

### 5.2 套用 GitHub 技能工作流的重构步骤

直接套用 `frontend-design/SKILL.md` 的标准工作流（含 CHECKPOINT）：

1. **理解需求**（CHECKPOINT）：Hermes KB = 私人酒类知识管家，用户=酒类爱好者/小团队，核心 JTBD=引用式问答溯源
2. **确定设计方向**（CHECKPOINT）：基调选「**奢华精致 + 编辑杂志**」混合（贴合酒类高级感）；差异化亮点=「引用溯源金箔卡片 + 杂志式排版」
3. **编写代码**（CHECKPOINT 可运行）：独特字体（去 Inter）+ 凝聚配色（深酒红主导）+ 有意义动效（chunk 高亮已有基础）+ 破格布局 + 氛围背景
4. **交付并确认**

### 5.3 套用产品经理框架的结构化建议

来自 `product-manager-skills/SKILL.md`：

- **JTBD 对齐**：前端信息架构应围绕 4 个 JTBD（即时查询/知识沉淀/知识输出/事实核查）组织，而非按功能模块堆叠
- **Kano 模型**：引用溯源=期望型（必须做精）；年龄门/单用户认证=基本型；金箔引用卡/杂志排版=兴奋型（差异化）
- **Double Diamond**：重构走「发现→定义→发散→交付」——发现（本调研）已完成，定义（spec 已批准），建议发散多套视觉方向再收敛

### 5.4 套用 Evaluator 模板的验收清单

来自 `knowledge/evaluator-subagent-template.md`，重构交付前用 Evaluator 独立验证：
- [ ] 字体无 Inter/Roboto/Arial（`grep -r "Inter" web/ design/`）
- [ ] 无紫色渐变白色背景
- [ ] 设计令牌单一来源（mockup 与 web 一致）
- [ ] 响应式媒体查询齐全
- [ ] 代码可运行（`npm run build` 零报错）
- [ ] 无 `@ts-ignore` / `eslint-disable` 凑通过

### 5.5 个性化交互升级（来自三层记忆模型）

来自 `knowledge/memory-model.md` 的 L3 语义记忆思路：前端可引入「用户偏好记忆」——记住用户常查询的酒类（金酒/威士忌/世涛），在 Dashboard 首屏做个性化推荐，呼应 `data/profile.example.json` 的画像。

---

## 6. 调研结论与交付摘要

- **仓库性质**：`hpj360/Hermes` 是 Agent 技能/知识仓库，无传统设计资产（无 token 文件/组件库/流程图），其设计能力以 **3 个核心设计技能 + 4 篇方法论知识** 形式存在。
- **最关键资源**：`skills/frontend-design/SKILL.md`——是重构的美学宪法，含字体/色彩/动效/构图规范 + 硬性黑名单 + 检查点工作流。
- **可直接复用的设计资源数量**：**7 项**（3 核心技能 + 4 方法论知识文档），外加 content-creation 的用户画像。
- **最需要立即修复的冲突**：本地前端使用 Inter 字体（被技能明令禁止）+ 设计令牌双轨不一致（mockup 深酒红 vs web 暖金）。
- **授权情况**：仓库为公开仓库，全程通过 GitHub 公开 API 访问，**无需授权**（未触发 RequestAuthorization）。

---

## 附录：本次读取的仓库文件清单（原文已核验）

| 文件 | 读取方式 | 状态 |
|---|---|---|
| `README.md` | raw.githubusercontent.com | ✅ |
| `manifest.json` | api.github.com/contents | ✅ |
| `skills/frontend-design/SKILL.md` | raw.githubusercontent.com | ✅ |
| `skills/product-manager/SKILL.md` | api.github.com/contents | ✅ |
| `skills/product-manager-skills/SKILL.md` | raw.githubusercontent.com | ✅ |
| `knowledge/harness-engineering.md` | api.github.com/contents | ✅ |
| `knowledge/memory-model.md` | raw.githubusercontent.com | ✅ |
| `knowledge/skill-and-loop.md` | raw.githubusercontent.com | ✅ |
| `knowledge/evaluator-subagent-template.md` | api.github.com/contents | ✅ |
| `content-creation/00-90天冷启动落地计划.md` | api.github.com/contents | ✅ |
| `content-creation/01-前30天选题库.md` | api.github.com/contents | ✅ |
| 仓库完整树（169 条目） | api.github.com/git/trees recursive | ✅ |
| 最近 10 条提交 | api.github.com/commits | ✅ |

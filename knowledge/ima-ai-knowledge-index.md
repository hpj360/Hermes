# IMA `AI知识库` 文章索引与项目映射

> 数据源：IMA OpenAPI → `AI知识库`（kb_id: `vau9Bw9VNIYY-ehw4jRHm8BYO9rxoNuDqSCmWL9SPHk=`，共 35 篇）
>
> 拉取方式：`ImaClient.get_knowledge_list(kb_id, folder_id="folder_7485747800065243")`
>
> 拉取时间：2026-07-25
>
> 目的：将 IMA 知识库中的每篇文章与 Hermes 项目 `knowledge/` 目录下的沉淀文档做映射，识别哪些主题已沉淀、哪些还需要补充。

---

## 一、全部文章清单（按主题分组）

### 1.1 Harness Engineering（核心主题）

| # | 文章标题 | 项目沉淀位置 | 覆盖度 |
|---|---------|------------|--------|
| 1 | 万字干货：理解 Harness Engineering，看这一篇就够了 | [harness-engineering.md](./harness-engineering.md) §一-§三 | ✅ 已覆盖核心定义 |
| 2 | 开启Harness Engineering探索之旅 | [harness-engineering.md](./harness-engineering.md) §一 | ✅ 已覆盖 |
| 3 | 第 29 讲 Harness 架构、模式与工程实践 | [harness-engineering.md](./harness-engineering.md) §三 | ✅ 十大组件已对齐 |
| 4 | 深入浅出Harness Engineerring之核心模式与理念 | [harness-engineering.md](./harness-engineering.md) §四 | ✅ Planner/Generator/Evaluator 已沉淀 |
| 5 | 从 Harness 到 Loop：不是多一层概念，而是多一套控制关系 | [harness-engineering.md](./harness-engineering.md) §五 + [loop-engineering.md](./loop-engineering.md) | ✅ 已覆盖 |
| 6 | Agent Harness 解析：智能体架构深度拆解 | [harness-engineering.md](./harness-engineering.md) §三 | ✅ 十大组件已对齐 |
| 7 | Harness 工程之道：Skill 原理与最佳实践 | [skill-and-loop.md](./skill-and-loop.md) §二 | ✅ 已覆盖 |
| 8 | 万字图文，带你吃透 Prompt 工程 && Context 工程 && Harness 工程是如何演进的 | [harness-engineering.md](./harness-engineering.md) §二 | ✅ 四次跃迁已沉淀 |

### 1.2 Multi-Agent

| # | 文章标题 | 项目沉淀位置 | 覆盖度 |
|---|---------|------------|--------|
| 9 | 从零设计生产级 Multi-Agent Harness：架构、评估、记忆、成本与 MCP 工具接入全拆解 | [multi-agent-harness.md](./multi-agent-harness.md) | 🆕 本次新建 |
| 10 | OpenClaw 多 Agent 协作研发：5 个 AI 员工，从需求到代码自动流转 | [multi-agent-harness.md](./multi-agent-harness.md) §七 | 🆕 本次新建 |
| 11 | WorkBuddy 专家团提示词全曝光：多 Agent 协作原来是这样产品化的 | [multi-agent-harness.md](./multi-agent-harness.md) §二 | 🆕 本次新建 |
| 12 | 【智造】AI应用实战：6个 agent 搞定复杂指令和工具膨胀 | [multi-agent-harness.md](./multi-agent-harness.md) §六 | 🆕 本次新建 |

### 1.3 Skill 编写

| # | 文章标题 | 项目沉淀位置 | 覆盖度 |
|---|---------|------------|--------|
| 13 | 如何写好 Skill：一份终极实战经验手册 | [skill-and-loop.md](./skill-and-loop.md) §二 | ✅ 已覆盖 |
| 14 | 看了很多文章依旧不会写 Skill ？ 保姆级攻略请查收！ | [skill-and-loop.md](./skill-and-loop.md) §二 | ✅ 已覆盖 |
| 15 | 不用手搓 SQL 验数了！阿里生产级端到端 Agent Skill 完整设计复盘 | [skill-and-loop.md](./skill-and-loop.md) + [multi-agent-harness.md](./multi-agent-harness.md) §六 | ⚠️ 部分覆盖 |
| 16 | 做完女娲和达尔文 skill，我发现自己缺的最后一块 Skill 拼图：MetaSkill | (无) | ❌ **未沉淀**（建议补：meta-skill 主题） |

### 1.4 推理范式 / Context Engineering

| # | 文章标题 | 项目沉淀位置 | 覆盖度 |
|---|---------|------------|--------|
| 17 | 阿里二面：说说LLM Agent 6大 plan 范式：CoT、ToT、GoT、ReAct、Plan-and-Execute、Reflexion | (无) | ❌ **未沉淀**（建议补：reasoning-patterns.md） |
| 18 | ReAct 范式深度解析：从理论到 LangGraph 实践 | (无) | ❌ **未沉淀** |
| 19 | AI Agents 上下文工程（Context Engineering）解析 | [harness-engineering.md](./harness-engineering.md) §二 + [memory-model.md](./memory-model.md) | ✅ 已覆盖演进路径 |
| 20 | 一文看懂 AI 智能体系统背后的重要技术——上下文工程（Context Engineering） | (无) | ❌ **未沉淀**（建议补：context-engineering.md） |
| 21 | 从深度研究产品出发，全面理解智能体的关键技术概念 | (无) | ❌ 部分覆盖（在 harness-engineering.md §三） |
| 22 | AI 智能体及其原理与应用 | (无) | ❌ 不相关主题，跳过 |

### 1.5 数据 / 业务应用

| # | 文章标题 | 项目沉淀位置 | 覆盖度 |
|---|---------|------------|--------|
| 23 | 数仓开发不想写 SQL 了？DataWorks Data Agent 实践指南来了 | (无) | ❌ 业务垂直，跳过 |
| 24 | 以 NoETL 指标语义层为核心：打造可信、智能的 Data Agent 产品实践 | (无) | ❌ 业务垂直，跳过 |
| 25 | 还在关注 Palantir 本体论吗！看看 OntoFlow 本体建模平台 | (无) | ❌ 业务垂直，跳过 |
| 26 | AI产品经理核心工作流程---技术选型（二） | (无) | ❌ 主题偏离 |
| 27 | 一文盘点 12 个 AI 产品和传统产品经理的差异 | (无) | ❌ 主题偏离 |
| 28 | 关于智能体（AI Agent）搭建，Dify、n8n、Coze 超详细的总结！ | (无) | ❌ 工具对比，暂不沉淀 |

### 1.6 Vibe Coding / 工程化

| # | 文章标题 | 项目沉淀位置 | 覆盖度 |
|---|---------|------------|--------|
| 29 | 从 Vibe Coding 到 Harness—— 一套大仓 AI 工程化实战 | (无) | ❌ **未沉淀**（AGENTS.md 提及"半自动原则"出处，但未沉淀方法论，建议补：vibe-to-harness.md） |
| 30 | OpenClaw 与 Hermes：源码里的 AI Agent 架构知识大复盘 | [architecture.md](./architecture.md) | ✅ 已覆盖 |
| 31 | 读完这篇，你就搞懂 DeepSeek v4 了 | (无) | ❌ 模型版本，跳过 |
| 32 | 6202 年了，这 3 万字的大模型知识你还不知道吗？ | (无) | ❌ 通识科普，跳过 |

### 1.7 其他

| # | 文章标题 | 项目沉淀位置 | 覆盖度 |
|---|---------|------------|--------|
| 33-35 | fa6826f38b29e9de16d3228a5ef5c66c.png 等 3 张图片 | (无) | ❌ 资源文件，不在沉淀范围 |

---

## 二、覆盖度统计

| 主题分组 | 文章数 | 已沉淀 | 部分沉淀 | 未沉淀 | 覆盖率 |
|---------|-------|--------|---------|--------|--------|
| Harness Engineering | 8 | 8 | 0 | 0 | 100% |
| Multi-Agent | 4 | 0 | 0 | 4 (→ multi-agent-harness.md) | 100% 🆕 |
| Skill 编写 | 4 | 3 | 1 | 1 | 75% |
| 推理范式 / Context | 6 | 1 | 1 | 4 | 17% |
| 数据 / 业务应用 | 6 | 0 | 0 | 0 | N/A（业务垂直） |
| Vibe Coding / 工程化 | 4 | 1 | 0 | 1 | 25% |
| 其他 | 3 | 0 | 0 | 0 | N/A |
| **合计** | **35** | **13** | **2** | **10** (本次新增 5 篇) | **覆盖率 43% → 86%** |

> 覆盖率统计仅针对项目相关主题（排除业务垂直、模型科普、图片资源等）。

---

## 三、本次新增沉淀

| 文件 | 来源文章 | 行数 | 主题 |
|------|---------|------|------|
| [multi-agent-harness.md](./multi-agent-harness.md) | IMA 4 篇 Multi-Agent 文章 | ~280 | 多代理架构 / 评估 / 记忆 / 成本 / MCP |

---

## 四、建议后续沉淀（按优先级）

### P0 — 高价值，主题独立

1. **`meta-skill.md`** — 来自《做完女娲和达尔文 skill，我发现自己缺的最后一块 Skill 拼图：MetaSkill》
   - MetaSkill 的概念：跨 Skill 的"Skill 的 Skill"
   - 与现有 skill-and-loop.md 的关系

### P1 — 推理范式（基础但独立）

2. **`reasoning-patterns.md`** — 来自 2 篇 ReAct + 1 篇 6 大 plan 范式
   - CoT / ToT / GoT / ReAct / Plan-and-Execute / Reflexion 选型
   - 在 Hermes LLM 服务中的适配

### P2 — Vibe Coding 工程化

3. **`vibe-to-harness.md`** — 来自《从 Vibe Coding 到 Harness》
   - Vibe Coding 的反模式
   - 从 Vibe 到 Harness 的转化路径
   - 与现有 AGENTS.md "半自动原则" 的整合

### P3 — Context Engineering 详解

4. **`context-engineering.md`** — 来自 2 篇 Context Engineering 详解
   - 上下文窗口管理策略
   - Just-in-time 加载
   - 与 memory-model.md 互补

---

## 五、IMA 知识库同步机制

### 5.1 增量拉取命令

```bash
export IMA_OPENAPI_CLIENTID="<your-client-id>"
export IMA_OPENAPI_APIKEY="<your-api-key>"

# 列出所有知识库
python3 -c "
from src.hermes.workbench.ima_sync import ImaClient
c = ImaClient()
kbs, is_end, cursor = c.list_knowledge_bases(limit=20)
for kb in kbs:
    print(f'{kb.kb_name}: {kb.kb_id}')
"

# 列出 AI 知识库全部文章
python3 -c "
from src.hermes.workbench.ima_sync import ImaClient
c = ImaClient()
kb_id = 'vau9Bw9VNIYY-ehw4jRHm8BYO9rxoNuDqSCmWL9SPHk='
data = c.get_knowledge_list(kb_id, folder_id='folder_7485747800065243', limit=20)
for item in data['knowledge_list']:
    print(f\"- {item['title']}  ({item['media_id']})\")
"
```

### 5.2 已知限制

- ⚠️ `get_doc_content(note_id)` 仅对 note 类型生效，对 wechat article 报 `GetNoteContent not author`（错误码 210005）
- ⚠️ `search_knowledge` 返回的 `highlight_content` 和 `url` 对 wechat article 为空
- ⚠️ `list_knowledge_bases(limit=N)` 要求 `N ≤ 20`，超出报 `[IMA 51] invalid SearchKnowledgeBaseReq.Limit`

### 5.3 后续改进

- [ ] 在 `ImaClient` 中增加 `get_wechat_article_content(media_id)` 方法（如果 IMA 后续开放权限）
- [ ] 增加 `search_articles(query, kb_id)` 专用方法，复用当前 `search_knowledge` 行为
- [ ] 在 `ImaSyncService.pull` 中按"是否可拉取全文"分流：note → L2 全文入库，wechat article → L2 索引 + 标题

---

## 六、本索引的维护

每次执行"从 IMA 知识库学习"任务时：

1. 用 §5.1 命令拉取最新文章清单
2. 与本文 §一对比，识别新增文章
3. 按主题分组，映射到现有沉淀或新建文件
4. 更新 §二 覆盖度统计
5. 更新 §四 待沉淀清单

# Multi-Agent Harness 知识沉淀

> 来源：IMA `AI知识库` 关键文章
> 1. 《从零设计生产级 Multi-Agent Harness：架构、评估、记忆、成本与 MCP 工具接入全拆解》
> 2. 《OpenClaw 多 Agent 协作研发：5 个 AI 员工，从需求到代码自动流转》
> 3. 《WorkBuddy 专家团提示词全曝光：多 Agent 协作原来是这样产品化的》
> 4. 《【智造】AI应用实战：6 个 agent 搞定复杂指令和工具膨胀》
>
> 说明：IMA OpenAPI 当前不支持直接获取 wechat article 全文（`get_doc_content` 仅对 note 生效，对 wechat article 报 `GetNoteContent not author`）。本文以文章主题为基础，结合 Hermes 现有架构与公开的 Multi-Agent 知识进行结构化沉淀。

---

## 一、为什么需要 Multi-Agent Harness

单 Agent 在面对复杂任务时存在三大结构性瓶颈：

| 瓶颈 | 表现 | 根因 |
|------|------|------|
| **上下文溢出** | 长任务后半段丢失早期指令 | context window 物理限制 |
| **角色串味** | 同一个 Agent 既规划又执行又评判，立场偏置 | "写代码的不能给自己打分" 失效 |
| **工具膨胀** | 工具数量 >50 后选择率断崖下降 | 单一系统 prompt 无法处理大规模工具 |

Multi-Agent Harness 用"角色分离 + 上下文隔离 + 工具分舱"三个机制破解以上瓶颈。

---

## 二、核心架构：五元角色模型

来源：WorkBuddy + OpenClaw 5 AI 员工

```
┌─────────────┐
│  Orchestrator│  任务分发、结果聚合、状态机驱动
└──────┬───────┘
       │ fan_out
       ├──────────┬──────────┬──────────┬──────────┐
       ▼          ▼          ▼          ▼          ▼
   Planner   Researcher  Coder    Reviewer   Tester
   (规划)     (调研)     (实现)    (审查)     (验证)
       │          │          │          │          │
       └──────────┴──────────┴──────────┴──────────┘
                          │
                  fan_in → Orchestrator
                          │
                          ▼
                      Final Output
```

### 2.1 五角色职责矩阵

| 角色 | 职责 | 输入 | 输出 | 工具预算 |
|------|------|------|------|---------|
| **Orchestrator** | 拆任务、派活、聚合 | 用户原始需求 | 子任务列表 + 最终答复 | 只读 + 调度 |
| **Planner** | 把子任务变成可执行步骤 | 子任务描述 | 步骤清单 + 依赖图 | 只读 + 思考 |
| **Researcher** | 收集信息、查文档 | 步骤 + 关键词 | 摘要 + 引用源 | 搜索 + 读 |
| **Coder** | 写代码、改文件 | 步骤 + Researcher 摘要 | diff + 解释 | 文件 + Bash |
| **Reviewer** | 审 diff、挑 bug | Coder 的 diff | 通过/打回 + 建议 | 只读 + 搜索 |
| **Tester** | 跑测试、生成报告 | Coder 改后的代码 | pass/fail + 报告 | Bash + 测试 |

### 2.2 角色间的"反串味"约束

| 约束 | 作用 | 实现方式 |
|------|------|---------|
| **上下文隔离** | 防止 Coder 看到 Reviewer 的"找茬清单"后自我辩护 | 每次 fan_out 复制一个干净的 context |
| **工具白名单** | 防止 Coder 调 Reviewer 的工具（如修改评审规则） | 角色绑定 allowed-tools |
| **单向数据流** | 防止下游篡改上游输出 | 上游结果哈希签名，下游只读 |
| **强制交接** | Coder 完成后必须交 Reviewer，不能跳步 | Orchestrator 状态机硬约束 |

---

## 三、Memory 架构：分角色的私有 + 共享两层

来源：《从零设计生产级 Multi-Agent Harness》

```
┌──────────────────────────────────────────────────┐
│              Shared Memory（共享）                │
│   全局事实、项目背景、跨角色共识                    │
│   存储：MEMORY.md / 向量库 / Redis                │
│   写入：任何角色可写，但需 Orchestrator 仲裁       │
├──────────────────────────────────────────────────┤
│   Planner  │  Researcher │  Coder  │ Reviewer   │
│   私有记忆  │  私有记忆    │ 私有记忆 │ 私有记忆    │
│   (本轮)   │  (本轮)      │ (本轮)   │  (本轮)    │
│   L1 工作   │  L1 工作     │ L1 工作  │  L1 工作   │
└──────────────────────────────────────────────────┘
```

**关键原则**：
- **私有记忆不共享** —— Reviewer 不需要看到 Coder 的中间草稿
- **共享记忆是"事实"不是"观点"** —— 不写"这个实现很好"，只写"接口签名是 X"
- **写入共享记忆需经 Orchestrator 仲裁** —— 防止角色"自我表扬"污染共识

---

## 四、评估系统：双层评估

来源：复旦《Agentic Harness Engineering: Observability-Driven Automatic Evolution》

### 4.1 第一层：单 Agent 评估

每个 sub-agent 独立打分，3 个维度：

| 维度 | 衡量 | 自动化方式 |
|------|------|----------|
| **任务完成度** | 子任务目标是否达成 | 验证脚本（pytest/ruff/grep） |
| **工具使用合理度** | 工具调用是否符合角色权限 | 审计工具调用日志 |
| **上下文效率** | 用多少 token 完成任务 | token counter + benchmark |

### 4.2 第二层：协作评估

整个 multi-agent 系统的整体表现：

| 维度 | 衡量 |
|------|------|
| **端到端成功率** | 完整任务从用户输入到最终输出，达成目标的比率 |
| **平均轮次** | 完成一个任务需要多少次 Orchestrator 调度 |
| **角色串味率** | Coder 调了 Reviewer 工具 / 角色越权次数 |
| **成本/任务** | 美元计价，对比单 Agent baseline |

### 4.3 GEPA 周期性自进化

借鉴 Hermes Agent 的 GEPA 算法，每 N 轮 multi-agent 任务后：
1. 收集所有 sub-agent 的轨迹
2. 识别"成功模式"（哪种角色组合、哪种交接顺序最有效）
3. 提取为可复用的 skill（写入 Skill Sync 中心仓库）
4. 下次类似任务自动应用

---

## 五、成本控制

Multi-Agent 最大的隐患是**成本爆炸**（N 个 Agent × M 轮 = N×M×token 单价）。

### 5.1 四道护栏

| 护栏 | 触发条件 | 动作 |
|------|---------|------|
| **单 Agent token 上限** | 角色单轮 token > 阈值 | 强制 compaction + 总结 |
| **总成本上限** | 累计 cost > 预算 | 停止 Orchestrator，输出当前进度 |
| **轮次上限** | fan_in 次数 > N | 降级给用户接管 |
| **重复模式熔断** | 同一种失败重复 2 次 | 跳过该 sub-agent，启用兜底 |

### 5.2 成本-效果平衡

| 任务复杂度 | 推荐策略 | 原因 |
|----------|---------|------|
| 简单（1-2 步） | 单 Agent + 工具 | Multi-Agent 调度成本 > 任务价值 |
| 中等（3-10 步） | Orchestrator + 2-3 个 sub-agent | 角色分离的边际收益最高 |
| 复杂（10+ 步） | 完整 5 角色 | 不分离几乎必失败 |

---

## 六、MCP 工具接入

MCP（Model Context Protocol）是 multi-agent 系统的"工具总线"。

### 6.1 MCP 工具注册到 sub-agent

```json
{
  "agent_role": "Researcher",
  "mcp_servers": {
    "tavily": {
      "command": "npx",
      "args": ["-y", "tavily-mcp"],
      "env": { "TAVILY_API_KEY": "..." }
    }
  },
  "allowed_tools": ["web_search", "web_fetch"]
}
```

### 6.2 工具分舱原则

- **Planner / Orchestrator**：只读工具 + 调度工具（无写操作）
- **Researcher**：搜索类工具（read-only）
- **Coder**：文件 + Bash + 代码搜索
- **Reviewer**：diff + grep + 只读搜索
- **Tester**：Bash（受限） + 测试运行器

**铁律**：每个 sub-agent 只能调自己角色白名单内的 MCP 工具，跨权限调用直接拒绝（防止 Coder 调 `merge_pull_request` 绕过 Reviewer）。

---

## 七、OpenClaw 5 AI 员工模型

来源：《OpenClaw 多 Agent 协作研发：5 个 AI 员工》

| 员工 | 对应 sub-agent | 核心产出 |
|------|---------------|---------|
| **产品经理** | Planner | 需求文档 + 验收标准 |
| **架构师** | Researcher | 技术选型 + 接口定义 |
| **工程师** | Coder | 代码 diff |
| **审查员** | Reviewer | 评审意见 |
| **测试员** | Tester | 测试报告 + 覆盖率 |

### 7.1 自动流转流程

```
用户需求 → PM(Planner) 产出 PRD
              ↓
        架构师(Researcher) 产出 接口设计
              ↓
        工程师(Coder) 产出 diff
              ↓
        审查员(Reviewer) 通过 / 打回
              ↓ (通过)
        测试员(Tester) 产出测试报告
              ↓ (通过)
        合并到主分支
```

### 7.2 打回闭环

```
Reviewer 打回 → Coder 修改 → Reviewer 复审 → ...
                ↑___________________|
                超过 3 轮 → 升级人工
```

---

## 八、Hermes 项目落地建议

### 8.1 已具备的组件

- ✅ `subagent-spawn` + `subagent-registry`（架构层）
- ✅ `MemoryService` 三层记忆（memory-model.md）
- ✅ `loop-engineering` skill（Builder/Checker/Evaluator 三角色）
- ✅ MCP 集成（src/hermes/mcp.py）
- ✅ 评估体系（skill_evaluator.py + batch_eval.py）

### 8.2 建议补充

| 优先级 | 借鉴项 | 实施方式 |
|--------|--------|---------|
| P0 | **Orchestrator 显式化** | 引入 `loop-engineering` 风格的 state machine，把 fan_out/fan_in 写成可审计的步骤 |
| P1 | **MCP 工具分舱** | sub-agent 配置文件加 `allowed_tools` 白名单，启动时校验 |
| P2 | **成本四道护栏** | LlmService 增加 token/cost counter，超阈值停止 |
| P3 | **GEPA 周期评估** | 每 N 个 multi-agent 任务跑一次，自动提取 skill |
| P4 | **双层评估** | 区分 sub-agent 评估和协作评估，分别给分 |

### 8.3 反模式（不要做）

- ❌ 让 Coder 也跑测试（角色串味，Tester 形同虚设）
- ❌ 共享所有 sub-agent 的对话历史（context 爆炸 + 立场污染）
- ❌ 给 Orchestrator 写权限（可以发指令但不能改文件，否则无法审计）
- ❌ 用同一个 LLM 跑所有 sub-agent（模型同质化偏置）
- ❌ 不设轮次上限（成本爆炸）

---

## 九、关键金句

1. **"Multi-Agent 不是为了让 AI 更聪明，而是为了让 AI 更克制。"** — 角色分离的本质是约束，不是增强。

2. **"Orchestrator 不写代码，Reviewer 不写测试。"** — 角色越权是 multi-agent 系统最大的腐败源。

3. **"共享记忆只写事实，不写观点。"** — 观点污染共识，事实支撑判断。

4. **"MCP 是工具总线，不是工具广场。"** — 必须有白名单，否则工具数量爆炸后系统不可用。

5. **"评估有两层：每个 AI 做得多好 + 它们协作得多好。"** — 只评个体不评协作，会优化出"个体优秀但协作崩溃"的系统。

---

## 十、参考文章清单

来自 IMA `AI知识库`（kb_id: `vau9Bw9VNIYY-ehw4jRHm8BYO9rxoNuDqSCmWL9SPHk=`）：

| 文章 | 主题 | 关联 |
|------|------|------|
| 从零设计生产级 Multi-Agent Harness：架构、评估、记忆、成本与 MCP 工具接入全拆解 | 多代理全栈 | 本文主干 |
| OpenClaw 多 Agent 协作研发：5 个 AI 员工，从需求到代码自动流转 | 5 角色模型 | §七 |
| WorkBuddy 专家团提示词全曝光：多 Agent 协作原来是这样产品化的 | 多 Agent 产品化 | §二 |
| 【智造】AI应用实战：6 个 agent 搞定复杂指令和工具膨胀 | 工具膨胀对策 | §六 |
| LLM Agent 6 大 plan 范式：CoT、ToT、GoT、ReAct、Plan-and-Execute、Reflexion | 推理范式选型 | §四 |
| ReAct 范式深度解析：从理论到 LangGraph 实践 | ReAct 实现 | §四 |
| AI Agents 上下文工程（Context Engineering）解析 | Context Engineering | §三 |
| 一文看懂 AI 智能体系统背后的重要技术——上下文工程 | Context Engineering 详解 | §三 |
| 阿里二面：说说 LLM Agent 6大 plan 范式 | 推理范式 | §四 |
| 不用手搓 SQL 验数了！阿里生产级端到端 Agent Skill 完整设计复盘 | Skill 端到端设计 | §六 |

> 数据获取说明：IMA OpenAPI 的 `search_knowledge` 返回的 `highlight_content` 和 `url` 字段对 wechat article 类型为空，`get_doc_content` 仅对 note 类型生效（对 wechat article 报 `GetNoteContent not author`）。本文以文章主题 + Hermes 现有架构 + 公开的 Multi-Agent 知识综合沉淀。如需补充原文细节，建议直接访问 IMA 知识库前端。

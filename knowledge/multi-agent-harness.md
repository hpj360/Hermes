# Multi-Agent Harness 提升项

> 来源：IMA `AI知识库` 4 篇 Multi-Agent 文章 + 项目代码对照
>
> 本文只记录**项目真实缺口**和**可落地提升项**，不重复已有架构描述。
> 已有能力见 [architecture.md](./architecture.md) 和 [harness-engineering.md](./harness-engineering.md)。

---

## 提升 1：MCP 工具按 sub-agent 角色分舱（P0，安全缺口）

### 现状

[mcp.py:222](file:///workspace/src/hermes/mcp.py#L222) 的 `MCP_REGISTRY` 是全局的，任何 sub-agent 都能调 `create_pr` / `post_pr_comment`。checker 虽然在 [loop.py:1350](file:///workspace/src/hermes/loop.py#L1350) 通过 `tools: Read, Grep, Glob, Bash` 做了文件级隔离，但 **MCP 工具没有白名单**。

### 风险

builder 可以直接调 `GitHubMCPClient.create_pr` 绕过 reviewer 人工检查合并代码。这在 L3 无人值守场景下是真实的安全漏洞。

### 落地方式

1. `AgentTask`（[orchestrator.py:78](file:///workspace/src/hermes/orchestrator.py#L78)）增加 `allowed_mcp_tools: list[str]` 字段
2. `Orchestrator.fan_out`（[orchestrator.py:284](file:///workspace/src/hermes/orchestrator.py#L284)）spawn 时传入白名单
3. `OpenClawClient.spawn_agent`（[orchestrator.py:187](file:///workspace/src/hermes/orchestrator.py#L187)）把白名单写入 payload
4. 角色默认白名单：
   - builder: `["github.get_pr", "github.list_prs"]`（只读）
   - checker: `[]`（无 MCP）
   - synthesizer: `[]`（无 MCP）

---

## 提升 2：sub-agent 级别的 token 上限 + 熔断（P1，成本控制）

### 现状

[loop.py:1636](file:///workspace/src/hermes/loop.py#L1636) 只有 **loop 级别**的 `budget_limit_tokens`，没有 **per-agent token 上限**。一个失控的 builder 可以耗尽整个 loop 的预算。

### 缺口

multi-agent 系统需要四道护栏，项目目前只有两道：

| 护栏 | 项目现状 |
|------|---------|
| 总成本上限 | ✅ `budget_limit_tokens` + `BUDGET_EXCEEDED` |
| 轮次上限 | ✅ `max_rounds` + `rounds_exhausted` 停止规则 |
| **单 Agent token 上限** | ❌ 缺失 |
| **重复模式熔断** | ⚠️ loop 级有 `same_failure_twice`，sub-agent 级无 |

### 落地方式

1. `AgentTask` 增加 `token_limit: int` 字段（默认 50000）
2. `Orchestrator.fan_in`（[orchestrator.py:324](file:///workspace/src/hermes/orchestrator.py#L324)）检查 `task.tokens_used > task.token_limit`，超限标记 `status=failed`
3. 增加 `agent_failure_count: dict[str, int]` 到 `LoopState`，同一 sub-agent 失败 2 次后跳过该角色，启用兜底

---

## 提升 3：multi-agent 协作评估指标（P2，可观测性）

### 现状

[loop.py:1029](file:///workspace/src/hermes/loop.py#L1029) 的 `loop_metrics` 只有轮次/通过率/token，没有 multi-agent 专属指标。无法回答"角色串味率多少""端到端成功率多少"。

### 缺口

multi-agent 系统的健康度不只是"任务完成没有"，还包括协作质量。当前缺少：

| 指标 | 含义 | 项目现状 |
|------|------|---------|
| `role_violation_count` | builder 调了 checker 工具的次数 | ❌ |
| `end_to_end_success_rate` | 完整任务从输入到输出达成目标的比率 | ❌ |
| `avg_rounds_per_task` | 平均调度轮次 | ✅ `current_round`（但不聚合） |
| `agent_failure_distribution` | 各 sub-agent 失败次数分布 | ❌ |

### 落地方式

1. `loop_metrics`（[loop.py:1029](file:///workspace/src/hermes/loop.py#L1029)）增加上述字段
2. `record_round`（[loop.py:1614](file:///workspace/src/hermes/loop.py#L1614)）统计 `agent_failure_distribution`
3. 角色违规检测：在 `fan_out` 时记录每个 task 的 `allowed_tools`，`fan_in` 后扫描 `task.result` 中是否出现违规工具调用

---

## 提升 4：GEPA 周期性自进化（P3，工作量大但价值高）

### 现状

项目完全没有。每次 multi-agent 任务结束后不会自动提取可复用模式。

### 价值

[harness-engineering.md](./harness-engineering.md) §六已沉淀理论（每 ~15 次工具调用后评估、提取 skill），但没有代码实现。GEPA 能让 multi-agent 系统越跑越快——20+ 自生成技能的 Agent 完成相似任务速度提升 40%。

### 落地方式

1. 在 `record_round`（[loop.py:1614](file:///workspace/src/hermes/loop.py#L1614)）后增加 `_maybe_extract_skill(rounds)` 钩子
2. 达到阈值（如累计 15 次工具调用）时触发评估
3. 评估流程复用 [skills/skill-creator/](file:///workspace/skills/skill-creator/) 的现有能力
4. 提取的 skill 写入 Skill Sync 中心仓库

**注意**：工作量较大，建议作为独立 feature 规划，不混入日常迭代。

---

## 不做的事（避免无意义沉淀）

以下内容在 IMA 文章中出现，但**项目已实现或不采用**，不再沉淀：

| 主题 | 原因 |
|------|------|
| 五元角色模型（Planner/Researcher/Coder/Reviewer/Tester） | 项目采用 builder-checker 两角色 + multi-perspective N+1 角色，不采用五角色 |
| OpenClaw 5 AI 员工模型 | 这是另一篇文章的产品描述，Hermes 是控制平面不是 5 员工模型 |
| 双层 Memory（共享 + 角色私有） | memory.py 已实现 L1/L2/L3 三层，角色私有记忆无落地路径 |
| 已具备组件清单 | architecture.md 和 harness-engineering.md 已覆盖 |
| 文章索引清单 | 维护成本 > 参考价值，不属于知识沉淀 |

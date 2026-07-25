# Multi-Agent Harness 提升项

> 来源：IMA `AI知识库` 4 篇 Multi-Agent 文章 + 项目代码对照
>
> 本文只记录**项目真实缺口**和**可落地提升项**，不重复已有架构描述。
> 已有能力见 [architecture.md](./architecture.md) 和 [harness-engineering.md](./harness-engineering.md)。

---

## 提升 1：MCP 工具按 sub-agent 角色分舱（P0，安全缺口）✅ 已实现

### 现状（已修复）

[mcp.py:222](file:///workspace/src/hermes/mcp.py#L222) 的 `MCP_REGISTRY` 是全局的，任何 sub-agent 都能调 `create_pr` / `post_pr_comment`。checker 虽然在 [loop.py:1350](file:///workspace/src/hermes/loop.py#L1350) 通过 `tools: Read, Grep, Glob, Bash` 做了文件级隔离，但 **MCP 工具没有白名单**。

### 风险（已消除）

builder 可以直接调 `GitHubMCPClient.create_pr` 绕过 reviewer 人工检查合并代码。这在 L3 无人值守场景下是真实的安全漏洞。

### 实现内容（commit 6704759）

1. `AgentTask` 增加 `allowed_mcp_tools: list[str] | None` + `mcp_violations: list[str]` 字段
2. `ROLE_MCP_WHITELIST` 角色默认白名单（[orchestrator.py:83](file:///workspace/src/hermes/orchestrator.py#L83)）：
   - builder: `["github.get_pr", "github.list_prs", "github.get_issue"]`（只读）
   - checker/synthesizer: `[]`（禁止所有 MCP）
3. `fan_out` 自动按 role 填充白名单（`_prepare_and_spawn`）
4. `spawn_agent` 增加 `allowed_tools` 参数，传入 Gateway payload
5. `fan_in` 后 `_audit_mcp_violations` 审计：
   - 扫描 `tool_calls` 字段（OpenAI 格式）
   - 扫描 content 中的 `github.<method>` 模式（兜底）
6. `RoundResult` 增加 `role_violation_count`（P2 可观测性前置）
7. 19 个测试用例覆盖白名单填充 + 违规检测

---

## 提升 2：sub-agent 级别的 token 上限 + 熔断（P1，成本控制）✅ 已实现

### 现状（已修复）

[loop.py:1636](file:///workspace/src/hermes/loop.py#L1636) 只有 **loop 级别**的 `budget_limit_tokens`，没有 **per-agent token 上限**。一个失控的 builder 可以耗尽整个 loop 的预算。

### 缺口（已补齐）

multi-agent 系统需要四道护栏，项目目前四道均已具备：

| 护栏 | 项目现状 |
|------|---------|
| 总成本上限 | ✅ `budget_limit_tokens` + `BUDGET_EXCEEDED` |
| 轮次上限 | ✅ `max_rounds` + `rounds_exhausted` 停止规则 |
| **单 Agent token 上限** | ✅ `AgentTask.token_limit` + `fan_in` 超限标记 failed |
| **重复模式熔断** | ✅ loop 级 `same_failure_twice` + sub-agent 级 `agent_failure_counts` 熔断 |

### 实现内容

1. `AgentTask.token_limit: int = 50000`（[orchestrator.py:130](file:///workspace/src/hermes/orchestrator.py#L130)），0=不限制（向后兼容）
2. `Orchestrator.fan_in` 检查 `task.tokens_used > task.token_limit`，超限标记 `status=failed`
3. `LoopState.agent_failure_counts: dict[str, int]` 跟踪角色连续失败次数（[loop.py](file:///workspace/src/hermes/loop.py)）
4. `AGENT_FAILURE_THRESHOLD` 常量定义熔断阈值，`get_tripped_roles` 暴露已熔断角色
5. `_update_failure_counts` 据本轮 `agent_status` 更新累计计数，下轮自动跳过熔断角色

---

## 提升 3：multi-agent 协作评估指标（P2，可观测性）✅ 已实现

### 现状（已修复）

[loop.py:1029](file:///workspace/src/hermes/loop.py#L1029) 的 `loop_metrics` 只有轮次/通过率/token，没有 multi-agent 专属指标。无法回答"角色串味率多少""端到端成功率多少"。

### 缺口（已补齐）

multi-agent 系统的健康度不只是"任务完成没有"，还包括协作质量：

| 指标 | 含义 | 项目现状 |
|------|------|---------|
| `role_violation_count` | builder 调了 checker 工具的次数 | ✅ `RoundResult.role_violation_count` + `_audit_mcp_violations` |
| `end_to_end_success_rate` | 完整任务从输入到输出达成目标的比率 | ✅ 由 `roles_completed` / `roles_failed` 推导 |
| `avg_rounds_per_task` | 平均调度轮次 | ✅ `current_round` + STATE.md 聚合 |
| `agent_failure_distribution` | 各 sub-agent 失败次数分布 | ✅ `failure_attribution_counts` 累计 |
| `checker_builder_agreement` | checker 是否认同 builder 成功声明 | ✅ `collaboration_metrics.checker_builder_agreement` |
| `failure_attribution` | builder / checker / mixed / none 归因 | ✅ `collaboration_metrics.failure_attribution` |

### 实现内容

1. `RoundResult.collaboration_metrics: dict[str, Any]`（[orchestrator.py:176](file:///workspace/src/hermes/orchestrator.py#L176)）
2. `_compute_collaboration_metrics` 在 `aggregate_results` 中计算 token_by_role / failure_attribution / checker_builder_agreement / roles_completed / roles_failed
3. `LoopState` 新增累计指标字段：`total_role_violations` / `total_tokens_by_role` / `failure_attribution_counts`
4. `_accumulate_collaboration_metrics` 每轮累计，`_update_state_md` 渲染到 STATE.md
5. `LoopRound.collaboration_metrics` 快照每轮指标，随 meta 持久化供跨会话追溯

---

## 提升 4：GEPA 周期性自进化雏形（P3，工作量大但价值高）✅ 已实现（雏形）

### 现状（已修复）

项目原本完全没有自进化能力。每次 multi-agent 任务结束后不会自动提取可复用模式。

### 价值

[harness-engineering.md](./harness-engineering.md) §六已沉淀理论（每 ~15 次工具调用后评估、提取 skill），但没有代码实现。GEPA 能让 multi-agent 系统越跑越快——20+ 自生成技能的 Agent 完成相似任务速度提升 40%。

### 实现内容（[src/hermes/gepa.py](file:///workspace/src/hermes/gepa.py)）

1. 数据模型：`Variant` / `VariantResult` / `GEPAExperiment` 三个 dataclass，均带 `to_dict` / `from_dict` 往返序列化
2. 评分函数 `score_variant`：加性模型，优先级 success >> tokens >> rounds
   - `SCORE_WEIGHT_SUCCESS=20000` 显式 sizing：覆盖最坏情况惩罚包络（1M tokens × 0.01 + 100 rounds × 50 = 15000），留 5000 安全裕度
   - 失败 variant 仍可排序（用于调试），但任何成功 variant 严格优于任何失败 variant
3. 周期编排 `run_gepa_cycle`：
   - 调用方提供 `evaluate_fn`（解耦 Orchestrator 内部，可单测）
   - 单 variant 崩溃不阻断整个 cycle（隔离 + 记录为 failed + error）
   - 保守提升策略：所有 variant 失败时 `winner_id=None`
4. 持久化：`save_experiment` / `load_experiment` / `list_experiments` / `get_latest_promotion`
   - `.gepa/<experiment_id>.json` 审计轨迹（永不覆盖）
   - `list_experiments` 跳过损坏 JSON（容错）
   - 按 `created_at` 降序排序
5. 26 个测试覆盖：序列化往返、评分优先级、cycle 编排、崩溃隔离、持久化、端到端流程

### 雏形边界（未来工作）

- variant 生成目前是手动的（调用方提供 variants）
- 未集成到 `record_round` 钩子（需后续 wire-up）
- 未实现 LLM 驱动的变体生成
- 未实现跨项目 promotion

**注意**：上述未来工作作为独立 feature 规划，不混入日常迭代。当前雏形已建立可审计的自进化框架，为后续迭代提供基础。

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

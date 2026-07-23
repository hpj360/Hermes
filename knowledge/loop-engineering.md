# Loop Engineering 在 Hermes 中的实现

> 参考文章：cobusgreyling/loop-engineering "Agent Loop 与 Loop Engineering 区别"
>
> 与 skills/loop-engineering/SKILL.md（面向 LLM 的技能文档）不同，本文档面向开发者，解释 Hermes 如何落地 Loop Engineering。

## 核心区别：Agent Loop vs Loop Engineering

| 概念 | 是什么 | Hermes对应 |
|------|--------|-----------|
| **Agent Loop** | Agent工具里的递归执行原语，按固定节奏反复调用Agent | LLM对话中的循环执行（隐式） |
| **Loop Engineering** | 围绕Agent Loop展开的系统设计方法论 | `hermes loop` CLI + 脚手架 + 审计 + 内置模式 |

Loop Engineering的核心目标：**让循环从"瞎跑"变成"可验证、可控制、可观测"**。

## 六大构件在Hermes中的实现

| 构件 | 说明 | Hermes实现 |
|------|------|-----------|
| **Automations/Scheduling** | 心跳触发（时间驱动或事件驱动） | `loop run` 手动触发（cron调度可由外部crontab实现） |
| **Worktrees** | 并行隔离 | 每轮写入STATE.md，不做git worktree（保持简单） |
| **Skills** | Agent可调用的工具/流程 | Skill Sync中心仓库 + `hermes skill-sync` 管理 |
| **MCP Connectors** | 外部工具连接 | 配置文件驱动的MCP服务器注册 |
| **Sub-agents** | Maker/Checker分离 | LOOP.md中定义Planner/Generator/Evaluator三角色 |
| **Memory/State** | 跨轮持久化 | `.loops/<name>/STATE.md` + `loop-budget.md` + `meta.json` |

## 分阶段上线（L1 → L2 → L3）

Hermes强制每个loop从L1开始，必须通过audit（就绪度≥70分）才能升级到L2，≥85分才能升级到L3：

| 阶段 | 能力 | 风险 | audit要求 |
|------|------|------|----------|
| **L1 Report** | 只扫描报告，不做任何修改 | 零风险 | 初始默认 |
| **L2 Assist** | 小步自动修复 + 独立Verifier验证 | 低风险 | score ≥ 70 |
| **L3 Autonomous** | 无人值守自动执行 | 高风险（需denylist） | score ≥ 85 |

升级命令：`hermes loop advance <name>`，会自动检查audit分数，不达标会阻止升级并给出修复建议。

## 目标四步框架（防古德哈特定律）

每个loop在LOOP.md中必须定义四件事：

1. **完成标准（可机器验证）**：什么叫"做完了"？必须有可执行的验证命令（如`pytest`、`ruff check`），而不是"看起来没问题"
2. **边界条件（Harness约束）**：不能做什么？denylist路径、禁止删除、禁止修改敏感配置
3. **降级方案（失败怎么办）**：max_rounds轮后仍未完成 → 列出未解决项交给用户
4. **目标分层**：全局约束（不破坏现有功能）vs 当前任务目标

## Maker/Checker 分离原则

**铁律：写代码的不验代码。**

- **Planner**：读取STATE.md和LOOP.md，生成本轮执行计划
- **Generator**：执行具体任务（一次一个小步骤）
- **Evaluator**：独立角色，只看结果和验证命令，不知道Generator是谁，给出"通过/未通过"

Hermes的LOOP.md模板内置了三角色定义。Evaluator禁止自评：如果Generator自己说"我改好了"，不算通过，必须跑验证命令。

## 三笔债（Three Debts）

Loop Engineering长期运行会积累三笔债，knowledge-hygiene模式专门检测这些：

| 债务 | 表现 | 解决方案 |
|------|------|---------|
| **Intent Debt** | AGENTS.md没有项目约定、LOOP.md有TODO、目标模糊 | `hermes loop audit` 检测 + knowledge-hygiene扫描 |
| **Comprehension Debt** | 文档过时、重复skill、manifest和实际不一致 | knowledge-hygiene L1报告，L2自动标记 |
| **Cognitive Surrender** | 盲目信任L3自动修复，不再审查结果 | budget限制 + 强制L1起步 + audit门控 |

## 内置Loop模式

| 模式 | 用途 | 默认阶段 | 频率 |
|------|------|---------|------|
| `daily-triage` | 每天扫描问题、分类优先级 | L1 | 每天 |
| `knowledge-hygiene` | 清理知识库、检测三笔债 | L1 | 每周 |
| `ci-sweeper` | 监控CI失败、修复flaky test | L1 | 每次CI |
| `pr-babysitter` | 盯PR状态、处理review反馈 | L1 | PR生命周期 |

## CLI命令参考

```bash
# 查看内置模式
hermes loop patterns

# 创建loop（从内置模式或自定义）
hermes loop init <name> [-p <pattern>]

# 查看所有loop状态
hermes loop list

# 就绪度审计（评分0-100）
hermes loop audit [name]

# 成本估算
hermes loop budget <name>

# 升级阶段（L1→L2→L3，有门控）
hermes loop advance <name>

# 执行一轮
hermes loop run <name>
```

## 文件结构

每个loop创建后在 `.loops/<name>/` 下生成三个文件：

```
.loops/kb-cleanup/
├── LOOP.md         # Loop配置：目标、边界、Maker/Checker分工、denylist
├── STATE.md        # 跨轮状态：High Priority、Watch List、执行历史
├── loop-budget.md  # 成本预算：token限制、成本护栏、运行日志
└── meta.json       # 机器可读状态：当前阶段、轮次、预算消耗
```

## 与Skill Sync的关系

- **Skill Sync** 解决"skill多Agent分发"问题 → 空间维度的管理
- **Loop Engineering** 解决"任务反复执行"问题 → 时间维度的管理
- 两者互补：Skill Sync确保每个Agent都有最新的skill；Loop Engineering确保反复执行的任务有结构、有验证、有边界

## 防坑要点

1. **永远从L1开始**：新loop先跑一周L1只报告，确认误报率低了再升L2
2. **Evaluator必须独立**：不能让同一个LLM既写代码又验收
3. **denylist要完整**：L3之前必须列出所有高风险路径
4. **预算硬限制**：达到budget自动停止，不能无限跑
5. **max_rounds要小**：3-5轮，超过就降级给人，防止死循环

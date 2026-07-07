# Hermes 技术方案架构文档

> 版本: 0.3.0 | 更新日期: 2026-06-26

## 一、项目定位

Hermes 是一个独立的 Agent 基础设施管理 CLI，定位为 **OpenClaw 的控制平面和方法论层**。

| Hermes 是 | Hermes 不是 |
|-----------|------------|
| Skill 分发中心（类 Nacos 配置中心） | LLM 调用引擎 |
| Loop Engineering 脚手架 + 执行编排器 | Agent 沙箱隔离运行时 |
| 质量审计工具（0-100 评分门控） | Sub-Agent 生命周期管理器 |
| 环境配置继承层 | 消息队列 / 事件总线 |
| 方法论沉淀层（7 篇 knowledge 文档） | 数据库驱动系统 |

**核心原则**: 做项目经理，不做工人——Hermes 负责编排和质量门禁，OpenClaw 负责执行和隔离。

---

## 二、系统架构总览图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          用户 (CLI)                                      │
│                    hermes <command> [subcommand]                        │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        main.py (CLI 入口)                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  │  start   │ │  doctor  │ │  config  │ │  profile │ │  skills  │      │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘      │
│  ┌──────────────────┐  ┌────────────────────────────────────────┐      │
│  │  skill-sync      │  │  loop (list/init/audit/run/continuous/  │      │
│  │  (status/add/    │  │       resume/logs/status/stop-rules)    │      │
│  │   sync/resolve)  │  └────────────────────────────────────────┘      │
│  └──────────────────┘                                                   │
└──────┬──────────┬──────────┬──────────┬──────────┬─────────────────────┘
       │          │          │          │          │
       ▼          ▼          ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐
│ config.py│ │ skills.py│ │profile.py│ │ loop.py  │ │   runner.py      │
│          │ │          │ │          │ │          │ │  ┌────────────┐  │
│ Settings │ │ SkillSync│ │ Profile  │ │ Loop引擎 │ │  │orchestrator│  │
│ get_sett │ │ discover │ │ render   │ │ StopRules│ │  │    .py     │  │
│ bootstrap│ │ sync/fix │ │ update   │ │ audit    │ │  └─────┬──────┘  │
└────┬─────┘ └────┬─────┘ └──────────┘ └────┬─────┘ └───────┼─────────┘
     │            │                        │                 │
     │            │                        │                 ▼
     │            │                        │        ┌──────────────────┐
     │            │                        │        │ orchestrator.py  │
     │            │                        │        │ OpenClawClient   │
     │            │                        │        │ Orchestrator     │
     │            │                        │        │ fan_out/fan_in   │
     │            │                        │        └────────┬─────────┘
     │            │                        │                 │
     ▼            ▼                        ▼                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        文件系统 (状态持久化)                           │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌─────────┐  ┌───────────┐ │
│  │ .env    │  │ skills/  │  │.state/  │  │ .loops/ │  │ knowledge/│ │
│  │ config  │  │ 中心仓库 │  │sync.json│  │ meta.json│  │ 7篇文档   │ │
│  └─────────┘  └──────────┘  └─────────┘  │ STATE.md │  └───────────┘ │
│                                          │ LOOP.md  │                │
│                                          │builder.md│                │
│                                          │checker.md│                │
│                                          └─────────┘                │
└──────────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼ (Gateway可用时)
                              ┌──────────────────────────┐
                              │   OpenClaw Gateway        │
                              │   localhost:18789         │
                              │   ┌────────────────────┐  │
                              │   │ subagent.spawn()   │  │
                              │   │ sessions_send()    │  │
                              │   │ sessions_history() │  │
                              │   │ sandbox isolation  │  │
                              │   └────────────────────┘  │
                              └──────────────────────────┘
```

---

## 三、模块依赖关系图

```
                    ┌─────────────┐
                    │  config.py  │ ← 最底层（配置基座）
                    │  Settings   │
                    └──────┬──────┘
           ┌───────────┬───┴────┬──────────┐
           │           │        │          │
           ▼           ▼        ▼          ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
    │logging.py│ │skills.py │ │profile.py│ │ loop.py  │
    │          │ │SkillSync │ │ Profile  │ │ Loop引擎 │
    └──────────┘ └──────────┘ └──────────┘ │ StopRules│
                                         └─────┬────┘
                                               │
                                               ▼
                                         ┌──────────────┐
                                         │orchestrator │ ← 控制平面
                                         │    .py      │
                                         │OpenClawClient│
                                         │ Orchestrator │
                                         └──────┬───────┘
                                                │
                                                ▼
                                         ┌──────────────┐
                                         │  runner.py   │ ← 执行引擎
                                         │  run_loop()  │
                                         │  continuous()│
                                         │  resume()    │
                                         └──────┬───────┘
                                                │
                                                ▼
                                         ┌──────────────┐
                                         │   main.py    │ ← CLI 入口
                                         │  argparse    │
                                         │  13 commands │
                                         └──────────────┘
```

**分层原则**:
- **L0 基座**: `config.py` — 所有模块的配置来源
- **L1 中间层**: `logging.py` / `skills.py` / `profile.py` / `loop.py` — 各自独立的功能模块
- **L2 编排层**: `orchestrator.py` — 依赖 config，提供 Sub-Agent 调度
- **L3 执行层**: `runner.py` — 桥接 loop + orchestrator，驱动循环执行
- **L4 入口层**: `main.py` — CLI 解析和命令分发

---

## 四、核心数据流

### 4.1 Loop 执行流（builder-checker 模式）

```
用户: hermes loop run fix-bugs
  │
  ▼
runner.run_loop("fix-bugs")
  │
  ├── 1. 检查预算 (check_budget)
  │      └── 80% 预警 / 100% 硬停止
  │
  ├── 2. 检查状态 (COMPLETED? BUDGET_EXCEEDED?)
  │
  ├── 3. 分发到 pattern 执行器
  │      └── _run_builder_checker()
  │
  ▼
orchestrator.run_builder_checker_round()
  │
  ├── Phase 1: Builder
  │   ├── fan_out([builder])          ← spawn_agent(builder.md)
  │   ├── fan_in([builder])           ← wait_for_completion(session_id)
  │   └── builder.result = "改了什么/文件/检查结果"
  │
  ├── Phase 2: Checker (并行 Fan-out)
  │   ├── fan_out([checker_lint, checker_type, checker_test])  ← 同时 spawn 3 个
  │   ├── fan_in([checker_lint, checker_type, checker_test])   ← 等待全部完成
  │   └── 各 checker.result = "ALL GREEN" 或 "FAILED + file:line 详情"
  │
  └── aggregate_results()  ← "不过滤"原则：原样拼接 checker 报告
      │
      ▼
LoopRound 构建
  │
  ├── record_round()
  │   ├── 更新 meta.json (rounds 列表持久化)
  │   ├── 更新 STATE.md (人类可读摘要)
  │   ├── 更新 budget_used_tokens
  │   └── 更新 status (COMPLETED/NEEDS_HUMAN/RUNNING)
  │
  └── check_stop_rules()  ← 7 条规则依次检查
      ├── Rule 1: ALL GREEN → 停止成功
      ├── Rule 2: 轮次用尽 → 升级
      ├── Rule 3: 预算耗尽 → 升级（record_round 状态机处理）
      ├── Rule 4: 超出能力边界 → 升级
      ├── Rule 5: 回归 → 升级
      ├── Rule 6: 同一失败连续两轮 → 升级
      └── Rule 7: 无实质进展 → 升级
```

### 4.2 Gateway 降级流

```
Orchestrator.is_available()
  │
  ├── True → orchestrated 模式
  │          └── 实际 spawn agent、收集结果
  │
  └── False → guidance 模式 (graceful degradation)
             └── 返回 agent 文件路径 + 执行指引
                 用户手动执行，零阻塞
```

### 4.3 Skill Sync 分发流

```
hermes skill-sync add wechat-reader
  │
  ├── 1. 从 source/central 导入到 skills/wechat-reader/
  │
  ├── 2. 计算中心仓库 SHA256 哈希
  │
  ├── 3. 分发到所有已发现的 Agent 目录:
  │      ├── ~/.codex/skills/wechat-reader → symlink 或 copy
  │      ├── ~/.claude-code/skills/wechat-reader → symlink 或 copy
  │      ├── ~/.cursor/skills/wechat-reader → symlink 或 copy
  │      ├── ~/.openclaw/skills/wechat-reader → symlink 或 copy
  │      └── ... (12 个已知目录 + 自定义)
  │
  └── 4. 记录状态到 .state/skill_sync.json
         └── { managed_skills: { "wechat-reader": { central_hash, agents, mode } } }
```

---

## 五、Loop Engineering 架构

### 5.1 三阶段自治模型

```
┌─────────────────────────────────────────────────────────┐
│                    L1: 只报告 (Report)                   │
│  ┌─────────────────────────────────────────────────┐    │
│  │ • Agent 只扫描和报告，不做任何修改               │    │
│  │ • 零成本（本地执行，不调用 LLM）                 │    │
│  │ • 人工审查报告后决定下一步                       │    │
│  └─────────────────────────────────────────────────┘    │
│                    audit score ≥ 70                      │
├─────────────────────────────────────────────────────────┤
│                    L2: 辅助修复 (Assist)                 │
│  ┌─────────────────────────────────────────────────┐    │
│  │ • Builder 写代码，Checker 独立验证               │    │
│  │ • 工具级硬隔离（Checker 无 Write/Edit）          │    │
│  │ • 循环到 ALL GREEN 或停止条件触发                │    │
│  │ • 成本可控（预算 + 轮次上限）                    │    │
│  └─────────────────────────────────────────────────┘    │
│                    audit score ≥ 85                      │
├─────────────────────────────────────────────────────────┤
│                    L3: 无人值守 (Autonomous)             │
│  ┌─────────────────────────────────────────────────┐    │
│  │ • 自动循环 + 自动提 PR                          │    │
│  │ • 需要 denylist 和严格停止规则                   │    │
│  │ • 预算硬停止 + 轮次上限                          │    │
│  │ • 7 条停止规则全部生效                           │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 5.2 七条停止规则

| # | 规则 | 触发条件 | 动作 |
|---|------|---------|------|
| 1 | ALL GREEN | 最新一轮 `passed=True` | `stop_success` |
| 2 | 轮次用尽 | `current_round >= max_rounds` | `stop_escalate` |
| 3 | 预算耗尽 | `budget_used_tokens >= budget_limit_tokens`（由 record_round 状态机处理） | `stop_escalate` |
| 4 | 超出能力边界 | 失败信息匹配16个环境问题信号词 | `stop_escalate` |
| 5 | 回归 | 有新失败 + 有已修复 + 有持续失败 | `stop_escalate` |
| 6 | 同一失败连续两轮 | 连续两轮有交集失败项 AND 失败数未减少 | `stop_escalate` |
| 7 | 无实质进展 | 连续2轮失败数未减少 AND 失败集合完全更换 | `stop_escalate` |

### 5.3 内置 Loop 模式

| 模式 | 默认阶段 | 最大轮次 | Sub-Agent 配置 | 并行 |
|------|---------|---------|----------------|------|
| daily-triage | L1 | 3 | scanner | 否 |
| knowledge-hygiene | L1 | 2 | manifest/skill/knowledge scanner × 3 | 是 |
| ci-sweeper | L1 | 3 | ci_monitor + builder + checker | 否 |
| pr-babysitter | L1 | 5 | pr_monitor | 否 |
| issue-triage | L1 | 3 | issue_scanner + duplicate_detector + label_suggester | 是 |
| changelog-draft | L1 | 2 | commit_classifier + pr_summarizer | 是 |
| builder-checker | L2 | 5 | builder + checker_lint/type/test × 3 | 是 |

### 5.4 就绪度审计（10 项检查，满分 100）

| 检查项 | 权重 | 说明 |
|--------|------|------|
| STATE.md 存在 | 8 | 跨会话状态跟踪 |
| LOOP.md 有完成标准 | 15 | 可机器验证的完成条件 |
| 有 Harness 边界 | 10 | 防止古德哈特定律 |
| 使用 L1 阶段 | 8 | 保守起步 |
| 有降级方案 | 8 | 失败时的处理计划 |
| 预算已配置 | 8 | 防止成本失控 |
| Maker/Checker 分离 | 10 | 生成与评判分离 |
| 最大轮次已设 | 8 | 3-10 轮 |
| 7 条停止规则 | 12 | 全部定义 |
| 工具级隔离 | 13 | checker 无 Write/Edit |

### 5.5 吴恩达三层 Loop 对照（Andrew Ng 框架）

参考 [Cobus Greyling loop-engineering](https://github.com/cobusgreyling/loop-engineering) 引用的吴恩达观点："做产品需要三层 Loop"，与 Hermes 的对应关系：

| 层次 | 频率 | 吴恩达定义 | Hermes 对应 | 停止条件 |
|------|------|------------|------------|---------|
| **L₀ Agent 编码 Loop**（最内层） | 分钟级 | Agent 写代码 + 自我测试 | `builder-checker` 单轮内的 3 个并行 checker（lint/type/test，[runner.py L255-310](file:///workspace/src/hermes/runner.py#L255-L310)） | 单个 checker 失败 |
| **L₁ 开发者反馈 Loop**（中层） | 小时级 | Agent 跑一轮，人审查后给反馈 | 完整一轮（builder + 3 checker）→ `resume_loop` 接收人类反馈重跑 | 7 条停止规则中的 same_failure_twice / no_progress / regression |
| **L₂ 外部反馈 Loop**（最外层） | 天/周级 | 用户/Alpha测试反馈 + A/B测试 | 整个 loop 周期（默认 5 轮），由 L1→L2→L3 阶段升级决定何时升级给人 | rounds_exhausted / budget_exceeded → `stop_escalate` |

**关键共识**（与 [knowledge/working-principles.md](file:///workspace/knowledge/working-principles.md) 规则一"第一性原理"一致）：吴恩达认为"什么算完成还得靠人看"——这正是 LOOP.md"完成标准"审计权重最高（15/100）的根因。Loop 自动化的是"执行"，完成定义权永远在人类。

### 5.6 对齐 Cobus Greyling 框架的能力补齐

参考 loop-engineering 的 7 套内置工作流 + 4 步 CLI 流程，Hermes 已实现的能力与差距：

| 能力维度 | Cobus Greyling | Hermes | 状态 |
|---------|---------------|--------|------|
| 7 套工作流 | 7 | 7（新增 issue-triage + changelog-draft） | ✅ 已对齐 |
| 交互式选择器 | ✓ | `hermes loop init --interactive` / `--from-pain-point` | ✅ 已补齐 |
| Token 成本估算 | `loop-cost` | `hermes loop cost`（`budget` 仍为别名） | ✅ 已对齐 |
| 审计评分 + 徽章 | `loop-audit --badge` | `hermes loop audit --badge` | ✅ 已补齐 |
| 8 步标准流程 | ✓ | 7 条停止规则替代（更具体） | ✅ 升级而非简单对齐 |

---

## 六、Orchestrator 架构（Sub-Agent 编排）

### 6.1 控制平面设计

```
┌─────────────────────────────────────────────────────────┐
│                    Hermes (控制平面)                      │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Orchestrator                        │    │
│  │                                                  │    │
│  │  fan_out(tasks) ──→ 并行 spawn agents           │    │
│  │       │                                          │    │
│  │       ▼                                          │    │
│  │  fan_in(tasks) ──→ 等待全部完成，收集结果        │    │
│  │       │                                          │    │
│  │       ▼                                          │    │
│  │  aggregate_results() ──→ "不过滤"原则聚合        │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         │                               │
│  ┌──────────────────────┴──────────────────────────┐    │
│  │           OpenClawClient (HTTP)                  │    │
│  │                                                  │    │
│  │  spawn_agent() → POST /api/subagent/spawn       │    │
│  │  wait_for_completion() → GET /api/sessions/{id} │    │
│  │  get_session_messages() → GET /api/sessions/...  │    │
│  │  send_message() → POST /api/sessions/{id}/send  │    │
│  │  health_check() → GET /api/health               │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         │                               │
└─────────────────────────┼───────────────────────────────┘
                          │ HTTP (localhost:18789)
                          ▼
┌─────────────────────────────────────────────────────────┐
│                OpenClaw Gateway (执行平面)               │
│                                                         │
│  • LLM 调用（13+ provider）                             │
│  • 沙箱隔离（writablePaths 控制）                       │
│  • Sub-Agent 生命周期管理                                │
│  • 工具注册表 + 权限模型                                 │
│  • 记忆系统（L1/L2/L3）                                  │
│  • Hook 系统（Gateway + Plugin 双层）                    │
│  • 22 个消息渠道集成                                     │
│  • Compaction / 上下文管理                               │
└─────────────────────────────────────────────────────────┘
```

### 6.2 Fan-out / Fan-in 模式

```
                    ┌─────────────┐
                    │  Builder    │ ← 串行（先写代码）
                    │  (Write/Edit)│
                    └──────┬──────┘
                           │ 完成
                           ▼
        ┌──────────┬───────┴───────┬──────────┐
        │          │               │          │  ← 并行 Fan-out
        ▼          ▼               ▼          ▼
   ┌─────────┐┌─────────┐    ┌─────────┐
   │Checker  ││Checker  │    │Checker  │  ← 同时跑3种检查
   │  lint   ││  type   │    │  test   │
   │(无Write)││(无Write)│    │(无Write)│
   └────┬────┘└────┬────┘    └────┬────┘
        │          │               │
        └──────────┴───────┬───────┘  ← Fan-in 聚合
                           │
                           ▼
                    ┌─────────────┐
                    │ aggregate   │ ← 原样拼接 checker 报告
                    │ (不过滤)    │    不解读、不总结
                    └─────────────┘
```

---

## 七、文件系统状态模型

```
.loops/<loop-name>/
├── meta.json          ← 机器可读状态（全部 round 历史、预算、状态）
├── LOOP.md            ← 循环配置（目标/边界/Maker-Checker/停止规则）
├── STATE.md           ← 人类可读状态摘要（自动生成）
├── loop-budget.md     ← 预算跟踪（限制/已用/预警线）
├── builder.md         ← Builder Agent 定义（tools: Read,Write,Edit,Glob,Grep,Bash）
├── checker.md         ← Checker Agent 定义（tools: Read,Grep,Glob,Bash — 无Write/Edit）
└── stop-rules.md      ← 七条停止条件详细说明

.state/
└── skill_sync.json    ← Skill Sync 状态（managed_skills + custom_agents）

.cache/                 ← 缓存目录
data/
└── profile.json       ← 用户画像（version 4, 15个区块）
```

---

## 八、CLI 命令全景

```
hermes
├── start                          # 默认：打印启动信息
├── doctor                         # 环境健康检查
├── config show                    # 显示当前配置
├── skills list                    # 列出已安装 skills
├── knowledge list                 # 列出知识文档
├── profile show [--json]          # 显示用户画像
│
├── skill-sync                     # Skill Sync 管理
│   ├── status                     #   同步状态总览
│   ├── agents                     #   列出发现的 Agent 目录
│   ├── add [skill] [--all] [--source] [--copy]  # 添加到同步管理
│   ├── remove [skill] [--all]     #   移除同步管理
│   ├── sync [skill]               #   推送变更到所有 agent
│   ├── resolve <skill> --source   #   解决冲突
│   └── add-agent <name> <path>    #   注册自定义 agent 目录
│
└── loop                           # Loop Engineering
    ├── list                       #   列出所有循环
    ├── patterns                   #   显示内置模式
    ├── init <name> [-p pattern]   #   初始化循环脚手架
    ├── audit [name]               #   就绪度审计（0-100分）
    ├── budget <name>              #   成本估算
    ├── advance <name>             #   升级自治阶段（L1→L2→L3）
    ├── run <name>                 #   执行一轮（local/orchestrated/guidance）
    ├── continuous <name>          #   连续执行到停止
    ├── resume <name>              #   从中断处恢复
    ├── logs <name>                #   查看执行历史
    ├── status <name>              #   查看状态+预算
    └── stop-rules                 #   显示七条停止规则
```

---

## 九、技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 语言 | Python 3.10+ | 严格类型标注 (mypy strict) |
| 配置 | pydantic-settings | 类型安全的配置管理 |
| 环境加载 | python-dotenv | .env 文件继承 |
| CLI | argparse | 标准库，零额外依赖 |
| HTTP | urllib | 标准库，Gateway 通信 |
| Lint | ruff | line-length=100, target=py310 |
| 测试 | pytest + pytest-asyncio | 75 个测试 |
| 构建 | setuptools | src/ 布局 |
| 运行时依赖 | 仅 3 个 | pydantic, pydantic-settings, python-dotenv |

**零外部运行时依赖原则**: Hermes 仅依赖 3 个包，HTTP 通信使用标准库 urllib，不引入 httpx/requests/aiohttp。

---

## 十、架构设计原则

### 1. 做项目经理，不做工人
Hermes 负责编排逻辑（状态机、停止规则、预算控制、质量门禁），OpenClaw 负责执行（LLM 调用、沙箱隔离、工具执行）。不重复造运行时轮子。

### 2. Graceful Degradation
Gateway 不可用时自动降级为 guidance 模式（打印执行指引），永不崩溃。CLI 异常捕获返回 exit code 2，不静默失败。

### 3. 单一真源 + 多点分发
`./skills/` 为中心仓库，通过 symlink（默认，零开销实时同步）或 copy 分发到 12 个已知 Agent 目录。SHA256 哈希检测变更，保守冲突解决（不自动 merge）。

### 4. 分阶段自治（L1/L2/L3）
强制从 L1（只报告）起步，通过 audit 评分门控升级。L1→L2 需 ≥70 分，L2→L3 需 ≥85 分。

### 5. 工具级硬隔离
Checker Agent 的 tools 字段物理上没有 Write/Edit，不是提示词约束。**写代码的不验代码，验代码的不写代码。**

### 6. "不过滤"原则
编排器原样转发 Checker 的完整失败报告给 Builder，不解读、不总结、不省略。总结会丢失关键细节，浪费整整一轮循环。

### 7. 文件系统即数据库
所有状态持久化到文件系统（JSON + Markdown），无需数据库。meta.json 机器可读，STATE.md 人类可读，双写保持一致。

### 8. 配置继承
不重复定义 API Key，从主项目 .env 继承。优先级：进程环境 > Hermes .env > 主仓库 .env > 默认值。

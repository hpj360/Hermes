# ADR 0019: dump-config 运行时最终组装视图（借鉴 DSH --dump-config）

Status: Accepted
Date: 2026-08-15

## Context

DeepSeek Harness 的 `--dump-config` 是其口碑最好的可观测性能力之一。腾讯实测
文章把它列为 Harness 设计三问之①的标杆：「运行时最终加载了什么，能否一条命令
打印出来？」DSH 的实现让 `--dump-config` 与真实启动共用同一套 patch 算法，因此
打印出的插件树就是实际启动的插件树——配置展示和真实启动不各维护一套逻辑。

Hermes 在三问之①上长期失分：

- `hermes config show` 只打印**环境配置**（paths / models / gateway / channels /
  tools / skillhub），不含运行时组装维度（loop patterns / agent presets /
  denylist）；
- `hermes loop presets list` 只覆盖**工具面**视图（ADR-0018），不含 providers /
  skills / loop patterns；
- 一个 sub-agent 实际能做什么，散落在 5 个位置：`LOOP_PATTERNS` 的 sub_agents
  与 denylist、`ROLE_MCP_WHITELIST`、`AgentPreset`（ADR-0018）、`DEFAULT_DENYLIST`
  （gepa_redteam.py）、`discover_skills()`——无一处可看全貌。

后果：配置漂移排查要 grep 多个文件；安全审计（"某个 L3 任务的 denylist 到底覆盖
了哪些路径"）要手工拼装；新成员上手要读源码才能理解"运行时加载了什么"。

## Decision

新增顶层 CLI 命令 `hermes dump-config`，打印**最终生效组装视图**，覆盖 7 个
区段：`paths / models / gateway / loop_patterns / agent_presets / skills /
denylist_aggregate`。支持 `--json` 程序化消费。

### 设计约束

1. **与真实启动共用组装逻辑**——不另维护一套。复用 `get_settings()` /
   `discover_skills()` / `LOOP_PATTERNS` / `merged_presets()` /
   `DEFAULT_DENYLIST`，不重新实现数据源。
2. **denylist 聚合求并集**——`denylist_aggregate = DEFAULT_DENYLIST ∪
   LOOP_PATTERNS[*].denylist ∪ presets[*].denylist`。并集语义保证 L3 红线
   不可丢失：一个 pattern 级保护（如 `auth/`）不能被更窄的 preset 清除
   （与 ADR-0018 第 3 条一致）。
3. **脱敏**——gateway token / API key 只显示 set/unset，沿用 `config show`
   惯例。
4. **人类可读默认输出 + --json 双模式**——默认分 section 打印，`--json`
   输出结构化 JSON。

### 不做的事

- 不做**实时进程内状态** dump（DSH 的 `--dump-config` 是启动期组装，Hermes
  同样是启动期常量；进程内动态状态属 Trajectory 视图范畴，见报告 v3 P1 第二项）。
- 不做**配置 diff**（与某个 baseline 对比）——属未来增强，当前只做"当前
  生效视图"。
- 不替换 `config show`——两者语义不同：`config show` 是环境配置（含 channels /
  tools / skillhub），`dump-config` 是运行时组装（含 patterns / presets /
  denylist）。

## Consequences

**正面**

- 三问之①从「⚠️ 部分」升级为「✅ 可一条命令打印最终组装视图」。
- 安全审计：denylist 聚合视图让"L3 任务到底保护了哪些路径"一处可查，无需
  手工拼装 5 个数据源。
- 配置漂移排查：新增 preset / pattern / skill 后，`dump-config` 一眼比对。

**中性**

- `dump-config` 是只读视图，不改变运行时行为；测试只验证输出结构与聚合
  正确性，不验证业务逻辑。

**边界**

- `dump-config` 反映的是**声明态**（LOOP_PATTERNS / presets / skills 的当前
  值），不反映某次具体 loop run 的**运行态**（哪个 preset 实际被某个 task
  解析后采用）——后者由 `hermes loop trajectory --verify`（ADR-0017）覆盖。

## 参考

- DSH `--dump-config`：`docs/architecture.md` "Profiles and bundles"
- 报告 v3 §3.2 P1 项
- 关联 ADR：0017（轨迹不变量）、0018（Agent Preset）

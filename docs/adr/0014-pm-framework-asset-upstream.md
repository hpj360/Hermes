# ADR 0014: PM Framework 资产上收（24 skill + 4 agent → hermes）

Status: Accepted
Date: 2026-08-14

## Context

`Hermes-workbench` 仓包含 **PM Framework v3.0** 的 24 个专属 skill 与 4 个 agent
定义（director / requirement-analyst / backend-developer / tester）。这些资产
**只存在于 workbench 仓**，不在 hermes 主仓，形成第二资产信源：

- workbench 共 70 个 skill，来源三分：`pm-framework@3.0.0`（24 个）+ `hermes-original`（33）+ `hermes-upstream@0.6.0`（13）。
- 若 workbench 变"发行薄壳"且沿用 `sync-forks.sh --delete`，会把这 24 个 PM skill 盲删。

## Decision

1. **24 个 PM skill + 4 个 agent 定义上收到 hermes 主仓**，作为可选 profile（`hermes/pm/`）。
2. 上收清单（24 skill）：
   `agent-communication, api-mock, automation-tester, cicd-pipeline, code-analyzer,
   dashboard-visualizer, data-analytics, database-designer, deployer, design-delivery,
   frontend-builder, interactive-prototype, knowledge-base, monitor-alert,
   multi-project-manager, notification-system, prototype-visualizer, quality-assessor,
   requirement-analyzer, security-scanner, smart-scheduler, task-tracker, test-runner,
   ui-design-toolkit`
3. workbench 瘦身为 **Docker 发行薄壳**：只保留 Dockerfile + docker-compose + 指向
   hermes 镜像的版本 tag，不再持有任何 skill/agent 资产。

## Consequences

- **正面**：skill/knowledge 单一信源（只有 hermes）；workbench 无本地资产，消除 drift。
- **负面 / tradeoff**：hermes 的 skill 从 44 增至 68，`skills list` 输出变长；上收需一次性迁移 24 skill 目录 + 4 agent 定义，并同步 manifest.json 的 `skillProvenance`。
- **后续约束**：PM Framework 的后续迭代在 hermes 主仓进行；workbench 发布只依赖 hermes 版本 tag。

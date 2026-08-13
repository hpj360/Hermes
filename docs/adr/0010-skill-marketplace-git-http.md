# ADR 0010: Skill marketplace 采用 git/HTTP + 目录文件（零依赖）

Status: Accepted
Date: 2026-08-14

## Context

P3-4 需要 `hermes skills publish/install`，实现 skill 的跨环境分发。原方案假设一个
"在线注册中心 / 分发服务"，即需要维护一个自定义服务端。这不属于 Hermes 的可控依赖，
也不符合零依赖基线（核心运行时 stdlib-only）。

## Decision

把"注册中心"降级为一个**纯目录文件** + 标准 git/HTTP 传输，新增
`hermes/skill_market.py`：

- **registry**：`skills/registry.json`（仓库内 vendored 目录，`{name: {source, version,
  description}}`）+ 可选远端目录（`HERMES_SKILL_REGISTRY` URL，stdlib `urllib` 拉取）。
- **install**：解析顺序为显式 `--source` → vendored 目录 → 远端目录；source 支持 git URL
  （`git clone` 子进程，git 是本仓同步脚本已依赖的 dev 工具而非 Python 依赖）、本地目录、
  本地/HTTP zip 归档（stdlib `zipfile`）。
- **pack**：`hermes skills pack <name>` 用 stdlib `zipfile` 把 skill 打成
  `<name>-<version>.zip`，version 取自 `manifest.yaml`。

无自定义服务、无第三方 Python 包；`git` 与 HTTP 都是既有标准设施。

## Consequences

- **正面**：零依赖达成跨环境分发闭环；registry 可静态托管在任意 git 仓库 / 静态文件服务；
  pack 产物可直接作为 registry 的 source。
- **负面 / tradeoff**：安装第三方 skill 需信任其 source（git/HTTP），当前不做签名校验，
  与"尽力而为静态沙箱"（ADR-0009）配套使用，风险由沙箱 + 子进程隔离兜底。
- **后续约束**：若需要签名/信任链或去中心化索引，应另立 ADR；registry 条目新增字段需
  保持 `{name: {...}}` 结构并补测试。

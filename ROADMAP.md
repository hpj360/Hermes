# Roadmap

> 详细迭代 Spec 见 [`docs/roadmap/iter-v0.6-to-v1.0.md`](docs/roadmap/iter-v0.6-to-v1.0.md)。

## 当前版本：0.6.0 → 目标 v1.0.0

| 里程碑 | 版本 | 主题 | 状态 |
|---|---|---|---|
| M0 稳基 | v0.6.1 | memory search / LLM 三能力 / skill 安全 / SQLite JobStore / 文档对齐 | 进行中（P0） |
| M1 闭环 | v0.7.0 | content-team 业务真实化 + GEPA 自进化 + 前端 UI | 计划（P1） |
| M2 扩张 | v0.8.0 | hermes-kb 集成 + skill sandbox + broker 抽象 | 计划（P2） |
| M3 自治 | v1.0.0 | GEPA 红队 + memory 向量化 + 一键发布 + marketplace | 计划（P3） |

## P0 稳基（当前阶段）

- [x] P0-1 memory 搜索能力补齐 + 修复既有失败（FTS5 线程/契约/编码/排序/symlink）
- [x] P0-2 LLM stream + retry + token counter
- [x] P0-3 Skill subprocess env 白名单 + SIGKILL 兜底
- [x] P0-4 JobStore SQLite + migrator
- [ ] P0-5 文档对齐（CHANGELOG / ROADMAP / ADR）— 本文档
- [ ] P0-6 多仓同步脚本
- [ ] P0-7 调度器命名空间隔离
- [ ] P0-8 Audit log 持久化

详见 `docs/roadmap/iter-v0.6-to-v1.0.md`。

# Roadmap

> 详细迭代 Spec 见 [`docs/roadmap/iter-v0.6-to-v1.0.md`](docs/roadmap/iter-v0.6-to-v1.0.md)。

## 当前版本：0.6.0 → 目标 v1.0.0

| 里程碑 | 版本 | 主题 | 状态 |
|---|---|---|---|
| M0 稳基 | v0.6.1 | memory search / LLM 三能力 / skill 安全 / SQLite JobStore / 文档对齐 | ✅ 完成（P0） |
| M1 闭环 | v0.7.0 | content-team 业务真实化 + GEPA 自进化 + 前端 UI | ✅ 完成（P1） |
| M2 扩张 | v0.8.0 | hermes-kb 集成 + skill sandbox + broker 抽象 | 计划（P2） |
| M3 自治 | v1.0.0 | GEPA 红队 + memory 向量化 + 一键发布 + marketplace | 计划（P3） |

## P0 稳基

- [x] P0-1 memory 搜索能力补齐 + 修复既有失败（FTS5 线程/契约/编码/排序/symlink）
- [x] P0-2 LLM stream + retry + token counter
- [x] P0-3 Skill subprocess env 白名单 + SIGKILL 兜底
- [x] P0-4 JobStore SQLite + migrator
- [x] P0-5 文档对齐（CHANGELOG / ROADMAP / ADR）
- [x] P0-6 多仓同步脚本
- [x] P0-7 调度器命名空间隔离验证 + 测试
- [x] P0-8 Audit log 持久化 + AuditStore + CLI

## P1 闭环

- [x] P1-1 analytics 平台指标适配器架构（真实 API + 模拟 fallback）
- [x] P1-2 视频号适配 + B站撤回（recall 能力边界）
- [x] P1-3 OAuth 标准化（token 过期检查 + 可注入刷新）
- [x] P1-4 前端 UI（Vite + React + Tailwind，选题/创作/发布三页面）
- [x] P1-5 GEPA 自动 variant 生成（LLM 驱动）
- [x] P1-6 GEPA split-run + Welch's t 检验显著性
- [x] P1-7 Skill Manifest 协议 + skills list --untested
- [x] P1-8 /metrics Prometheus 端点 + dashboard trace 消费
- [x] P1-9 LLM function calling（tools 参数 + tool_calls 解析）
- [x] P1-10 skill_exec 安全回归套件

详见 `docs/roadmap/iter-v0.6-to-v1.0.md`。

# Roadmap

> 详细迭代 Spec 见 [`docs/roadmap/iter-v0.6-to-v1.0.md`](docs/roadmap/iter-v0.6-to-v1.0.md)。

## 当前版本：0.6.0 → 目标 v1.0.0

| 里程碑 | 版本 | 主题 | 状态 |
|---|---|---|---|
| M0 稳基 | v0.6.1 | memory search / LLM 三能力 / skill 安全 / SQLite JobStore / 文档对齐 | ✅ 完成（P0） |
| M1 闭环 | v0.7.0 | content-team 业务真实化 + GEPA 自进化 + 前端 UI | ⚠️ 部分完成（P1 工程完成，**真实平台 API 未接**） |
| M2 扩张 | v0.8.0 | hermes-kb 集成 + broker 抽象 + async bridge + OTLP | ✅ 完成（P2） |
| M3 自治 | v1.0.0 | GEPA 红队 + memory 向量化 + 一键发布 | ✅ 完成（P3） |
| M4 记忆升级 | v0.7.x | memory 后端协议化 + Mem0 融合 + 异步抽取 + 矛盾治理 | 🚧 进行中（见 `docs/roadmap/iter-memory-upgrade.md`） |

> **路线图诚信说明**：M1 的"content-team 业务真实化"当前为**适配器架构就位**，
> 发布/数据仍是 `random` 模拟，真实平台 API 接入是产品规划的**阶段 2（生死线）**，
> 详见 `docs/roadmap/product-plan.md`。

---

## 个人工作台线（PRD v4）

> 依据 [`docs/prd/PERSONAL-WORKBENCH-PRD.md`](docs/prd/PERSONAL-WORKBENCH-PRD.md)（v4）
> 与验收报告 [`docs/review/workbench-implementation-acceptance.md`](docs/review/workbench-implementation-acceptance.md)。
> 本仓只做 hermes 主运行底座；`Hermes-workbench/`、`content-team/` 冻结为资产源。

### 已交付

| 阶段 | 范围 | 状态 |
|---|---|---|
| P0 | U1a 调度修复 / U1b FastAPI 网关 / U2 鉴权 / U3 Windows 常驻 / U4-U6 前端 / U7 待办 / U8 捕获 / U9 飞书通知 / U10 技能中心 | ✅ |
| P0.5 | 捕获落 notes（markdown+frontmatter）+ 摘要 job + 驾驶舱简报本地化 | ✅ |
| P1-C3 | 飞书 bot 入箱（webhook + lark-cli 长连接双通道） | ✅ |

### 地基修复（本轮）

- [x] **O1 单树运行时**：venv editable 重指向 `D:\Hermes\hermes`（原指向 `D:\Hermes-release` 运行时副本），消除手工双树同步的脆弱性（曾被 release 侧 git reset 清空过一次）。
- [x] **O5 测试隔离**：新增全局 autouse fixture，将 `HERMES_STATE_DIR/CACHE_DIR/PROFILE_PATH` 指向 per-test tmp 并重置调度/记忆/审计单例；全量跑批不再污染真实 `.state`（此前 audit/episodes/facts/tasks 被改写、顺序敏感）。

### 待办（P1 剩余）

- [ ] **C1 自动周报 + 数据回采** —— 业务闭环关键项，采用"半自动人工导出优先"（平台无官方接口）
- [ ] C2 GitHub 双向同步（依赖 GitHub token）
- [ ] C4 全局日 token 预算（用量采集已就位，前置熔断待接）
- [ ] C5 Gated 发布流（飞书确认卡）—— C1 下游
- [ ] C6 Obsidian vault 索引 + 创作台知识卡

> **主线判断**：过去阶段以"横向扩能力"（加模块/skill/测试）为主，边际收益递减；
> 建议下一阶段转向"**纵向打穿一条真实业务闭环**"——去掉所有 mock，走通一次
> 真实 LLM → 真实发布 → 真实数据回流 → 真实复盘。判断标准只有一个：真的能用。
> 优先级：C1 → C5 → C6；C2/C4 按需。

---

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

- [x] P1-1 analytics 平台指标**适配器架构**（真实 API 接口就位，默认仍为 random 模拟）
- [x] P1-2 视频号适配 + B站撤回（recall 能力边界，半自动模式）
- [x] P1-3 OAuth 标准化（token 过期检查 + 可注入刷新，真实刷新待接）
- [x] P1-4 前端 UI（Vite + React + Tailwind，选题/创作/发布三页面）
- [x] P1-5 GEPA 自动 variant 生成（LLM 驱动）
- [x] P1-6 GEPA split-run + Welch's t 检验显著性
- [x] P1-7 Skill Manifest 协议 + skills list --untested
- [x] P1-8 /metrics Prometheus 端点 + dashboard trace 消费
- [x] P1-9 LLM function calling（tools 参数 + tool_calls 解析）
- [x] P1-10 skill_exec 安全回归套件

## P2 扩张

- [x] P2-1 /kb/search proxy + content_team RAG 调用
- [x] P2-2 skill sandbox（stdlib ast 静态门，零依赖，见 ADR-0009）
- [x] P2-3 JobQueue Backend 协议（in-memory / broker 双实现，ADR-0008）
- [x] P2-4 配置指针式继承 + Vault backend（stdlib urllib KV-v2 客户端）
- [x] P2-5 async bridge（asyncio.to_thread 桥，ADR-0007）
- [x] P2-6 OTLP exporter

## P3 自治

- [x] P3-1 GEPA 红队 variant + denylist 强度回归（gepa_redteam.py）
- [x] P3-2 memory TTL + 归档 + 向量化（embedding 缓存持久化）
- [x] P3-3 hermes deploy 一键发布（Dockerfile / compose / 说明）
- [x] P3-4 Skill marketplace（git/HTTP 分发 + registry.json 目录，见 ADR-0010）

详见 `docs/roadmap/iter-v0.6-to-v1.0.md`。

## P0 之后：DSH 借鉴（Harness 能力补齐）

> 依据 `docs/deepseek-harness-analysis.md` §3.1 方案 C。P0/P1 已实施并验收。

- [x] DSH-P0-1 派发轨迹不变量（`hermes/trajectory.py`，见 ADR-0017）
- [x] DSH-P0-2 Agent Preset 能力面收窄（`hermes/presets.py`，见 ADR-0018）
- [x] DSH-P1 Trajectory 视图（后端 3 路由 + workbench dashboard 面板，见 ADR-0020）
- [x] DSH-P1 `hermes dump-config`（7 区段最终组装视图，见 ADR-0019）
- [ ] DSH-P2 执行 seam / Python 版 PTC / 快照回放 / 能力描述符 fail-loud（均需 ADR + 业务触发）

详见 `docs/roadmap/p0-harness-borrow.md`。

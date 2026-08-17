# Hermes 记忆升级迭代 Spec v0.1（M4）

> **版本**：v0.1 (2026-08-17)
> **依据**：memory 层现状审查 + 市面产品深度选型（Mem0 主选）+ 方案对抗性审查修正（F1-F4）
> **范围**：hermes 仓 `src/hermes/workbench/`（memory 层）
> **目标**：在不破坏 stdlib-only 离线降级基线的条件下，用外部记忆产品补齐三个缺口：
> ① LLM 事实抽取（替代规则型 `learn_profile_from_episodes`）
> ② 实体/时间感知检索（升级 RRF-4 扁平打分）
> ③ 记忆矛盾治理与反馈闭环
> **状态**：**待确认**（决策基线 D1-D7 未经用户确认前不执行任何任务）

---

## 0. 要点速览（TL;DR）

1. **主选 Mem0 OSS（`mem0ai`，Apache 2.0），以 optional extra `hermes[mem0]` 引入，不进主依赖**；回退方案 MemOS adapter（同一协议实现，切换成本≈1 个适配器）。
2. **抽象先行**：新增 `MemoryBackend` 协议（`search/index_episode/delete_episode/rebuild/health`），现有 `MemoryService` 检索逻辑薄封装为 `local_rrf` 实现；`mem0` 为第二实现。核心原则：**外部后端是可选增强，本地 RRF-4 永远是保底基线**。
3. **episodes.jsonl 永远是 ground truth（单向投影）**：Mem0 侧数据可随时从 episodes 全量重建；compaction/archive 钩子同步删除 Mem0 条目。禁止双向同步。
4. **抽取不进热路径**：`record_episode` 只写本地 + 入队；异步 worker（复用现有 JobQueue/WorkerPool 基建）批量抽取，幂等（按 episode.id 去重）+ 失败重试。
5. **中文是一等公民**：默认 embedding 用 bge-m3（Ollama），抽取走中文配置；P0 必须实测中文实体链接效果，不过关则降权 Mem0 实体信号、仅用其事实抽取。
6. **P0 是验证门，不是开发门**：先用 Hermes 自己的 episodes 语料做三路 A/B（RRF-4 / RRF-4+Mem0 / Mem0 单独），Go/No-Go 判据不达标直接回退 MemOS，不进入 P1。
7. **矛盾治理必须有人**：Mem0 是 ADD-only（不覆盖），"偏好 X"与"偏好 Y"会并存；consolidation job 产出合并建议，`--gated` 人工确认后才回写 profile.json（契合半自动原则）。
8. **GEPA 边界不重叠**：程序性记忆（loop 模式/skill 进化）继续归 GEPA；Mem0 只负责事实/偏好层（L2 蒸馏 + L3 回写）。MemOS 的 skill 进化能力因与 GEPA 功能面重叠，不构成选型理由。
9. **术语映射固化**：Mem0 `user` 级 ↔ Hermes L3 profile；Mem0 `agent` 级 ↔ Hermes L2 episodes 蒸馏；Mem0 `session` 级 **不启用**（Hermes L1 是会话内工作记忆，由 loop 上下文承担）。
10. **执行纪律**：严格 P0 Gate → P1 → P2 → P3 顺序；每任务独立 commit+push（`scripts/git-push.sh`）；L2/L3 写入类改动 `--gated`；复杂任务后多 Agent 对抗性审查。

---

## 1. 决策基线（待用户确认）

| # | 决策项 | 建议选择 | 备选 |
|---|---|---|---|
| D1 | 主选产品 | **Mem0 OSS**（`hermes[mem0]` optional extra） | MemOS local plugin（回退路径） |
| D2 | 引入方式 | **`MemoryBackend` 协议 + 适配器**，不改造 `MemoryService` 现有接口语义 | 直接替换 `MemoryService`（否决：破坏降级） |
| D3 | 抽取管道 | **异步队列**（复用 JobQueue/WorkerPool），不进 loop 热路径 | 同步抽取（否决：热路径成本不可控） |
| D4 | 中文 embedding | **bge-m3（Ollama）** 为默认，P0 实测对比 gte-Qwen2 | 只用英文默认模型（否决：中文语料为主） |
| D5 | 矛盾治理 | **consolidation job + `--gated` 人工确认** | 全自动合并（否决：违反半自动原则） |
| D6 | Spec 落地形式 | 单文件 `docs/roadmap/iter-memory-upgrade.md`（本文件）+ ADR-0021 | 散落多文档 |
| D7 | 执行节奏 | 严格 P0→P1→P2→P3，**P0 Gate 不达标即回退 MemOS** | 直接铺 P1（否决：风险前置） |

---

## 2. 顶层节奏

| Phase | 周期 | 主题 | 关键交付 | 估期 |
|---|---|---|---|---|
| **P0 验证** | 1-2 周 | A/B 基准 + 部署验证 + Go/No-Go | `MemoryBackend` 协议草案 / 评测语料 / 基准报告 / ADR-0021 | ~40h |
| **P1 融合** | 2-3 周 | 接入主检索 + 异步抽取 + 一致性 | `Mem0Adapter` / `MemorySyncService` / 5 路 RRF / rebuild 命令 / 测试套件 | ~90h |
| **P2 闭环** | 2 周 | 画像回写 + 矛盾治理 + 可观测 | consolidation job / `memory audit` CLI / learn_profile 升级 / metrics | ~50h |
| **P3 观测** | 滚动 2 周 | 对抗性审查 + 回退演习 + 复查 | 审查报告 / 演习记录 / 下一步决策 | ~20h |

---

## 3. 改动面总览

| 文件 | 状态 | 内容 |
|---|---|---|
| `src/hermes/workbench/memory_backend.py` | 新增 | `MemoryBackend` Protocol + `LocalRRFBackend`（薄封装现有检索） |
| `src/hermes/workbench/mem0_adapter.py` | 新增 | `Mem0Backend`：懒加载 mem0，复用 hermes.config provider/embedding |
| `src/hermes/workbench/memory_sync.py` | 新增 | 异步抽取服务：入队/批处理/幂等/重试/重建 |
| `src/hermes/workbench/memory.py` | 修改 | `search_episodes_rrf` 接第 5 路信号；`record_episode` 插入队钩子；compaction/archive 钩子同步 delete |
| `src/hermes/workbench/cli.py` | 修改 | 新增 `memory rebuild` / `memory audit` 子命令；`_make_memory` 工厂注入 backend |
| `src/hermes/config.py` | 修改 | `HERMES_MEMORY_BACKEND` / `HERMES_MEMORY_SYNC_*` / embedding 配置项 |
| `src/hermes/workbench/server.py` | 修改 | `/metrics` 挂 memory 指标（P2）；`/memory/*` 复用不变 |
| `pyproject.toml` | 修改 | `[project.optional-dependencies] mem0 = [...]` |
| `tests/workbench/test_memory_backend.py` 等 | 新增 | adapter/融合/降级/一致性/重试幂等测试 |
| `docs/adr/0021-memory-backend-protocol.md` | 新增 | 协议 + Mem0 融合决策 + 单向投影一致性模型 |
| `docs/roadmap/iter-memory-upgrade.md` | 新增 | 本文件 |
| `ROADMAP.md` / `CODE_WIKI.md` / `CHANGELOG.md` / `knowledge/memory-model.md` | 修改 | M4 里程碑对齐（P1-6） |

---

## 4. P0 验证（Gate 决定 Go/No-Go，1-2 周）

| ID | 标题 | 改动面 | 产出 | 验收标准 | 估期 |
|---|---|---|---|---|---|
| P0-1 | `MemoryBackend` 协议草案 + `hermes[mem0]` extra | 新增 `memory_backend.py`；`pyproject.toml` | Protocol（`search` / `index_episode` / `delete_episode` / `rebuild` / `health`）+ `LocalRRFBackend` | 主依赖零新增；`pip install -e .` 不装 mem0 也能跑全测试 | 8h |
| P0-2 | 评测语料构建 | `scripts/benchmark/memory_queries.json` | 从 `.state/episodes` 历史 + content-team 真实查询构造 50-100 条评测对，覆盖偏好/事实/时间三类 | 每条评测对含 ground-truth episode id 标注 | 6h |
| P0-3 | 三路 A/B 基准 | `scripts/benchmark/memory_bench.py` | RRF-4 / RRF-4+Mem0 / Mem0 单独；指标 recall@5、MRR、p50/p95 延迟、每条 episode 增量 token | 脚本可复现；输出 Markdown 报告 | 12h |
| P0-4 | 部署与中文验证 | 验证笔记（`docs/review/` 下） | Windows 下 Mem0 本地嵌入式向量存储可用性；bge-m3 vs gte-Qwen 中文对比；中文实体链接实测 | F3 得到量化结论（通过/降级） | 8h |
| P0-5 | ADR-0021 起草 | `docs/adr/0021-memory-backend-protocol.md` | 协议 + 融合决策 + Go/No-Go 判据 | 判据可执行、可复核 | 6h |

### P0 Gate（Go/No-Go 判据）

| 判据 | 阈值 | 不达标动作 |
|---|---|---|
| recall@5 相对提升 | ≥ 15% | 回退 MemOS 方案（同一协议实现 `MemosBackend`） |
| p95 检索延迟 | < 500ms | 同上 |
| 每条 episode 增量 token | < 3K | 降级为"仅索引、不 LLM 抽取"再评估 |
| Windows 本地部署 | 通过 | 若向量存储依赖外部服务 → 判 No-Go |
| 中文实体链接实测 | 有效或可降权 | 无效则 Mem0 仅用于事实抽取，实体信号不参与融合 |

---

## 5. P1 融合（2-3 周）

| ID | 标题 | 改动面 | 产出 | 验收标准 | 估期 |
|---|---|---|---|---|---|
| P1-1 | `Mem0Backend` 适配器 | 新增 `mem0_adapter.py`；`config.py` 加配置项 | 懒加载 mem0；复用 hermes.config 的 provider/embedding；中文默认 bge-m3 | mem0 未安装时模块导入不报错；`health()` 正确报告不可用 | 16h |
| P1-2 | 异步抽取服务 `MemorySyncService` | 新增 `memory_sync.py`；`memory.py` 的 `record_episode` 插入队钩子 | 复用 JobQueue/WorkerPool；按 episode.id 幂等去重；失败经 RetryPolicy 重试；队列深度可观测 | 抽取延迟不阻塞 `record_episode`；重复入队不重复索引；重启后未处理队列可恢复 | 20h |
| P1-3 | 5 路 RRF 融合 | `memory.py` `search_episodes_rrf` | Mem0 结果作为第 5 路信号（权重最高）；降级矩阵：mem0 down → RRF-4；未抽取 episode → 本地信号兜底 | 降级路径测试通过；融合排序单调性测试通过 | 12h |
| P1-4 | 一致性：rebuild + 钩子 | `memory_sync.py` + `memory.py` | `hermes workbench memory rebuild`（episodes → 全量重建 Mem0 索引）；compaction/archive 钩子同步 `delete_episode` | 重建后 Mem0 索引与 episodes 一致；compaction 后旧条目不再被检索到 | 16h |
| P1-5 | 测试套件 | `tests/workbench/` | adapter / 融合 / 降级 / 一致性 / 重试幂等，覆盖率 ≥85% | pytest 全绿；ruff + mypy strict 零错误 | 18h |
| P1-6 | 文档对齐 | ROADMAP / CODE_WIKI / CHANGELOG / memory-model.md | M4 里程碑登记 + 术语映射表固化 | manifest 版本同步；ADR-0021 状态 Accepted | 8h |

### P1 验收门
- `bash scripts/verify-state.sh` 全 ✅；`pytest tests/` 全绿且覆盖率不低于现状（83%+）
- 回退演习：`HERMES_MEMORY_BACKEND=local_rrf` 时行为与 v0.6.0 完全一致（diff 测试）
- 每任务完成立即 `bash scripts/git-push.sh`

---

## 6. P2 闭环（2 周）

| ID | 标题 | 改动面 | 产出 | 验收标准 | 估期 |
|---|---|---|---|---|---|
| P2-1 | Consolidation job | `memory_sync.py` 或独立模块 + `triggers.py` | cron/阈值触发的矛盾配对合并 + 过期 TTL；产出合并建议，`--gated` 人工确认后回写 profile.json | 矛盾对可检出；未确认不落盘；审计记录完整 | 16h |
| P2-2 | `hermes workbench memory audit` CLI | `cli.py` | 列出矛盾对 / 孤儿事实 / 抽取失败队列，人类裁决 | 三类清单可查询、可导出 | 8h |
| P2-3 | `learn_profile_from_episodes` 升级 | `memory.py` | 主路径走 Mem0 user 级记忆回写 L3；规则型保留为离线降级 | mem0 可用时画像含 LLM 抽取结果；不可用时行为不变 | 12h |
| P2-4 | `/metrics` 挂 memory 指标 | `server.py` | 抽取队列深度 / 增量 token / 降级次数 / recall 代理指标 | Prometheus 格式可拉取 | 10h |

---

## 7. P3 观测（滚动 2 周）

| ID | 标题 | 产出 | 验收 |
|---|---|---|---|
| P3-1 | 多 Agent 对抗性审查 | 审查报告（反方复现基准、质疑融合权重、找降级边界反例） | 发现的问题回溯修复，不得带病交付 |
| P3-2 | 回退演习 | 人为断掉 Mem0 → RRF-4 无感降级记录 | 端到端验证通过 |
| P3-3 | 决策点复查 | Graphiti 图层 / MemOS 第二后端是否进入 M5 | 输出结论 + 触发条件 |

---

## 8. 架构要点（不可简化的设计约束）

### 8.1 MemoryBackend 协议（草案）

```python
class MemoryBackend(Protocol):
    def search(self, query: str, limit: int = 10, kind: str | None = None) -> list[tuple[Episode, float]]: ...
    def index_episode(self, episode: Episode) -> None: ...
    def delete_episode(self, episode_id: str) -> None: ...
    def rebuild(self, episodes: list[Episode]) -> None: ...
    def health(self) -> bool: ...
```

- `LocalRRFBackend` = 现有 `MemoryService.search_episodes_rrf` 的薄封装（基线）。
- `Mem0Backend` = 同一协议；**懒加载** mem0（模块内 import），未安装/不可用时 `health()` 返回 False。
- `MemosBackend`（回退方案预留）同协议，与现有 `MemosClient` 合并实现。

### 8.2 单向投影一致性模型

- 权威数据流：`record_episode → episodes.jsonl → (异步) → Mem0 索引`。
- 反向永不成立；Mem0 侧任何状态可由 `rebuild(episodes)` 重建。
- compaction/archive 触发 `delete_episode`（按 id 失效）；失败重试，超限记入 audit 并在 P2-2 可见。
- 检索兜底：未完成抽取的 episode 仍被本地 RRF 信号覆盖，不存在"写入即不可见"。

### 8.3 融合与降级矩阵

| 状态 | 检索行为 |
|---|---|
| Mem0 健康 | RRF 5 路（mem0 信号权重最高） |
| Mem0 不可用 | RRF 4 路（与 v0.6.0 完全一致） |
| 单条 episode 未抽取 | 本地 4 路信号覆盖该条 |

### 8.4 术语映射（写进 memory-model.md）

| Hermes | Mem0 | 状态 |
|---|---|---|
| L1 工作记忆（会话内） | （不启用 session 级） | loop 上下文承担 |
| L2 episodes（ground truth） | agent 级记忆（蒸馏结果） | 单向投影 |
| L3 profile（用户偏好/事实） | user 级记忆（回写目标） | `--gated` 回写 |

---

## 9. ADR 计划

| ADR | 标题 | 时机 |
|---|---|---|
| ADR-0021 | MemoryBackend 协议与 Mem0 融合决策（含 Go/No-Go 判据与回退方案） | P0-5 起草，Gate 通过后 Accepted |
| （视需要）ADR-0022 | 若 P0 回退 MemOS：协议实现变更说明 | 回退时 |

---

## 10. 风险登记

| 风险 | 概率 | 缓解 |
|---|---|---|
| Mem0 OSS 召回增益不达 15% | 中 | P0 Gate + MemOS 回退路径（协议已抽象） |
| 中文实体链接实测效果差 | 中高 | P0-4 前置验证；不过关则降权实体信号、仅用事实抽取 |
| 抽取管道积压 | 低 | 复用 JobQueue 背压 + 批处理上限 + 队列深度指标告警 |
| Mem0 上游向平台倾斜、OSS 收缩 | 中 | 协议隔离 + 降级基线永保 + P3-3 复查 |
| 双写漂移残留 | 中 | 单向投影 + rebuild 命令 + audit CLI 兜底 |
| 增量 token 超预算 | 中 | P0-3 实测；超限降级为"仅索引、不 LLM 抽取" |

---

## 11. 确认清单（请逐项确认）

1. **D1**：主选 Mem0 OSS（`hermes[mem0]` extra）？还是直接选 MemOS？
2. **D2**：`MemoryBackend` 协议 + 适配器（保留 RRF-4 基线）的引入方式是否同意？
3. **D3**：异步抽取管道（不进热路径）是否同意？
4. **D4**：中文默认 bge-m3（Ollama），P0 实测对比，是否同意？
5. **D5**：矛盾治理 `--gated` 人工确认，是否同意？
6. **D6/D7**：本 Spec 文件 + 严格 P0 Gate 节奏（不过关回退 MemOS），是否同意？
7. **估期**：P0 ~40h / P1 ~90h / P2 ~50h / P3 ~20h，是否可接受？
8. **范围**：P0 是否包含 ADR-0021 起草？P1 是否包含文档对齐（P1-6）？

确认方式：逐项回复「同意 / 修改为…」，全部确认后从 P0-1 开始执行。

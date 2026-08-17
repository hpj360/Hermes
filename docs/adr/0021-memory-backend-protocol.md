# ADR 0021: MemoryBackend 协议与 Mem0 融合决策

Status: Accepted
Date: 2026-08-17

## Context

Hermes 的 memory 层（`workbench/memory.py`）已有自研的三层记忆（L1 facts /
L2 episodes / L3 profile）+ 混合检索（RRF：子串 + TF-IDF + FTS5 BM25 + Ollama
向量）。但存在三个缺口：

1. **无 LLM 事实抽取**：`learn_profile_from_episodes` 是纯规则型，无法从对话里
   提炼用户偏好/经验。
2. **无实体/时间感知检索**：RRF 是扁平打分，缺少实体匹配与时间排序。
3. **无矛盾治理闭环**：记忆只增不改，长跑后矛盾事实累积。

市面产品评估（Mem0 / MemOS / Graphiti / Cognee / Letta / LangMem / OpenViking）
结论：**Mem0（`mem0ai`，Apache 2.0）为主选**，因召回基准领先、license 干净、
生态最成熟，且其「LLM 事实抽取 + 实体链接 + 时间推理」恰好补齐三个缺口。
Graphiti 因需图数据库基建（Neo4j/FalkorDB）判为未来备选；OpenViking 因 AGPLv3
判为不兼容。

约束：Hermes 的设计原则是 stdlib-only、本地优先、离线降级（`CODE_WIKI.md` 原则
1）。引入外部后端**不得破坏**这条基线——本地 RRF 必须永远是可用兜底。

## Decision

1. **抽象 `MemoryBackend` 协议**（`memory_backend.py`）：`search` /
   `index_episode` / `delete_episode` / `rebuild` / `indexed_ids` / `health`。
   - `LocalRRFBackend`：现有 RRF 的薄封装，无独立索引，`index/delete/rebuild`
     为 no-op，`indexed_ids` 恒等于全部 episode id。
   - `Mem0Backend`（`mem0_adapter.py`）：懒加载 mem0，`health()` 为 False 时
     调用方降级本地 RRF；未安装 mem0 时模块导入/构造**永不抛错**。

2. **episodes.jsonl 是唯一 ground truth（单向投影）**：`record_episode` → 本地
   落盘 → 异步入队 → 后端索引。反向永不成立；后端状态可随时由 `rebuild` 从
   episodes 全量重建。`compact_episodes` / `archive_episodes` 同步
   `delete_episode` 失效后端条目。

3. **抽取不进热路径**：新增 `MemorySyncService`（`memory_sync.py`），`enqueue`
   只做内存去重 + pending 落盘 + 入队，永不调用后端/网络；单 daemon worker 批量
   消费，失败按指数退避重试，耗尽记入失败日志。pending 文件保证重启不丢。

4. **检索融合**：`search_episodes_rrf` 增第 5 路后端信号，权重 2.0（其余 1.0），
   后端不健康时自动退回 4 路。

5. **引入方式**：mem0 作为 `pyproject.toml` 的 optional extra `hermes[mem0]`，
   不进主依赖；`_make_memory` 工厂按 `HERMES_MEMORY_BACKEND` 装配。

6. **中文是一等公民**：`_tokenize` 增加 CJK 字符 bigram 分词（无空格中文可检索）；
   Mem0 默认 embedding 复用 Ollama（bge-m3 等），P0 需实测中文实体链接效果。

7. **矛盾治理必须有人（半自动原则）**：`detect_conflicts` 提供规则型候选对，
   `memory audit` 供人类裁决；consolidation 从不自动回写 profile。

## Consequences

- **正面**：召回质量补齐实体/语义维度；LLM 事实抽取替代规则型画像学习；异步
  抽取不阻塞热路径；协议隔离使后端可替换（MemOS 为回退实现，成本≈1 个适配器）。
- **负面 / tradeoff**：引入可选第三方依赖（mem0）与 LLM 抽取成本；Mem0 为
  ADD-only，矛盾需额外治理；双轨（episodes + 后端索引）有漂移风险，靠单向投影
  + `rebuild` + `memory audit` 兜底。
- **后续约束**：
  - 任何新后端（如 MemOS）只实现 `MemoryBackend` 协议，不得改动 `MemoryService`
    现有方法语义。
  - 后端 `search` 必须返回 `(Episode, score)`；返回不了 Episode 的（如原生
    MemOS 记忆）需先经 episode_id 元数据映射回 Episode，否则不参与 RRF 融合。
  - `HERMES_MEMORY_SYNC_ENABLED=true` 时抽取走异步 worker；`_make_memory` 已按
    `(state_dir, backend, sync)` 做进程级缓存（`_reset_memory_cache` 供测试），
    `serve` 长驻模式复用同一实例与同一 worker，不再每请求泄漏线程。

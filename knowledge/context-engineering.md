# Context Engineering 知识沉淀

> 来源：DeepSeek-Reasonix 的 cache-aware 上下文维护实践（评估见
> `docs/ecosystem-reasonix-opendesign-assessment.md` §1）+ 花叔 Loop Engineering
> 橙皮书"Context Engineering"章节。

---

## 一、稳定前缀 vs 易变后缀（Reasonix A1/A3 借鉴）

**核心洞察**：发给模型的上下文可以拆成两部分，缓存收益主要来自"稳定前缀"。

| 区域 | 内容 | 性质 |
|------|------|------|
| **稳定前缀** | agent 定义（builder.md）+ 环境摘要（约定 + 结构） | 跨轮不变 → 命中 prefix-cache |
| **易变后缀** | 本轮 task + 上轮 checker 报告 + 工具结果 | 每轮变化 → 不命中缓存 |

**纪律**：
1. 稳定前缀**顺序固定**、**不含时间戳/动态 id/逐轮报告**——`build_stable_prefix`
   + `assert_stable_prefix` 契约锁定（`src/hermes/context.py`）。
2. 环境摘要用 `env_summary` **缓存 + 内容 hash 判重**，只在源内容变化时重算，
   保证字节级稳定。
3. compaction/摘要前调用 `prune_stale_tool_outputs` 裁剪陈旧工具输出，防上下文
   单调膨胀（回应 DSH 13.4k token 首包教训，`deepseek-harness-analysis.md` §2.5）。

## 二、executor / checker 会话分离 + cache-stable

Hermes 的 builder（executor）与 checker（verifier）经 Gateway 各自独立 spawn，
天然会话分离——这是"写代码的不给自己的代码打分"（harness-engineering.md §四）
在会话层的落地。cache-stable 的额外含义是：

- 每个角色的 `agent_definition` 保持稳定（同一 .md 文件，不在运行时拼时间戳）。
- 角色间只传"结构化失败报告"（checker → builder 的 raw report），不传易变的
  完整对话历史，避免污染对方的前缀。

## 三、checkpoint / rewind（Reasonix A2 借鉴）

- `record_round` 每轮落 `checkpoints/<round>.json`（快照 meta.json）。
- `hermes loop rewind --to N` 恢复到第 N 轮：截断 rounds、截断 trajectory
  （用 ADR-0017 的 `LoopRound.trajectory_seq`）、状态置 NEEDS_HUMAN。
- 与 fresh resume 的区别：rewind 是"回到历史某一轮继续"，resume 是"从终态清空
  重开一个新周期"。

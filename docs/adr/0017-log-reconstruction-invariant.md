# ADR 0017: Loop 轨迹采用"派发可重建"不变量（借鉴 DeepSeek Harness）

Status: Accepted
Date: 2026-08-15

## Context

借鉴 DeepSeek Harness 的 session log 设计（见 `docs/deepseek-harness-analysis.md`）：
DSH 强制"模型看见的内容必须已记入日志"，发请求前用 invariant 比较当前请求与
`session.deriveMessages()`，不一致即 `log-reconstruction desync` 失败。这使其
Trajectory 能完整还原模型所见、工具调用与 token 变化。

Hermes 是**控制平面**——LLM 请求实际发生在 OpenClaw Gateway 内部（`/api/subagent/spawn`），
Hermes 无法直接观测 Gateway 发给模型的消息。但 Hermes 能观测并控制**自己发给 Gateway
的一切输入**（`task` / `context` / `agent_definition` / `allowed_tools` / `denylist` /
`model`），这些输入就是模型上下文的上游来源。当前这些字段散落在 `AgentTask` 各字段与
`spawn_agent` 的局部 payload 构造中（orchestrator.py:291-303），无持久化快照，无法回答：

1. 第 N 轮 builder 当时收到了什么任务与上下文？（只能靠 STATE.md 摘要与 episodes 推断）
2. 审计"模型当时看见了什么"时，日志与真实派发是否一致？

这是 `multi-agent-harness.md` 提升项未覆盖的可观测性缺口，也是 L3 无人值守审计
可信度的短板。

另有一条 Hermes 直连 LLM 的路径：`hermes.workbench.llm`（生产调用方为 workbench 的
goal.py planner 与 CLI；GEPA 的 `auto_generate_variants` 目前仅测试路径调用，未来
接入 GEPA 周期时同样适用）。该路径的请求头与消息体同样无轨迹日志。

## Decision

新增 `hermes/trajectory.py`，实现**追加式派发轨迹日志 + 可重建校验**：

1. **TrajectoryLogger**：追加式 JSONL（`.loops/<name>/trajectory.jsonl`），每条记录
   `{"seq": N, "time": ..., "type": "...", "data": {...}}`。
   `record(type, data) -> int` 返回 seq；内部 `threading.Lock` 串行化计数器与追加
   （`atomic_append_jsonl` 的 flock/msvcrt 锁只保证行写入原子，不保证 seq 分配顺序，
   因此进程内锁不可省）。`record()` 失败（写盘 OSError）→ **中止派发**，
   与 desync 同为 fail-loud：轨迹是 L3 审计凭证，写入失败不应静默降级。
   `last_seq()` 供调用方回填轮次记录；构造时从既有文件续接 seq（跨 logger 实例
   不重号）。

2. **事件类型**：派发类 2 种（默认开启）+ 直连 LLM 类 2 种（opt-in，见第 5 条）：
   - `dispatch/request`：spawn 前的**完整 payload 快照**（含 agent_definition 全文，
     见第 3 条），`data` 含 `role` + `round_num`（轮次关联键）+ `agent_file` +
     `agent_file_sha256`（原始文件哈希，供离线 verify 区分 preset 拼接）+ `payload`。
   - `dispatch/result`：`request_seq`（对应 request 事件的 seq）+ `role` + `round_num`
     + `session_id` / `status` / `tokens_used` / `completed_at`。**失败路径同样补记**
     （desync 中止、Gateway 不可用、超时均记 `status=failed`），保证每个 request
     都有配对 result，replay 不依赖文件位置。
   - `request/header`、`request/context`：直连 LLM 路径的请求头与消息快照。

3. **payload 构造提纯**：`orchestrator.py` 新增模块级纯函数
   `_build_spawn_payload(task, preset=None) -> dict`，为唯一 payload 构造点。
   **payload 保持含 agent_definition 全文**（Gateway 现有契约要求全文）；
   轨迹快照同样存全文（放弃"哈希替代"优化——轨迹本就是审计数据源，还原能力优先于
   磁盘占用；agent .md 文件本身已存在于 loop_dir，重复成本有限）。
   `preset` 为 **resolve 后的 preset 对象**（非按名回查），其 `prompt_sections`
   拼接发生在 payload 构造内、轨迹记录之前。

4. **运行时校验 `assert_reconstructable(events, payload)`**：重放该 task 的
   `dispatch/request` 事件得到 `derived_payload`，与即将派发的 payload 做规范化
   JSON 比较；不一致 → 抛 `TrajectoryDesyncError`，中止派发。
   **定位声明（诚实）**：记录与派发同源（同一 dict），运行时校验实际价值是——
   ① 序列化 round-trip 门禁（抓 record 写盘丢字段/规范化不对称 bug）；② 日志被
   外部篡改的即时发现；③ 配合"后续约束"的契约测试，阻止未来新增 payload 字段
   而未入轨迹的漂移。它**不**等于 DSH 的双来源不变量（Hermes 的请求序列化发生在
   Gateway 内部，受控范围外）。

5. **直连 LLM 路径（opt-in）**：`hermes.workbench.llm` 的 `chat()` 增加可选
   `trajectory` 参数，发送前**只记录** `request/header` 与 `request/context`
   （best-effort，失败不阻断 LLM 调用）。与派发路径的 fail-loud 语义不同：直连
   路径**不执行同源校验**、**无开关门控**，是否启用完全由调用方是否显式传入
   `trajectory` 决定（当前无生产调用方接入）。

6. **任务关联**：`AgentTask` 新增 transient 字段 `trajectory_request_seq: int | None`
   （不进 `to_dict`，不入 Gateway payload）。`_prepare_and_spawn` 在 record 后把
   返回的 seq 暂存于此，`fan_in` 补记 result 时携带，实现 request→result 的
   显式配对（一轮 4 个 task 可区分）。`AgentTask.round_num` 线程化轮次号，
   `LoopRound.trajectory_seq` 持久化到 meta.json（跨会话追溯轮次↔轨迹）。

7. **CLI**：`hermes loop trajectory <name> [--json] [--verify]`。`--verify` 为
   离线审计，检查清单：JSON 行完整性（corrupt line 计数）、seq 连续、
   request/result 配对完备（含非 int request_seq 的异常 result）、`agent_file`
   原始内容与 `agent_file_sha256` 的一致性。注意：自由文本字段（task/context）
   离线无法鉴别"篡改后仍自洽"的日志——verify 不承诺检出所有篡改，只承诺清单内项目。

8. **生命周期**：`resume_loop` 对 COMPLETED/BUDGET_EXCEEDED 清空历史开始新周期时
   （runner.py），将旧 trajectory.jsonl 归档为 `trajectory.<n>.jsonl`（文件名
   递增序号），新周期从空文件开始，避免跨周期事件混流。

**边界（诚实声明）**：本不变量验证的是 **Hermes → Gateway 的派发边界**，不是
Gateway → 模型边界。Gateway 内部对 payload 的二次加工（注入系统提示等）不在
Hermes 控制范围内，仍以 Gateway 自身日志为准。这与 DSH 的不变量有范围差异，
不变量名称相应定为"派发可重建"而非"模型所见可重建"，避免过度承诺。

## Consequences

- **正面**：
  - 每轮每个 sub-agent 的完整派发输入快照可追溯、可重放、离线可校验，审计粒度
    从"轮次摘要"升级到"逐 task 输入快照"；
  - 为 P1 的 Trajectory UI 提供唯一数据源（数据先行，UI 后置）；
  - 零新依赖（JSONL + 现有 persistence 原语），符合 stdlib-first 基线；
  - 契约测试使"新增影响上下文的字段"必然显式化（见后续约束）。
- **负面 / tradeoff**：
  - 每次 spawn 多一次 JSONL 追加（含 fsync，毫秒级），对分钟级任务可忽略；
  - `assert_reconstructable` 每次校验全量重读轨迹文件（O(N)/spawn），长 loop 下
    是 O(n²)；当前规模可接受，若轨迹增长到数万行需改为尾行读取或内存比对；
  - `agent_definition`（builder.md 全文）进入轨迹 → 磁盘占用与日志敏感度上升，
    需要文档化"轨迹=敏感边界"（与 DSH 的隐私含义一致）；
  - 运行时校验的价值有限（同源比较），真实防线是契约测试 + 离线 verify；
  - 不变量覆盖范围受控于 Gateway 边界，若未来 Gateway 开放"透传原始消息"接口，
    应升级不变量到消息级（另立 ADR）。
- **后续约束**：新增任何会影响模型上下文的 spawn 字段，必须同时加入
  `_build_spawn_payload` 与轨迹事件，否则契约测试失败（有意为之）。
  破坏性字段变更需在轨迹 reader 中做兼容迁移（如 `schema_version`）。

## 参考

- DSH session log：`packages/core/session` + `invariant.ts`（log-reconstruction desync）
- 分析报告：`docs/deepseek-harness-analysis.md` §3.1 方案 C 之 P0-1

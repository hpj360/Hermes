# Super-agent 架构对照笔记

> 来源：阿里妹《深度解析 DeepSeek Super-agent：多端协同的自主 Agent 设计思路》
> （对象：DeepSeek Harness 团队开源的 `deepseek-ai/dsh-superagent-prototype`，官方标注为原型）
>
> 本文只记录**可迁移的架构判断**与**本项目真实缺口**，不重复已有架构描述。
> 已有能力见 [architecture.md](./architecture.md)、[multi-agent-harness.md](./multi-agent-harness.md)。

---

## 一、核心模型（提炼）

Super-agent 的三条硬要求：**Always Active**（7×24 待命）、**主动性**（主动汇报/预警，而非被追问）、**长时程自主**（数小时到数天不中断）。

为满足它们，必须接入更多 Context 与权限；入口一多，就出现真问题：**一个 Agent 如何接收来自多端的消息、并把结果准确回投给来源。**

### Router + Worker 的四条边界

| 边界 | 含义 |
|---|---|
| Router 不干活 | 只做对接人、汇总、调度；甚至不具备 Bash/工具能力 |
| Worker 不直接对人 | 产出先交 Router，由 Router 决定是否透传 |
| Worker 之间不直接交流 | 避免网状耦合；需要协作时由 Router 重调度 |
| Worker 可以是 Agent Team | 内部自建 Sub-Agent 并行，对 Router 是黑盒 |

> 关键收益：**Worker 做错了能回 Router 重新调度**，绕开传统 Hand-off「交出去就回不来」的链路拉长。

### 三种协同范式的分野

| 范式 | 谁对用户说话 | 主 Agent 负载 | 主要失败代价 |
|---|---|---|---|
| Multi-Agent（Hand-off） | 谁都能 | 低但失控 | 分错任务后下游解决不了，再转交→链路长、成本高 |
| Agent Team | Orchestrator 亲自下场 | **高**：工具/设计细节塞满窗口，频繁触发压缩 | 上下文被挤爆 |
| **Super-agent** | 仅 Router | **低** | Worker 错了可回炉重调度 |

作者结论：三者结构相似，**差别在人对分工边界的定义**；把 Agent Team 的 Orchestrator 限定为只路由，就等价于 Super-agent。

### 四个机制

1. **事件驱动双层过滤**：Fast Path（纯代码规则，零延迟，拦掉绝大多数噪声）→ Slow Path（大模型语义判断，防漏）。先便宜后昂贵。
2. **渠道绑定回投**：创建 Worker Session 时直接订阅原始渠道（IM Thread / PR 评论），结果无需事后猜路由。
3. **全双工**：耗时任务不再阻塞——立即返回「已触发」，通道保持开放；结果作为新上下文回喂，触发最终交付。
4. **工程兜底**：Inline & Spill（高频信息留上下文、低频信息外置按需读）、存算分离（计算与会话状态解耦，摆脱单机生命周期）、Watchdog（检测无效循环/报错并拉起恢复）。

---

## 二、本项目对照

| Super-agent | Hermes 现状 | 判定 |
|---|---|---|
| Router | `Orchestrator` + loop runner | 已有，但 Router 还兼审计与评分，比「纯路由」重 |
| Worker | `AgentTask` + 隔离 session + 独立 workspace | 等价 |
| Worker 不直接对人 / 之间不直连 | fan_in 统一收集，aggregate 统一产出 | 等价 |
| 全双工 | `SteeringController` + `_fan_in_polling` | 可用：并行下 stop 即时生效；仍限「fan_in 等待期」 |
| Watchdog | `WatchdogConfig`（重复动作）+ 七条停止规则 + token 熔断 | 轮边界 + 轮内重复动作检测；静默/token 速率未做 |
| 事件驱动 Fast/Slow | 无 | 单入口 CLI，暂不需要 |
| 渠道绑定回投 | 无 | 同上 |
| 存算分离 | `loops_dir` 状态落盘 + resume | 有 checkpoint，非计算/状态解耦级 |

---

## 三、提升 1：并行 fan_in 的 steering 串行阻塞（P0，真实缺陷）✅ 已实现

### 现状（修复前）

旧 `fan_in` 是**逐个 task 串行等待**：

```python
for task in tasks:
    self._fan_in_with_steering(task, timeout, steering)
```

而 checker 阶段是并行派发的（[orchestrator.py:1256](../src/hermes/orchestrator.py#L1256) `parallel=True`，[orchestrator.py:1274](../src/hermes/orchestrator.py#L1274) 一次 fan_in 全部）。

### 影响

3 个并行 checker 时，针对第 3 个的下发指令，最坏要等前两个各自跑完（单个 timeout 300s）才会被 pop。
**「轮内 steering」在并行场景下不是实时的**——这与 steer 的设计意图（中途止损）直接冲突：
用户已判定第 3 个 checker 跑偏，但 stop 指令要排在队尾。

### 修复方向

把串行改为一趟轮询所有 pending session：

```
while pending:
    for task in pending: probe(task.session_id)   # 全量探测
    drain steering for ALL pending keys            # 统一消费
    collect finished tasks                          # 完成即收，不按顺序
    sleep(poll_interval)
```

- 改动集中在 `fan_in` 的分支与新增的 `_fan_in_polling`（批量轮询实现）
- 结果收集仍复用 `_collect_task_result`，`tasks` 列表顺序不变（只是收集时机变早）
- 风险：中低。语义变化是「完成顺序 ≠ 列表顺序」，需确认调用方无顺序依赖

### 验收

- 3 个 fake session，对第 3 个 stop，能在**一个 poll 周期内**生效（当前需等前两个）
- 单个 task 超时不拖累其他 task 的 deadline
- 现有 steering 用例（单 task 路径）全部保持通过

### 实现内容

- `fan_in` 分支：`steering is None and watchdog is None` 走原阻塞路径（行为不变），否则走 `_fan_in_polling`
- `_fan_in_polling` 一趟探测全部 pending：完成即收集，不再按列表顺序阻塞；所有 session 共享同一 deadline
- 人下达的 steering 优先于自动 watchdog；单次探测失败继续轮询
- 回归用例用**收集顺序**而非最终状态作判据（旧实现里被阻塞的任务最终也会 stop，只看终态区分不出两种实现）

---

## 四、提升 2：全生命周期 steering（P1）

### 现状

`steering` 只在 `fan_in` 等待期被消费。以下窗口**没有通道**：

| 窗口 | 现状 |
|---|---|
| builder spawn 后、fan_in 前 | 无消费点 |
| sequential task 之间 | 无消费点 |
| 轮与轮之间（`run_loop_continuous` 的 gated 等待） | 无消费点 |

### 方案与成本

| 方案 | 改动 | 风险 |
|---|---|---|
| **A. 最小化**：在 `run_loop_continuous` 的回合间等待也 poll steering | 1 处循环 + 复用现有 controller | 低 |
| **B. 下沉为 SteeringPump**：独立线程持续消费，fan_in 只做注册 | 新增线程生命周期、与 `GatewayClient` 并发、task 字段写入加锁 | 中 |

建议先做 A（补齐边界），确有「轮间插话」需求再做 B。B 的前提是确认 `GatewayClient` 的 `_request` 在多线程下安全（当前无共享可变状态，urllib 每请求独立，风险不大）。

---

## 五、提升 3：轮内 Watchdog（P1，重复动作部分 ✅ 已实现）

### 可用信号（已确认）

| 信号 | 来源 | 可用性 |
|---|---|---|
| 会话状态 | `check_session` 每次 poll 返回 `status` | ✅ 已在用 |
| 消息增量 | `client.get_session_messages()` 可中途调用（stop 路径已用） | ✅ 可用 |
| token 用量 | `check_session` 返回 dict 里的 `tokens_used` | ⚠️ **中间态是否填充未验证**——终态才读，中间可能为 0 |
| 重复动作 | 需自行从消息的 `tool_calls` 计算 `(tool, args)` 指纹 | ✅ 可算 |

### 三条检测（按性价比排序）

1. **重复动作**：连续 N 次相同 `(tool_name, args_hash)` → 判定原地打转。**最可靠**，只依赖消息增量。
2. **无进展**：连续 M 个 poll 周期消息数不增 → 静默/卡死。
3. **token 速率/绝对量**：已有 `_check_token_limit` 但只在**终态**生效；下沉到轮内即可提前熔断。**前提是先验证网关中间态返回 `tokens_used`**，否则本条不成立。

### 处置

复用 `SteeringController.stop()`——已支持「保留部分结果 + status=stopped」，**无需新增通道**。这是本次评估里最省的一点：Watchdog 只是「自动化的 steering 触发者」。

### 成本

- 检测器本体：约 80 行 + 3 个阈值（重复次数、静默周期、token 速率）
- 接入点：`_fan_in_polling` 的 poll 间隙（与提升 1 改在同一处，**已合并实现**）
- 测试：fake session 序列驱动（重复动作 / 静默 / 正常），约 6–8 个用例
- 风险：低-中。误杀是主要风险 → 阈值需保守，且 stop 理由要写进结果供人复核

### 实现内容（仅第 1 条）

- `WatchdogConfig(repeat_threshold=3)`；`fan_in(..., watchdog=...)`
- `_last_action_fingerprint` 取最近一次 `tool_calls` 的 `(工具名, 参数摘要)` 指纹；纯文本消息不算动作（否则会把反复思考误判为打转）
- 连续相同指纹达阈值 → 复用 `steering.stop` 路径（`status="stopped"`，保留部分结果），理由写明次数与指纹
- 生产接线：`runner.py` 的 builder-checker 与 perspectives 两条链路默认传 `WatchdogConfig()`
- 探测异常按「无信号」处理，不阻断等待
- **未做**：静默检测与 token 速率熔断（后者依赖网关中间态 `tokens_used`，未验证）

---

## 六、明确可舍的三项

| 机制 | 舍弃理由 | 何时重新考虑 |
|---|---|---|
| 事件驱动 Fast/Slow 过滤 | 当前单入口 CLI，不存在千人群聊级噪声 | 接入 IM/webhook 多源入口时 |
| 渠道绑定回投 | 单入口，结果直接返回调用方 | 同上 |
| 存算分离 | 已有 `loops_dir` 持久化 + resume，满足本地续跑 | 需要云端托管、跨设备接续时 |

作者本人的提醒正适用：**「没有最好的 Harness 架构，只有最适合当前场景的」**——这三项不是缺陷，是场景未到。

---

## 七、落地成本总表

| 提升 | 改动面 | 风险 | 测试增量 | 依赖前提 | 状态 |
|---|---|---|---|---|---|
| 1. 并行 fan_in steering | `fan_in` 拆分 + `_fan_in_polling` 批量轮询 | 中低 | 3 用例 | 无 | ✅ 已实现 |
| 2. A. 轮间 steering | `run_loop_continuous` 1 处循环 | 低 | ~3 用例 | 无 | 待做 |
| 2. B. SteeringPump 线程 | 新线程 + 并发写入加锁 | 中 | ~6 用例 | 确认 client 线程安全 | 待做 |
| 3. 重复动作检测 | 指纹计算 + poll 间隙判定 | 低 | 6 用例 | 无 | ✅ 已实现 |
| 3. token 速率熔断 | 下沉 `_check_token_limit` | 中 | ~4 用例 | **需实测网关中间态 tokens** | 待做 |

**已落地：1 + 3（重复动作）**，共 12 个新用例，全量 2386 passed / ruff / mypy 通过。
**剩余顺序：2A → 3（token）→ 2B。** 理由：token 熔断与 SteeringPump 都有外部前提，应后置。

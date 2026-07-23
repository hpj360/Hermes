# Hermes 决策记录与演进日志 (DECISIONS)

> 本文档记录 Hermes 项目的关键设计决策、决策原因、以及反模式清单。
> 修改 prompt/规则/架构时，先读本文档，避免"不知道上一次为什么这么定"。

## 一、关键决策记录

### D001: 为什么是 7 条停止规则（而非 5 条或 8 条）

**日期**: 2026-06-25
**决策**: 采用 7 条互斥停止规则，评估顺序 = STOP_RULES 列表顺序
**原因**:
- ALL GREEN 是成功条件（非停止），列为首条便于统一查阅
- budget_exceeded 和 rounds_exhausted 同属"资源耗尽"
- regression/same_failure_twice/no_progress 三者必须互斥（通过 new/overlap/fixed/count 四维判定）
- beyond_capability 前置于 regression（外部问题不应算回归）
**替代方案**: 5 条（合并 regression/no_progress）→ 否决，因两者失败模式不同
**参考**: [loop.py STOP_RULES](file:///workspace/src/hermes/loop.py)

### D002: 为什么用工具级硬隔离而非提示词约束

**日期**: 2026-06-25
**决策**: checker.md 的 tools 字段排除 Write 和 Edit
**原因**: 提示词约束可被绕过（Agent"觉得"需要改一行），工具不可见就是不可见
**替代方案**: 提示词说"你不要改代码" → 否决，不可靠
**参考**: [builder-checker-loop.md](file:///workspace/knowledge/builder-checker-loop.md)

### D003: 为什么 working-principles 只有 2 条

**日期**: 2026-06-26
**决策**: 全局工作规则只保留 2 条（第一性原理 + 对抗性审查）
**原因**: 规则越多解释空间越大，2 条是最小自洽集——一个管"怎么想"，一个管"怎么验"
**替代方案**: 10 条详细规则 → 否决，Rule 应下沉成 Skill 或脚本
**参考**: [working-principles.md](file:///workspace/knowledge/working-principles.md)

### D004: 为什么 audit 是这 10 项、权重为什么这样定

**日期**: 2026-06-26
**决策**: 10 项检查，满分 100，Tool-level isolation 权重最高(13)
**原因**: 工具级隔离是安全红线，权重最高；完成标准是质量核心，第二高(15)；其余按重要性分配
**参考**: [loop.py audit_loop](file:///workspace/src/hermes/loop.py)

### D005: 基线对比简化版——只对比 failure_items 集合

**日期**: 2026-07-07
**决策**: check_stop_rules 增加 baseline_failures 参数，只对比 failure_items 集合（不额外跑 pytest）
**原因**: Hermes 测试规模小（85个），失败集合通常为空。额外跑 pytest 成本高于收益。复用 checker 已有结果足够
**替代方案**: 每轮额外跑 pytest 做完整基线快照 → 否决，成本过高
**参考**: 文章《从Vibe Coding到Harness》第六章基线对比经验

### D006: 门禁软硬区分——hard_gate 声明性标签

**日期**: 2026-07-07
**决策**: STOP_RULES 和 audit_loop 检查项增加 hard_gate 字段
**原因**: 声明性分类标签，标识哪些是质量红线（hard_gate=True）、哪些是建议性检查（hard_gate=False）。不直接影响运行时行为——所有停止规则触发时都返回 stop_escalate，hard_gate 的价值在于让人类审查者快速识别"这条规则是红线还是建议"
**规则**: no_progress 为软门禁（建议拆分任务后 resume）；其余 6 项为硬门禁（红线，必须介入）。STOP_RULES 共 7 条，1 软 + 6 硬
**设计选择**: 不让 hard_gate 影响代码行为（YAGNI），避免"为概念而概念"的反模式 8。如未来需要差异化行为（如 hard_gate=False 时不设 NEEDS_HUMAN），再落地
**参考**: 文章《从Vibe Coding到Harness》第六章软硬门禁取舍

### D007: 软门禁留"伤疤"

**日期**: 2026-07-07
**决策**: audit_loop 返回 warnings 列表，写入 STATE.md 的 Audit Warnings 段落
**原因**: "不阻断"不等于"什么都不做"。绕过要在视觉上不舒服——AI 想绕没人拦，但绕了之后所有产物里都有显眼标记
**参考**: 文章《从Vibe Coding到Harness》第六章软门禁失败留疤

### D008: --gated 半自动模式

**日期**: 2026-07-07
**决策**: run_loop_continuous 增加 --gated 参数，每轮暂停等人工确认
**原因**: AI 对自己生成的东西天然无"否决欲望"，这是模型级偏置。关键节点必须有人
**限制**: Hermes 是 CLI 工具，无 IDE 弹窗，不实现"每分钟不超一次点击"等体感约束
**参考**: 文章《从Vibe Coding到Harness》第五章半自动模式

### D009: MCP 只接 GitHub

**日期**: 2026-07-07
**决策**: MCP 集成只接 GitHub，遵循"读多写少 + 写操作幂等 + 失败软降级"三原则
**原因**: GitHub 是最通用的外部系统。TAPD/iWiki/工蜂等是腾讯内部系统，不适用于 Hermes 的通用 CLI 定位
**边界**: MCP 不是 Harness 的主体，是外接能力接口。Hermes 定位是控制平面，不是交付平面
**参考**: 文章《从Vibe Coding到Harness》第九章 MCP 三原则

### D010: 产物清单校验

**日期**: 2026-07-07
**决策**: LoopState 增加 deliverables 字段，record_round 校验产物文件存在性
**原因**: "完成"不再是"AI 觉得做完了"，而是"产物清单全部存在"。让产生问题的人产生验证手段
**参考**: 文章《从Vibe Coding到Harness》第三章"开发完成"定义扩容

### D011: multi-perspective pattern（多视角并行分析）

**决策**：借鉴 ai-berkshire 的 4 视角并行框架，新增 `multi-perspective` pattern。N 个 perspective agent 全部 `parallel=True` 同消息并行 spawn，synthesizer 串行汇总。

**为什么这么定**：
- 分析类任务（非修复类）需要多视角对照，串行 builder-checker 不适合
- 复用已有 `fan_out`/`fan_in`，无新增并行原语（YAGNI）
- 默认 3 视角（正面/风险/中立），用户可改 LOOP.md

**不做**：不自研并行调度（threading/asyncio），复用 OpenClaw Gateway 的并行能力

### D012: 产物抽检声明性标记协议

**决策**：deliverables 中用 `<!-- claim: -->` 标记可验证断言，`audit_deliverables` 校验标记存在性（不校验内容真假）。

**为什么这么定**：
- 与现有 `<!-- failures:json -->` 协议一脉相承，已有先例
- 校验"内容真假"需要用户自验函数，当前无领域知识（YAGNI）
- 标记存在性已能抓到"agent 没写任何断言"的问题

**不做**：不做正则抽取数字 + 独立源比对（ai-berkshire 的 report_audit.py 模式），因为领域特定

### D013: 反端水硬约束仅限 multi-perspective

**决策**：`audit_loop` 对 `multi-perspective` pattern 检查 `summary.md` 含 `<!-- conclusion: -->` 标记。其他 pattern 不受约束。

**为什么这么定**：
- 分析类任务必须收敛到明确结论，禁止"一方面...另一方面..."
- 探索类任务（builder-checker/knowledge-hygiene）强行收敛会催生假结论
- hard_gate=True 但不阻断运行（声明性标签，与 D006 一致）

**不做**：不做全局"结论明确度"检查（风险过高）

### D014: MCP 双源标记当前预留

**决策**：MCP 读方法返回 `_sources` 字段标记数据来源。当前仅 GitHub 单源，audit_loop 单源产生 warning 不阻断。

**为什么这么定**：
- Hermes 当前只有 GitHub MCP，双源验证无法真正生效
- `_sources` 字段为未来扩展预留，新增 MCP 时无需改 audit 逻辑
- warning 不阻断，避免当前所有 MCP 数据都报错

**不做**：不做主动双源取数 + 误差检查（当前无第二个数据源，YAGNI）

### D015: escalation_info 持久化（P0-1）

**日期**: 2026-07-11
**决策**: LoopRound 增加 `escalation_info: dict` 字段，record_round 在 check_stop_rules 返回后回填，随 meta.json 持久化。

**根因（时序矛盾）**：record_round 在 `loop.rounds.append(round_data)` 之后才调用 check_stop_rules，但 escalation_info 从未回填到 round_data，_save_loop_meta 持久化的 round 缺该字段，导致 matched_signals / blocker / new_failures 等诊断信息永远无法跨会话追溯——人类看 logs 时只知道"停止了"，不知道"为什么停止"。

**为什么不做 Verdict 三态**：对抗审查发现 `beyond_capability` 停止规则已用 16 个信号词 + `escalation_info.blocker` 覆盖了"外部依赖阻塞"场景。再加一套 "BLOCKED:" 前缀文本协议是第二个脆弱机制，会削弱已有的信号词机制（第一性原理：同一问题不应有两套检测路径）。

**为什么不做 confidence 字段**：confidence 是主观估计，无校验手段，会变成"看起来科学但无意义"的字段（YAGNI + 反模式 8）。

**展示**：main.py `_format_escalation_info` helper 在 run/continuous/resume/logs 5 处渲染持久化字段。
**参考**: [loop.py LoopRound.escalation_info](file:///workspace/src/hermes/loop.py)、Multica 文章"准出字段 Verdict"能力

### D016: loop_metrics 指标看板 + estimate_cost 历史平均护栏（P0-2）

**日期**: 2026-07-11
**决策**: 新增 `loop_metrics(name)` 聚合轮次/令牌/通过率统计 + CLI `hermes loop metrics` 命令；estimate_cost 改用历史平均，带最小样本量护栏。

**为什么加指标看板**：借鉴 Multica 组织级 Loop Engineering 的"指标看板"能力。此前可观测性只有"看最后一轮"，无法回答"这个 loop 历史平均消耗多少 token / 通过率多少"。指标看板让 loop 从"黑盒单次执行"升级为"可追踪的持续过程"。

**estimate_cost 护栏根因（小样本陷阱）**：直接用历史平均在样本极少时不稳定——若 loop 只跑 1 轮就因 beyond_capability 停止，历史均值要么极低（import error 早停）要么极高（builder 读很多文件），外推不如固定 50k 准确。
- 护栏1：过滤 `tokens_used=0` 轮次（未实际执行/记录缺失会拉低均值）
- 护栏2：有效样本 < 3 时回退固定 50k（MIN_SAMPLE=3）
- 新增 `estimate_source` 字段标记来源（historical_avg / fallback_default），让用户知道估算是基于真实数据还是默认值

**参考**: [loop.py loop_metrics](file:///workspace/src/hermes/loop.py)、Multica 文章"指标看板"能力

### D017: 为什么砍掉 P1-1 Rework 语义

**日期**: 2026-07-11
**决策**: 不实现 Rework（部分回滚中间轮次）语义。

**对抗审查结论**：
1. **stop rules 依赖连续两轮比对**：regression / same_failure_twice / no_progress 都依赖 `rounds[-2]` vs `rounds[-1]` 的连续比较。Rework 删除中间轮次会破坏这个不变量，导致跨边界误判（第一性原理：状态机的转换前提不能被破坏）
2. **resume_loop 已覆盖"重新开始"**：NEEDS_HUMAN / ERROR 状态下 resume_loop 清空 rounds + budget 重置为 IDLE，已提供"全量重启"能力。Rework 是介于"全量重启"和"继续"之间的中间态，复杂度高但收益不明确
3. **状态机污染**：引入 Rework 需要在 LoopStatus 枚举加新状态 + 转换规则，增加状态机复杂度（反模式 8：复杂度自给自足）

**替代方案**：需要部分重做时，人类审查 logs 后手动调整 LOOP.md 目标，用 resume_loop 全量重启。

### D018: 为什么砍掉 P1-2 sub_agents 声明驱动

**日期**: 2026-07-11
**决策**: 不激活 LOOP_PATTERNS 中 sub_agents 声明字段的运行时读取，保持 runner.py 硬编码执行路径。

**对抗审查结论**：
1. **声明字段表达力不足**：sub_agents 声明只有 `role / agent_file / parallel / check_type`，无法表达"builder 依赖 checker 上一轮的 previous_report"这类跨轮次依赖。激活后反而不如当前硬编码灵活
2. **aggregate_results 空列表陷阱**：`all([])` 返回 True，空 task 列表会被误判为 ALL GREEN。激活 sub_agents 前必须先修复这个陷阱，但当前硬编码路径不触发它
3. **死字段激活的隐性成本**：sub_agents 当前是"文档性声明"（人类阅读用），激活成"运行时驱动"需要全套测试 + 边界处理，收益是"少几行硬编码"，成本收益比不合理（YAGNI）

**保留**：sub_agents 字段保留为声明性文档，供人类理解 pattern 结构。

## 二、反模式清单（永远不要做的事）

> 来源：文章《从Vibe Coding到Harness》第十章 + Hermes 项目实战教训

1. **❌ 第一天就拆 7 个 Agent** — Agent 是被撞墙逼出来的，不是设计出来的。从 builder-checker 两角色开始，哪里痛补哪里
2. **❌ 让 AI 跑确定性脚本** — 调度/门禁/测试/提MR是纯确定性工作，下沉成 bash 脚本，不让 AI 解释执行徒增 token
3. **❌ 下游 Agent 改上游产物** — 下游能改上游，整条流程的责任边界就崩了。需要改时只能提阻塞项
4. **❌ 把所有失败都设成硬门禁** — 不是质量红线就别阻断。频繁打断会让团队怀疑工程化的价值
5. **❌ 没有基线对比就相信 AI 说的"这是历史问题"** — 剥夺 AI 的解释权，用 B-A 的新增失败判定
6. **❌ 把团队规约存进 Memory** — 团队要对齐的东西必须落到仓库；Memory 只放纯个人偏好
7. **❌ 一次到位设计 Harness** — Harness 不是设计出来的，是哪儿痛补哪儿。先跑通开发闭环，再扩展
8. **❌ 复杂度自给自足** — 机制主要在 fix 自己引入的副作用时，80% 应该删掉（YAGNI 原则）
9. **❌ 修复后不立即 commit + push** — 本地 commit 未 push 时，环境重置会丢失所有工作（Hermes 实战教训）
10. **❌ 让用户每分钟点一次以上** — 体感不对，团队会主动绕过工具退回 Vibe Coding

## 三、演进时间线

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1.0 | 初始 5 条停止规则、builder-checker pattern、工具级硬隔离 |
| 2026-06-26 | v0.2.0 | 扩展到 7 条停止规则、audit_loop 10 项检查、working-principles 2 条 |
| 2026-06-29 | v0.3.0 | issue-triage + changelog-draft pattern、cost/badge/interactive CLI |
| 2026-07-06 | v0.3.1 | _terminal_status_to_stop 统一状态映射、conftest 隔离、profile 解析器重写 |
| 2026-07-07 | v0.4.0 | 基线对比简化版、软门禁留疤、门禁软硬区分、产物清单校验、--gated 半自动、GitHub MCP |
| 2026-07-07 | v0.5.0 | multi-perspective pattern、产物抽检准出、反端水硬约束、MCP 双源标记（借鉴 ai-berkshire） |
| 2026-07-11 | v0.6.0 | escalation_info 持久化（修复时序矛盾）、loop_metrics 指标看板、estimate_cost 历史平均护栏（借鉴 Multica 组织级 Loop Engineering） |

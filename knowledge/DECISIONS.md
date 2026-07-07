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

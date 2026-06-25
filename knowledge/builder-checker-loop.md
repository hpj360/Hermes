# 三个文件搭建 Loop Engineering — 实践指南

> 参考文章：《三个文件，搭建 Loop Engineering》
>
> 本文记录了文章的核心实践方法，以及 Hermes 如何将其融合到 `hermes loop` 工具链中。

## 核心思路

**一句话**：把写代码和查代码拆成两个 Agent，让编排器循环调度，查到全绿为止。

传统方式是单次的：你写需求 → Agent 生成代码 → 你肉眼看一遍 → 觉得没问题就收工。但肉眼看容易漏：代码能跑不代表测试全过，测试过了不代表类型没错。

Loop Engineering 把验证变成系统的内置环节：自动跑完所有检查 → 有问题自动反馈 → 修完再查 → 直到全绿。

## 三文件模式

### 文件一：builder.md（只写代码）

```yaml
---
name: builder
description: 负责编写和修复代码
tools: Read, Write, Edit, Glob, Grep, Bash
---
```

关键设计：
- **有 Write 和 Edit 工具**，能修改代码
- 接到任务时：先读项目约定（AGENTS.md/README/package.json），理解架构再动手
- 接到修复请求时：逐条阅读 checker 报告，定位根因（区分症状和病因），一次只修一个根因
- **红线**：绝不弱化测试来通过、绝不删除/跳过检查、不要顺手重构不相关代码

### 文件二：checker.md（只查代码）

```yaml
---
name: checker
description: 运行所有检查并报告失败项。绝不修改代码。
tools: Read, Grep, Glob, Bash
---
```

关键设计：
- **没有 Write 和 Edit 工具** — 这是工具级硬隔离，不是提示词约束
- 即使 checker "想"修复问题，它物理上无法修改任何文件
- 先读 package.json 的 scripts 字段发现检查命令，不假设
- 报告格式：ALL GREEN + 逐项通过证明 / FAILED + file:line - 什么坏了
- **红线**：绝不意译失败信息（复制原始错误）、绝不省略小问题、绝不自己尝试修复

### 文件三：stop-rules.md（停止规则）

六条刹车条件，覆盖实战中常见的卡死模式：

| # | 规则 | 触发条件 | 动作 |
|---|------|---------|------|
| 1 | ALL GREEN | 所有检查通过 | 停止（成功） |
| 2 | 轮次用尽 | 达到轮次上限（默认5轮） | 停止，升级 |
| 3 | 同一失败连续两轮 | builder在猜，不是在修 | 停止，升级 |
| 4 | 回归 | 修复导致之前通过的检查失败 | 停止，升级 |
| 5 | 无实质进展 | 连续2轮失败项数量未减少 | 停止，拆分任务 |
| 6 | 超出能力边界 | 外部依赖/环境问题 | 停止，报告阻塞点 |

升级协议：停止时必须携带当前轮次、失败项列表、已尝试方法、失败原因判断。

## 关键原则

### 1. 工具级硬隔离（不是提示词约束）

checker.md 的 tools 字段没有 Write 和 Edit。这不是靠提示词说"你不要改代码"，而是从工具可见性层面保证 checker 物理上无法修改任何文件。

**为什么重要**：提示词约束可以被绕过（Agent可能"觉得"需要改一行），但工具不可见就是不可见。

### 2. 不过滤原则

编排器拿到 checker 的失败报告后，必须**原样转发**给 builder，不要自己解读或过滤。

**为什么重要**：编排器倾向于帮忙总结，但总结会丢失行号、堆栈轨迹、中间输出这些 builder 定位根因需要的关键细节。报告模糊一轮，整个循环就白跑一轮。

### 3. 报告格式标准

统一的报告格式确保信息完整传递：

**builder 汇报**：
```
改了什么：<一句话>
修改文件：<file1>, <file2>, ...
本地检查结果：<通过/失败>
```

**checker 报告**：
```
ALL GREEN
  test: 848 passed, 0 failed
  lint: 0 errors
  tsc: no errors
```
或
```
FAILED
  src/foo.ts:42 - undefined is not a function - test
  src/bar.ts:15 - missing return type - lint
```

## Hermes 中的实现

### CLI 命令

```bash
# 创建 builder-checker loop（自动生成6个文件）
hermes loop init my-task -p builder-checker

# 查看停止规则
hermes loop stop-rules

# 审计就绪度（包含工具级隔离检查、停止规则检查）
hermes loop audit my-task

# 查看 loop 运行指引
hermes loop run my-task
```

### 生成的文件

`hermes loop init <name> -p builder-checker` 生成6个文件：

```
.loops/<name>/
├── LOOP.md          # Loop配置：目标、边界、Maker/Checker分工、停止规则摘要
├── STATE.md         # 跨轮状态
├── loop-budget.md   # 成本预算
├── builder.md       # builder Agent定义（有Write/Edit工具）
├── checker.md       # checker Agent定义（无Write/Edit，工具级硬隔离）
├── stop-rules.md    # 六条停止条件 + 红线 + 升级协议 + 编排器规则
└── meta.json        # 机器可读状态
```

### 停止规则检查

`check_stop_rules()` 函数可被外部编排器调用，根据轮次历史自动判断是否触发停止条件：

```python
from hermes.loop import check_stop_rules, LoopRound

result = check_stop_rules(
    name="my-task",
    current_round=3,
    max_rounds=5,
    rounds=[
        LoopRound(round_num=1, ..., failure_count=3, failure_items=["test::foo", "lint::bar"]),
        LoopRound(round_num=2, ..., failure_count=3, failure_items=["test::foo", "lint::bar"]),
    ],
)
# result["should_stop"] == True
# result["rule_id"] == "same_failure_twice"
```

### 审计新增检查项

`hermes loop audit` 现在检查两个新维度：
- **Stop rules defined (6 conditions)** — 是否定义了全部六条停止规则
- **Tool-level isolation** — checker.md 的 tools 字段是否排除了 Write 和 Edit

## 实践中的坑

1. **builder 喜欢顺手改点别的** — 读完一圈代码后有冲动把看到的问题一起改了。停止规则里的刹车条件存在就是为了在拆东墙补西墙时及时叫停。

2. **checker 的报告质量决定循环效率** — 如果只贴最后一行错误信息没带上下文，builder 找不到根因瞎猜，浪费整轮。checker 必须保留完整输出。

3. **编排器会自作主张总结失败信息** — 转述过程中行号丢了、堆栈丢了、中间输出丢了，只剩一句概括。必须在提示词里写好"不要解读或过滤"。

## 与文章前一篇的关系

上一篇文章《Agent Loop 与 Loop Engineering 区别》讲的是**概念**（Agent Loop是运行机制，Loop Engineering是系统设计方法论）。

这篇文章讲的是**实践**（三个文件怎么搭、怎么跑、怎么刹车）。

Hermes 项目将两者融合：概念层面有 [knowledge/loop-engineering.md](file:///workspace/knowledge/loop-engineering.md) 知识文档，实践层面有 `hermes loop` CLI工具链 + builder-checker模式 + 六条停止规则 + 工具级硬隔离。

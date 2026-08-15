# ADR 0018: 引入 Agent Preset（工具面 + Prompt 收窄，借鉴 DSH Preset）

Status: Accepted
Date: 2026-08-15

## Context

DSH 的 Preset 决定某个会话看见哪些工具、提示词和投影单元——其生产价值在于
"删掉什么、替换什么"（如社区 Data Agent 只保留 read/edit/write 并用 `sqlcmd`
替换 bash），而不是堆工具。实测文章给出硬证据：默认配置下"回复 PONG"首包吃掉
13,467 input token，主要来自工具说明、仓库规则与 skill 摘要。

Hermes 当前的能力收窄是**分散且狭窄**的：

- `ROLE_MCP_WHITELIST`（orchestrator.py:85-95）只白名单 MCP 工具，不含内置工具、
  prompt、model、token 预算；
- denylist 从 `LOOP_PATTERNS` 注入（runner.py:287-288），只保护路径，不定义能力面；
- `AgentTask` 的 `allowed_mcp_tools` / `token_limit` / `agent_file` 等字段互相独立，
  无命名、可复用的组合；sub-agent 的 agent_definition 直接读 builder.md/checker.md
  全文，无 prompt 片段级组合。

后果：每个 loop pattern 的"这个角色能做什么"散落在 4 个位置（LOOP_PATTERNS 的
sub_agents、ROLE_MCP_WHITELIST、AgentTask 字段、agent .md 文件），无法一处声明、
无法复用、无法 dump 审计。领域 Agent（如只读数据查询角色）要临时拼装，成本高。

**既有决策约束**：`knowledge/DECISIONS.md` D018 已决定**不激活**
`LOOP_PATTERNS.sub_agents` 声明字段的运行时读取（对抗审查理由：跨轮次依赖表达力
不足、aggregate_results 空列表陷阱、死字段激活的隐性成本），runner 保持硬编码
执行路径。本 ADR **不推翻 D018**：preset 注入走角色名约定（第 4 条），
sub_agents 仍保持文档性声明。

## Decision

新增 `hermes/presets.py`，定义命名的 **AgentPreset**，作为 sub-agent 能力面的
唯一组合单元：

1. **AgentPreset 字段**：
   - `name` / `description`
   - `tools: list[str] | None` — 内置工具白名单（Read/Grep/Glob/Bash/Write...，
     None=不限制）
   - `mcp_tools: list[str] | None` — MCP 工具白名单（None=不限制，`[]`=禁全部；
     与 AgentTask.allowed_mcp_tools 同语义）
   - `denylist: list[str]` — 路径黑名单（**与 pattern 级 denylist 取并集**，见第 3 条）
   - `token_limit: int` — 单 agent token 上限（沿用 P1 熔断语义）
   - `model: str | None` — 模型覆盖
   - `prompt_sections: list[str]` — prompt 片段（.md 文件路径或内联文本），
     按序拼接到 agent_definition 之后（由 `_build_spawn_payload` 基于 **resolve
     后的 preset 对象**应用，**先于 payload 构造与轨迹记录**，保证 ADR-0017
     轨迹快照与实际派发一致）
   - `schema_version: int`

2. **内置 Preset**（模块级 `BUILTIN_PRESETS`，行为零漂移）：
   - `builder-default`：mcp_tools = `ROLE_MCP_WHITELIST["builder"]`（以白名单 dict
     为 mcp_tools 字段的数据源，避免双份事实源），token_limit=50000
   - `checker`：mcp_tools=[]，token_limit=50000（checker_lint/type/test 等
     checker 系角色经 `_ROLE_PRESET_MAP` 统一映射到这一个 preset）
   - `synthesizer`：mcp_tools=[]，token_limit=50000
   - `perspective`：mcp_tools=**None**（与现状一致——`_get_role_whitelist` 对
     perspective 前缀匹配落空返回 None=不限制；收窄留待单独立项，不在本 ADR 引入
     行为变化）
   - `data-analyst`（新，示范领域 Agent）：tools=[read, grep, glob]，mcp_tools=[]，
     prompt_sections=[只读查询约束片段]——**只读**（edit/write 与只读约束互相否定，
     不做矛盾预设）
   - mcp_tools 以外的字段（token_limit/denylist/model/prompt_sections）为内置
     preset 显式声明值，数据源是 preset 定义本身，非 ROLE_MCP_WHITELIST。

3. **解析优先级与安全红线**（`AgentTask.preset: str | None` 新字段）：
   - 优先级：`显式 AgentTask 字段 > preset 定义 > 角色默认值（ROLE_MCP_WHITELIST）`。
   - "显式"的判定（逐字段，消除 None vs [] 歧义）：
     - `allowed_mcp_tools`：`is not None` 即显式（含 `[]`）；None = 未设置 →
       preset 填充 → 否则角色默认。
     - `tools`：`is not None` 即显式；None = 未设置 → preset 填充。
     - `model`：`is not None` 即显式。
     - `token_limit`：等于类默认值 50000 视为未显式设置（可被 preset 覆盖）；
       其他值（含 0=不限制）视为显式，preset 不得覆盖。
     - `denylist`：**并集语义**（pattern 级 ∪ preset），preset 永远不能清空或
       收窄 pattern 级保护——这是 L3 安全红线：`auth/ payment/ security/ .env *.key`
       等保护即使挂一个 denylist=[] 的 preset 也不可绕过。契约测试强制该语义。
   - 安全字段（mcp_tools/denylist/tools）preset **只可收紧、不可放宽**：显式
     收紧值（如显式 `mcp_tools=[]`）优先于 preset 的宽白名单；未设置时 preset 的
     值同样只能比角色默认更紧（内置 preset 定义时人工保证，用户 preset 由
     resolve 时的收紧校验兜底——preset 值比角色默认宽时记 warning 并采用角色默认）。

4. **注入路径（尊重 D018）**：不激活 sub_agents 运行时读取。preset 按**角色名
   约定**映射——`_prepare_and_spawn` 中按 `task.role` 查角色→内置 preset 映射表
   （builder→builder-default、checker*→checker、synthesizer→synthesizer、
   perspective_*→perspective），runner 硬编码执行路径不变；用户 preset 可通过
   `AgentTask.preset` 显式挂载（当前唯一显式入口是构造 AgentTask 的代码，
   runner 未来按需传入，不改变 sub_agents 的声明性）。

5. **CLI**：`hermes loop presets [list|show <name>]` —— 打印内置与已安装 preset，
   输出含最终生效的工具面（这是 `--dump-config` 思想的局部落地）。

6. **用户自定义**：`.state/presets/*.json`（或 `HERMES_PRESETS_DIR` 指定目录），
   加载失败（损坏文件）记 warning 并跳过。**容错不对称是有意设计**：数据损坏
   （文件问题）跳过不阻断；引用错误（LOOP_PATTERNS/代码引用不存在的 preset 名）
   fail loud 抛 ValidationError——能力面是安全敏感配置，静默降级违反最小权限原则。

## Consequences

- **正面**：
  - 能力面一处声明、按名复用；领域 Agent 收窄从"拼字段"降为"写一个 JSON"；
  - 直接回应文章教训——首包 token 膨胀可通过 preset 收窄工具面与 prompt 控制；
  - `hermes loop presets list` 提供"这个角色最终能干什么"的审计视图；
  - 与 ADR-0017 轨迹日志配合：preset 解析结果进入 dispatch 快照，可审计。
- **负面 / tradeoff**：
  - 新增一层抽象；`ROLE_MCP_WHITELIST` 与 preset 并存期需维护"角色→preset"映射，
    该映射的 mcp_tools 数据源仍是白名单 dict（单一事实源成立）；
   - Gateway 对内置工具白名单键（`allowed_builtin_tools`，新键；`allowed_tools`
     保持 MCP 白名单语义不变）的支持未知，沿用前向兼容策略：Gateway 支持则强制
     执行，不支持则由 Hermes 事后审计兜底——兜底审计 `_audit_builtin_tool_violations`
     在本 ADR 范围内实现（复用 `_audit_mcp_violations` 的模式，对非 mcp_ 前缀的
     tool_calls 名比对 tools 白名单）；其产出计入 `aggregate_results` 的
     `Tool violations` summary 计数（**仅记录、不强制失败**——强制失败只保留给
     denylist/路径违规这一 L3 红线）；
  - preset 的 prompt_sections 进入 agent_definition 后同样受轨迹日志约束
    （ADR-0017），拼接必须发生在 `_build_spawn_payload` 之前。
- **后续约束**：新增 loop pattern 的 sub_agents 必须声明 preset（未声明的
  保留角色默认值并记 warning）；内置 preset 的字段变更需同步更新
  `test_presets` 的契约测试（含"preset 不可清空 pattern denylist"红线用例）。

## 参考

- DSH Preset：`packages/preset/agent-presets`（standard/minimal/领域 Agent 组合）
- 分析报告：`docs/deepseek-harness-analysis.md` §3.1 方案 C 之 P0-2
- 既有决策：`knowledge/DECISIONS.md` D018（sub_agents 不激活运行时读取）

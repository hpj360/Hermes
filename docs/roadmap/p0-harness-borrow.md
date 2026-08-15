# P0 Harness 借鉴实施 Spec：轨迹不变量 + Agent Preset

> 依据：`docs/deepseek-harness-analysis.md` §3.1 方案 C 之 P0 两项
> ADR：`docs/adr/0017-log-reconstruction-invariant.md`、`docs/adr/0018-agent-preset.md`
> 状态：已实施并验收（pytest 1678 通过 / ruff 0 / mypy 0），待 commit
> 原则：零新依赖、向后兼容（现有 tests/ 约 1477 个测试全绿）、每阶段独立 commit + push
> 估期：阶段 1 约 1.5-2 天；阶段 2 约 2-2.5 天；阶段 3 约 0.5 天

---

## 阶段 1：轨迹不变量（ADR-0017）

### 1.1 新文件 `src/hermes/trajectory.py`

```
TrajectoryDesyncError(Exception)          # 校验失败，派发中止
@dataclass TrajectoryEvent                 # seq / time / type / cycle / data
class TrajectoryLogger:
    __init__(path: Path, cycle: str = "0")
    record(type: str, data: dict) -> int   # 追加一行，返回 seq；内部 threading.Lock
                                           # 串行化计数器+追加；写失败抛异常（fail loud）
    events() -> list[TrajectoryEvent]      # 读取（损坏行跳过 + warning）
    last_seq() -> int                      # 供 record_round 回填
def assert_reconstructable(events: list[TrajectoryEvent], request_seq: int, payload: dict) -> None
    # 重放 seq==request_seq 的 dispatch/request 事件 → derived；
    # 规范化 JSON 比较；不一致抛 Desync
def verify_trajectory(path: Path) -> dict  # 离线审计：行完整性/seq 连续/request-result
                                           # 配对完备/agent_definition sha256 与当前文件一致
```

**设计要点**：
- `_build_spawn_payload(task)` 定义在 **orchestrator.py**（模块级纯函数，唯一
  payload 构造点，替换 `spawn_agent` 内联构造）；trajectory.py 只负责日志与校验。
- `dispatch/request.data` = payload 全文（含 agent_definition 全文）+ `role` +
  `round_num`；`dispatch/result.data` = `request_seq` + `role` + `round_num` +
  session_id/status/tokens_used/completed_at。失败路径（desync/Gateway 不可用/
  超时）同样补记 result，保证配对完备。
- `AgentTask` 新增 transient 字段 `trajectory_request_seq: int | None`（不进
  to_dict、不入 payload）。

### 1.2 改动文件

| 文件 | 改动 |
|------|------|
| `src/hermes/trajectory.py` | 新模块（1.1 接口） |
| `src/hermes/orchestrator.py` | ① 新增模块级纯函数 `_build_spawn_payload(task) -> dict`；② `OpenClawClient` 保持 `spawn_agent` 旧签名不变（向后兼容既有 mock），新增 `spawn_payload(payload: dict)` 入口，`spawn_agent` 内部委托 `_build_spawn_payload` + `spawn_payload`（行为等价，存量测试零改动）；③ `Orchestrator.__init__` 增加 `trajectory: TrajectoryLogger | None = None`；④ `_prepare_and_spawn`：构造 payload → `trajectory.record("dispatch/request", ...)` 并暂存 seq → `assert_reconstructable(...)` → `client.spawn_payload(payload)`；desync/写失败时 task.status="failed"、result 记录错误、不发 HTTP、补记 result 事件；⑤ `fan_in` 完成后补记 `dispatch/result`（含 request_seq） |
| `src/hermes/runner.py` | 在 `_run_builder_checker`（runner.py:269）与 `_run_multi_perspective`（runner.py:376）两处 Orchestrator 构造点注入 TrajectoryLogger（路径 `.loops/<name>/trajectory.jsonl`）；generic 路径（runner.py:204）不派发、不注入；guidance/local 模式无派发不启用 |
| `src/hermes/loop.py` | `record_round` 增加关键字参数 `trajectory_seq: int | None = None`（默认 None 向后兼容），返回值附 `trajectory_seq` 键；`resume_loop` 新周期开始时归档旧 trajectory（`trajectory.<cycle>.jsonl`），cycle 从 1 递增 |
| `src/hermes/cli_loop.py` | 新子命令 `loop trajectory <name> [--json] [--verify]`（verify 调用 `verify_trajectory`） |
| `src/hermes/workbench/llm.py` | 增加可选 `trajectory: TrajectoryLogger | None` 参数：发送前 record `request/header`（model/temperature/max_tokens）与 `request/context`（messages），并执行同一校验；默认 None 行为不变 |
| `src/hermes/config.py` | 新字段 `HERMES_LLM_TRAJECTORY_ENABLED: bool = False`（仅门控 llm.py 直连路径；Orchestrator 派发路径默认始终开启） |
| `src/hermes/gepa.py` | `auto_generate_variants` 在 `HERMES_LLM_TRAJECTORY_ENABLED=true` 且调用方提供 trajectory 时启用（opt-in；当前无生产调用方，为未来 GEPA 周期接入预置） |

### 1.3 测试计划（新文件 `tests/test_trajectory.py`，目标 25+ 用例）

1. `TrajectoryLogger.record`（7 用例：基本追加/seq 递增/损坏行跳过/目录自动创建/
   线程并发 10×50 无丢失 **且 seq 集合唯一 + 行内 seq 单调**/写失败抛异常/last_seq）
2. `_build_spawn_payload`（3 用例：全字段/无 agent_file/字段与 spawn_agent 旧签名
   构造结果等价——保证重构行为不变）
3. `assert_reconstructable`（5 用例：一致通过/字段篡改抛 Desync/事件缺失抛 Desync/
   request_seq 不存在抛 Desync/空 data 边界）
4. Orchestrator 集成（mock client，6 用例：正常派发记录配对事件/desync 时
   `spawn_payload` 调用次数==0 + task failed + result 事件补记/Gateway 不可用
   （session None）也补记 result/无 trajectory 注入行为不变=向后兼容/
   `spawn_agent` 旧签名调用等价于 `spawn_payload`/result 事件携带 request_seq
   可配对 4-task 轮）
5. `workbench.llm` trajectory 注入（2 用例：记录后发送/desync 中止）
6. `verify_trajectory` 离线审计（3 用例：完好通过/删 result 报配对不完备/改
   agent_definition 全文报哈希不一致）
7. CLI `loop trajectory`（2 用例：--json 输出/--verify 非零退出）
8. resume 归档（2 用例：新周期归档旧文件/cycle 递增）

### 1.4 验收标准

- `pytest tests/` 全绿（含新增）；`ruff check src/ tests/` 与 `mypy src/` 零错误；
  覆盖率不低于现状（83%/88.5% 基线不降）
- 存量 3 处 FakeClient（tests/test_loop.py:2379、2410、2786 附近）零改动通过
  （`spawn_agent` 签名不变的直接证据）
- 自动化验收代替手工：pytest CLI 用例覆盖 trajectory 命令；手工仅做一次端到端
  观察（`hermes loop run test-bc` 后 `--verify` 通过、改 agent_definition 后
  verify 非零退出）

---

## 阶段 2：Agent Preset（ADR-0018）

### 2.1 新文件 `src/hermes/presets.py`

```
@dataclass AgentPreset: name/description/tools/mcp_tools/denylist/token_limit/model/prompt_sections/schema_version
    to_dict() / from_dict()                    # 序列化往返
BUILTIN_PRESETS: dict[str, AgentPreset]
    # mcp_tools 以 ROLE_MCP_WHITELIST 为数据源；其余字段为显式内置默认值
    # perspective 的 mcp_tools=None（与现状一致，不引入行为变化）
ROLE_PRESET_MAP: dict[str, str]                # 角色名约定：builder→builder-default、
                                               # checker*/synthesizer/perspective_*
def load_user_presets(presets_dir: Path | None) -> dict[str, AgentPreset]  # 损坏文件跳过 + warning
def resolve_preset(task: AgentTask) -> AgentTask
    # 显式字段（allowed_mcp_tools/tools/model is not None；token_limit != 50000）> preset > 角色默认
    # denylist = pattern ∪ preset（并集，红线）；未知 preset 名 → ValidationError
    # preset 比角色默认宽的安全字段 → warning + 采用角色默认（只可收紧）
def apply_prompt_sections(agent_definition: str, preset: AgentPreset) -> str  # 按序拼接
```

### 2.2 改动文件

| 文件 | 改动 |
|------|------|
| `src/hermes/presets.py` | 新模块（2.1 接口） |
| `src/hermes/orchestrator.py` | ① `AgentTask` 增加 `preset: str | None = None`、`tools: list[str] | None = None`（内置工具白名单）、`model: str | None = None`，`to_dict` 补齐新字段（加性，存量断言安全）；② `_prepare_and_spawn`：先 `resolve_preset(task)` → `apply_prompt_sections` → 再 `_build_spawn_payload`（顺序锁定：拼接必须先于快照）；③ payload 新增键 `allowed_builtin_tools`（内置工具白名单；`allowed_tools` 保持 MCP 白名单语义不变，兼容现有测试断言 test_loop.py:2396）；④ 新增 `_audit_builtin_tool_violations(task, messages)`：对非 mcp_ 前缀的 tool_calls 名比对 tools 白名单，fan_in 时执行并记 `tool_violations`（"Gateway 不支持则 Hermes 事后审计兜底"的实现） |
| `src/hermes/runner.py` | `_run_builder_checker` / `run_parallel_perspectives` 构造 AgentTask 时按 ROLE_PRESET_MAP 挂内置 preset（或经 `_prepare_and_spawn` 的角色约定自动解析，实现时二选一，推荐后者：runner 零改动）；**不激活 LOOP_PATTERNS.sub_agents 运行时读取**（尊重 DECISIONS.md D018） |
| `src/hermes/cli_loop.py` | 新子命令 `loop presets [list|show <name>]`，list 输出内置 + 用户 preset 的最终工具面（等效于局部 dump-config） |
| `src/hermes/config.py` | 新字段 `HERMES_PRESETS_DIR: str | None = None` |

### 2.3 测试计划（新文件 `tests/test_presets.py`，目标 30+ 用例）

1. 序列化往返（3 用例）
2. `resolve_preset` 优先级矩阵（10 用例：显式 allowed_mcp_tools 覆盖（含显式 []）/
   显式 tools 覆盖/显式 model 覆盖/token_limit 默认 50000 被 preset 覆盖 + 显式
   0 不被覆盖/未指定 preset 回退角色默认/未知 preset 抛 ValidationError/preset
   比角色默认宽时采用角色默认 + warning/preset 收紧生效/denylist 并集非替换/
   prompt_sections 顺序）
3. **L3 红线契约**（3 用例：denylist=[] 的 preset 挂在 builder-checker 上，
   pattern 级 `auth/` 等保护仍生效/路径审计仍执行/强制失败仍触发）
4. `load_user_presets` 容错（2 用例：损坏 JSON 跳过/目录不存在返回空）
5. `apply_prompt_sections`（2 用例：文件片段/内联片段/顺序）
6. Orchestrator 集成（5 用例：preset 解析后 payload 的 `allowed_builtin_tools`
   正确/`allowed_tools` 仍是 MCP 白名单（防语义漂移）/无 preset 行为不变=现有
   测试基线/data-analyst preset 只读工具面进入 payload/checker preset
   mcp_tools=[] 保留）
7. 内置 tool 审计 `_audit_builtin_tool_violations`（3 用例：违规检测/白名单内
   不报/None 白名单跳过）
8. AgentTask.to_dict 新字段（2 用例：preset/tools/model 序列化）
9. CLI（4 用例：list/show/未知名报错/json 输出）

### 2.4 验收标准

- 现有 tests/test_loop.py（orchestrator 测试所在文件）全绿——内置 preset 等价于
  现状默认值的直接证据
- 自动化断言代替人工比对：`BUILTIN_PRESETS["builder-default"].mcp_tools ==
  ROLE_MCP_WHITELIST["builder"]` 等映射契约测试入册
- 覆盖率不低于现状；`ruff`/`mypy` 零错误

---

## 阶段 3：收尾（两阶段共用）

| 项 | 内容 |
|----|------|
| 文档 | ① `knowledge/multi-agent-harness.md` 增补"提升 6（轨迹不变量）/提升 7（Agent Preset）"两节（遵循该文档惯例：含实现内容 + commit hash）；② `CHANGELOG.md` 记录；③ `docs/deepseek-harness-analysis.md` 修订 §3.2 P0-1 措辞（"模型所见可重建" → "Hermes→Gateway 派发输入可重建"，与 ADR-0017 边界声明一致）并标注 P0 完成状态；④ 两份 ADR 状态翻为 Accepted；⑤ `ROADMAP.md` 增加本项指针 |
| 验证 | `bash scripts/verify-state.sh` 通过；按 AGENTS.md 规则分阶段 commit + `scripts/git-push.sh`（每阶段独立推送）；实施完成后启动多 Agent 对抗性审查（AGENTS.md 工作原则 2），发现的问题回溯修复 |
| 回滚 | 以 commit 为回滚单元：`git revert` 对应阶段 commit；阶段 1 的行为等价性由"spawn_agent 旧签名委托新入口 + 等价性测试"兜底，阶段 2 由"内置 preset 等价现状 + 存量测试全绿"兜底 |

## 不做的事（本 Spec 边界）

- 不做 Trajectory UI（P1 项，数据源就位后另立项）
- 不做 Gateway 内部消息级不变量（受控范围外，见 ADR-0017 边界声明）
- 不做 DSH 桥接执行后端（P2 项，待 DSH 脱离 preview）
- 不做全量 `hermes dump-config`（P2 项，`loop presets list` 只是局部落地）
- 不激活 LOOP_PATTERNS.sub_agents 运行时读取（DECISIONS.md D018 维持有效）

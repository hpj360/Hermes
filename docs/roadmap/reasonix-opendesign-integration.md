# 集成方案：Reasonix 三技术点 + OpenDesign MCP 桥接

> 依据：`docs/ecosystem-reasonix-opendesign-assessment.md`
> 状态：A（Reasonix 三技术点）已实施并验收；B（MCP 桥接）已由并发流的通用 MCP client 交付（见下）
> 原则：零新运行时依赖、向后兼容、每阶段独立 commit + push
> 估期：A1 约 1 天；A2 约 1-1.5 天；A3 约 0.5 天

## ⚠️ B 部分状态更新（2026-08-18）

本方案原 B1（`opendesign.py` CLI 子进程包装）+ B2（`opendesign-design` skill）已被
**并发流的通用 MCP client**（`src/hermes/mcp_client.py`，commit 906c9d3）取代：

- `MCPClient` 提供 JSON-RPC 2.0 + `StdioTransport`/`HTTPTransport` + `hermes mcp list/ping/tools/call` + 审计，**通用**（消费 Open Design 261 插件及任意 MCP server），优于原计划的 od-CLI 子进程包装。
- `mcp.json.example` 内置 Open Design server 模板（`od mcp install hermes --print` 取真实命令）。
- `tests/content_team/test_design_publish_loop.py` 已验证"设计生成 → 多平台发布 → 分析反馈"端到端闭环（模拟 OD MCP，暴露真实工具名 list_skills/create_project/start_run/get_run/cancel_run）。

**因此原 B1/B2（opendesign.py + opendesign-design skill）不再实施**，避免重复；MCP 桥接的
"通用设计能力"目标已由 `mcp_client.py` 达成。本方案仅保留 Part A（Reasonix 三技术点）。

---

## 0. 总览

| 编号 | 事项 | 类型 | 优先级 | 目标 |
|------|------|------|--------|------|
| A1 | cache-aware 上下文维护（prefix 稳定 + stale 裁剪） | 技术借鉴 | P1 | 降 token、提缓存命中、回应 §2.5 风险 #1 |
| A2 | per-turn checkpoint / rewind | 技术借鉴 | P2 | 轨迹 → 可撤销（数据已就位，补 rewind 语义） |
| A3 | cache-stable 会话前缀 | 技术借鉴 | P2 | 稳定前缀排序 + 契约测试 |
| B | OpenDesign MCP 桥接 | 集成 | P1 | content-team 补设计/视频/落地页产出 |

---

## Part A：Reasonix 三技术点

### A1. cache-aware 上下文维护（prefix-cache 稳定）

**目标**：把"注入模型的上下文"拆成**稳定前缀**（跨轮不变 → 命中 prefix-cache）与**易变后缀**（每轮变化），并在 compaction 前裁剪 stale 工具输出。

**现状与缺口**：
- Hermes 是控制平面：模型消息在 Gateway 内组装；Hermes 能控制的是 `_build_spawn_payload` 的 `agent_definition + task + context`，以及 workbench `LlmClient`（直连路径）。
- `agent_definition`（builder.md 全文）天然稳定；但 `context`（上轮 checker 报告）逐轮变化，且**无裁剪**——长 loop 下 context 单调膨胀。
- 无"稳定环境摘要"概念：AGENTS.md 全文 + skill 摘要每次会话重新注入，内容可能随版本漂移，破坏缓存稳定性。

**设计**：新增 `hermes/context.py`，提供三件事：

```
def env_summary(repo_root: Path) -> dict[str, Any]
    # 稳定、可版本化的环境摘要：{conventions(AGENTS.md 摘要), structure(顶层目录),
    #  version(hash)}。缓存到 .cache/context-summary.json，内容 hash 变化才重算。
    # 只进"稳定前缀"，不逐轮重建。

def build_stable_prefix(agent_definition: str, env: dict) -> str
    # 稳定前缀 = agent_definition + env_summary，顺序固定、无时间戳/动态 token。
    # 契约：同一 loop 内跨轮不变（由 A3 契约测试锁定）。

def prune_stale_tool_outputs(messages: list[dict], kept_markers: list[str]) -> list[dict]
    # 裁剪 stale 工具结果：只保留 marker 命中（如"当前文件状态"/最新 edit 后的 read）
    # 与最后 N 条；供 compaction/摘要前调用，防 context 膨胀。
```

**改动文件**：

| 文件 | 改动 |
|------|------|
| `src/hermes/context.py` | 新模块（上述 3 个纯函数 + `env_summary` 缓存） |
| `src/hermes/orchestrator.py` | `_build_spawn_payload` 前置 `build_stable_prefix`：`agent_definition` 按稳定前缀组装，`task/context` 作为易变后缀；无破坏（默认 prefix 与现状等价） |
| `src/hermes/workbench/llm.py` | `chat()` 可选 `stable_prefix: str | None`：存在时置于 messages 前、与 body 分离（直连路径的 prefix 稳定化） |
| `src/hermes/cli_power.py` | 复用 `cmd_context`：打印当前 env_summary + stable_prefix（对齐 `hermes dump-config` 三问之①的精神） |
| `src/hermes/config.py` | 新字段 `HERMES_CONTEXT_SUMMARY_DIR`（默认 `.cache`） |

**测试计划**（`tests/test_context.py`，约 18 用例）：
1. `env_summary` 幂等（内容不变 → hash 不变、不重算）、内容变化重算、缓存落盘/读取
2. `build_stable_prefix` 顺序固定、无时间戳、同一输入恒等
3. `prune_stale_tool_outputs` 保留 marker 命中、裁剪未命中、空列表/无 marker 边界
4. `_build_spawn_payload` 集成：agent_definition 含稳定前缀、task/context 保持易变
5. `llm.chat` stable_prefix 前置且不破坏 messages

**验收**：`pytest tests/` 全绿；`ruff`/`mypy` 零错误；`hermes context` 能打印稳定前缀。

---

### A2. per-turn checkpoint / rewind

**目标**：每轮结束落一个可回滚的 checkpoint；`hermes loop rewind` 恢复到指定轮。

**现状**：`LoopState` 已随 `meta.json` 持久化（每轮覆盖，无历史）；`trajectory.jsonl` 追加（不可回滚）。缺"回到第 N 轮"的能力。

**设计**：在 `loop.py` 增加 checkpoint 管理（复用 `persistence.atomic_write_json`）：

```
def checkpoint_loop(name: str) -> Path
    # record_round 末尾调用：把当前 LoopState 快照写到
    #   .loops/<name>/checkpoints/<round_num>.json（不覆盖，追加式）
    # 用 round_num 命名，幂等（同轮重复调用覆盖同文件）。

def rewind_loop(name: str, target_round: int) -> dict[str, Any]
    # 1. 读取 checkpoints/<target_round>.json 恢复 LoopState（rounds 截断到该轮）
    # 2. 截断 trajectory.jsonl 到该轮对应的 seq（用 LoopRound.trajectory_seq，
    #    ADR-0017 已持久化）
    # 3. 保存 meta.json；状态置 NEEDS_HUMAN（回滚后需人工确认再继续）
    # 4. 目标轮不存在 → ValidationError
```

**改动文件**：

| 文件 | 改动 |
|------|------|
| `src/hermes/loop.py` | `checkpoint_loop` / `rewind_loop` / `_checkpoint_path` / `list_checkpoints`；`record_round` 末尾调 `checkpoint_loop` |
| `src/hermes/trajectory.py` | `truncate(path, upto_seq)`：保留 seq ≤ upto_seq 的行（原子重写） |
| `src/hermes/cli_loop.py` | 新子命令 `loop rewind <name> --to <round>` 与 `loop checkpoints <name>` |
| `src/hermes/runner.py` | `resume_loop` 保持现状（checkpoint 与 fresh resume 归档不冲突） |

**测试计划**（`tests/test_loop.py` 追加 + `tests/test_trajectory.py` 追加，约 15 用例）：
1. `checkpoint_loop` 幂等、追加式、round 命名
2. `rewind_loop` 恢复 rounds 截断、trajectory 截断、状态置 NEEDS_HUMAN、目标轮不存在报错
3. `truncate` 保留 seq 边界、空文件、seq 不存在
4. CLI `loop rewind`/`loop checkpoints` 集成

**验收**：跑一个多轮 loop 后 `hermes loop rewind <name> --to 1`，`hermes loop status` 显示回退到第 1 轮、`hermes loop trajectory --verify` 仍通过。

---

### A3. cache-stable 会话前缀

**目标**：以契约测试锁定"稳定前缀跨轮不变"，文档化 executor/checker 会话分离。

**现状**：builder/checker 已分会话（Gateway spawn），但"前缀稳定"无显式保证；无契约测试防"把易变内容塞进前缀"。

**设计**（轻量，主要是纪律 + 测试）：

```
# context.py
def assert_stable_prefix(prefix_a: str, prefix_b: str) -> None
    # 契约断言：同一 loop 两轮产生的 stable_prefix 必须一致（不含时间戳/
    #  动态 token/checker 报告）。A1 的 build_stable_prefix 被此测试锁定。

# 文档：knowledge/context-engineering.md 补一节"executor/checker 会话分离 + 前缀稳定"
```

**改动文件**：

| 文件 | 改动 |
|------|------|
| `src/hermes/context.py` | `assert_stable_prefix`（纯函数） |
| `knowledge/context-engineering.md` | 补"稳定前缀 + 双角色会话分离"一节（若无此文档则新建） |
| `tests/test_context.py` | 契约测试：模拟两轮构建 stable_prefix，断言恒等 |

**测试**：`test_stable_prefix_across_rounds`（两轮同输入 → 前缀一致）；`test_stable_prefix_rejects_volatile`（前缀含时间戳 → 断言失败）。

---

## Part B：OpenDesign MCP 桥接

### B1. `OpenDesignClient`（本地 `od` CLI 子进程包装）

**目标**：Hermes 侧以 stdlib 子进程调用本地 `od` CLI，产出设计/视频/落地页文件，复用现有 MCP 审计模式。

**设计**：新增 `hermes/opendesign.py`，对齐 `mcp.py` 的 `GitHubMCPClient` 风格：

```
@dataclass OpenDesignResult: ok / stdout / stderr / exit_code / duration

class OpenDesignClient:
    def __init__(self, cli_path: str | None = None):
        # cli_path 默认 "od"（PATH 解析），可经 HERMES_OD_CLI_PATH 覆盖
    def list_projects(self) -> dict        # od project list --json
    def list_files(self, project_id: str) -> dict   # od files list <id> --json
    def generate(self, brief: str, *, kind="prototype", design_system=None,
                 out_dir: Path, timeout=300.0) -> OpenDesignResult
        # od <kind> 或 od create 派发；stdout/stderr 捕获；超时强杀（复用
        #  skill_runner 的进程树终止模式）
    # 审计：每个调用记录到 .state/audit.jsonl（复用 workbench.audit.AuditStore），
    #  无凭据写入（本地 CLI，无 token）
```

**安全约束**：
- `brief` 为普通字符串，不拼接 shell（用 `subprocess` 列表参数，非 `shell=True`）。
- `generate` 的 `out_dir` 必须位于项目根内（复用 server.py `_validate_loop_name` 同款校验思路，防路径逃逸）。
- 本地 `od` 不存在时 `OpenDesignResult.ok=False` + 明确报错，不静默降级。

**改动文件**：

| 文件 | 改动 |
|------|------|
| `src/hermes/opendesign.py` | 新模块（Client + Result + 审计） |
| `src/hermes/config.py` | 新字段 `HERMES_OD_CLI_PATH: str | None`、`HERMES_OD_ENABLED: bool = False` |
| `src/hermes/cli_power.py` 或 `main.py` | 新命令 `hermes opendesign {list-projects|list-files|generate}`（`--json`） |
| `src/hermes/content_team/` | 见 B2 |

**测试计划**（`tests/test_opendesign.py`，约 12 用例，全部 mock `subprocess`）：
1. `list_projects`/`list_files` 解析 `--json` 输出
2. `generate` 成功/非零退出/超时/`od` 缺失（`FileNotFoundError` → ok=False）
3. `out_dir` 路径逃逸被拒
4. 审计记录写入
5. CLI 三子命令集成

### B2. 通用设计能力 skill（opendesign-design）+ 业务消费者

**定位（通用，非小红书专用）**：`opendesign-design` 是**通用设计产出能力**——输入 brief + 产物类型 + 可选设计系统，输出真实文件（HTML/图片/视频/deck/落地页）。小红书 content-team 只是其**一个业务消费者**，其余场景（任何需要设计产物的 task）均可复用。

**设计**（最小接入，不深度耦合）：
- 新增 skill `skills/opendesign-design/`（SKILL.md + `run.py`），复用 `OpenDesignClient`：
  - 输入：`brief`（自然语言）+ `kind`（prototype/deck/image/video/landing-page/document，通用枚举）+ 可选 `design_system`（设计系统名，默认读 `DESIGN.md`）
  - 产出：`--out-dir`（默认项目 `content-creation/artifacts/<slug>/`）下的真实文件
  - 不绑定任何具体业务账号/平台——小红书调酒只是 `design_system` 可传入的一个取值
- `content_team` 的创作流程在"创作"步骤后**可选**调用该 skill（由 `HERMES_OD_ENABLED` 门控，默认关），作为业务消费者示例而非唯一用法。

**改动文件**：

| 文件 | 改动 |
|------|------|
| `skills/opendesign-design/SKILL.md` + `run.py` | 新通用 skill（调用 OpenDesignClient，kind 通用枚举） |
| `src/hermes/content_team/` | 创作链路加可选 OD 调用（`HERMES_OD_ENABLED` 门控，未启用时行为不变） |

**测试**：`tests/test_opendesign.py` 追加 skill 调用（mock client）用例 3 个。

---

## 阶段划分与执行顺序

```
阶段 1（P1）  A1 上下文维护 + B1 OpenDesignClient + B2 接入
阶段 2（P2）  A2 checkpoint/rewind
阶段 3（P2）  A3 稳定前缀契约
```

每阶段完成：`pytest tests/ -q` → `ruff check src/ tests/` → `mypy src/hermes/` → 分阶段 commit + push（`scripts/git-push.sh` 或裸 push + `ls-remote` 校验）。

## 回滚

- A1/A3：`context.py` 新增模块，`_build_spawn_payload` 前缀组装默认等价现状 → 删除调用即回滚。
- A2：checkpoint 为追加式新文件，不影响 `meta.json` 既有结构 → 回退 `checkpoint_loop` 调用即回滚。
- B：`HERMES_OD_ENABLED` 默认关 + skill 可选 → 关闭开关即回滚。

## 不做的事（本方案边界）

- 不以 Reasonix 作为 Hermes sub-agent 后端（无 headless 单任务契约，DSH 更优）。
- 不深度耦合 OpenDesign 为 content-team 创作后端（需业务 ROI 背书）。
- 不引入 OpenDesign 的 Node/pnpm 依赖（仅本地 `od` CLI 子进程）。
- 不做 checkpoint 跨 loop 迁移/merge（rewind 仅限单 loop 内回滚）。

## 关联

- `docs/ecosystem-reasonix-opendesign-assessment.md`（评估）
- `docs/deepseek-harness-analysis.md` §2.5（上下文膨胀风险）、§3.1（治理立场）
- ADR-0017（轨迹，A2 依赖其 `LoopRound.trajectory_seq`）
- `src/hermes/mcp.py`（B1 对齐的审计模式）

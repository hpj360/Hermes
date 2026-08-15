# ADR 0020: Trajectory 视图（后端 API + Dashboard 可视化）

Status: Accepted
Date: 2026-08-15

## Context

ADR-0017 落地了派发轨迹不变量（`trajectory.jsonl` + `assert_reconstructable` +
`hermes loop trajectory --verify` CLI），让 Hermes→Gateway 的派发输入可重建。
但轨迹数据只能通过 CLI 查看，无法在 Dashboard 可视化——排障时需要 SSH 到
机器跑命令，"模型为什么这么干"仍然靠猜。

报告 v3 §3.2 P1 第二项要求："Trajectory 视图：apps/web 会话轨迹页（时间轴 +
request/token/tool + cache），数据源 trajectory.jsonl，复用 tracing"。

调查发现 apps/web 是**内容业务前端**（连 FastAPI 8000 端口，非 workbench
server），不适合放工程视图。正确的位置是 **workbench dashboard**——自包含
单页 HTML（`DASHBOARD_HTML`，原生 JS，无构建步骤），已是 Tasks/Episodes/
Facts/Traces/Skills 五面板的工程 dashboard。

## Decision

分两层落地 Trajectory 视图：

### 1. 后端 HTTP API（3 路由，server.py）

| 路由 | handler | 作用 |
|------|---------|------|
| `GET /loops` | `h_get_loops` | 列出有 trajectory.jsonl 的 loop（扫描 `.loops/` 子目录） |
| `GET /loops/<name>/trajectory` | `h_get_loop_trajectory` | 返回事件列表（复用 `TrajectoryLogger.events()`） |
| `GET /loops/<name>/trajectory/verify` | `h_get_loop_trajectory_verify` | 返回审计结果（复用 `verify_trajectory()`） |

**设计约束**：handler 函数内 `from hermes.loop import loops_dir` / `from
hermes.trajectory import ...`，与 CLI `cmd_loop_trajectory` 共用同一套数据源
读取逻辑，不另维护一套。`NotFoundError` 复用 workbench errors 体系。

### 2. Dashboard 面板（dashboard.py）

在 Skills 面板后新增 "Loop Trajectory" 面板：

- **loop 选择器**（`<select>`）：列出有轨迹的 loop
- **events 表格**：选中 loop 后显示 Seq / Type / Time / Detail 四列；
  dispatch/request 显示 role+file+round，dispatch/result 显示 req_seq+role+
  status+tokens
- **Verify 按钮**：调用 `/trajectory/verify`，显示 PASS/FAIL + 事件计数 +
  seq gaps / unpaired requests / hash mismatches 明细

面板不参与 auto-refresh（轨迹是按需查看的历史数据，非实时状态）。

### 不做的事

- 不在 apps/web 加 trajectory 页面（apps/web 是业务前端，连 FastAPI）。
- 不做 token/cache 时间轴图表（当前表格视图已满足"看见发生了什么"的需求；
  报告 v3 提的"时间轴 + request/token/tool + cache"是更丰富的可视化，留作
  未来增强）。
- 不聚合进 `/dashboard` JSON（轨迹数据量可能大，按需独立 fetch 更合理）。

## Consequences

**正面**

- 排障从"SSH 跑 CLI"变为"浏览器点选"——回答"模型为什么这么干"从猜测变可查。
- 三问之②的可视化补齐：CLI（`hermes loop trajectory --verify`）+ HTTP API
  + Dashboard 三种消费方式。
- Verify 按钮让审计结果一处可见，降低 L3 无人值守的审查摩擦。

**中性**

- Dashboard HTML 增加 ~100 行（trajectory 面板 + JS），仍是无构建单页。

**边界**

- 视图反映 trajectory.jsonl 的**记录态**，不反映 Gateway 内部的实际处理
  （ADR-0017 边界不变）。
- 大量事件时表格无分页（当前 loop 规模小，未来需要时再加）。

## 参考

- 报告 v3 §3.2 P1 第二项
- 关联 ADR：0017（轨迹不变量）、0019（dump-config）

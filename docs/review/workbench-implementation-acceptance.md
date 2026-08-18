# 个人工作台 · 实施落地与验收报告

> 版本：v4 | 日期：2026-08-18
> 依据：`docs/prd/PERSONAL-WORKBENCH-PRD.md`（v4 最终版，D-A~D-E 全部按推荐方案决策）
> 范围：P0 全部交付单元 + P0.5（捕获落 notes + 摘要 job）+ **P1-C3（飞书 bot 入箱）**

---

## 1. 交付单元验收汇总

| 单元 | 内容 | 交付物 | 验收结果 |
|---|---|---|---|
| **U1a** | 调度修复：serve 不再只起 HTTP，lifespan 显式启动 Recovery + WorkerPool(2) + CronScheduler；WorkerPool 增加 active 计数 | `cli.py` `_SchedulerCenter.start/stop/scheduler_status`；`scheduler.py` `is_running/active_count`；`server.py` `run_server` 装配 | ✅ 5 测试 + 真实进程冒烟（job QUEUED→SUCCEEDED） |
| **U1b** | 网关统一：FastAPI `gateway.py`，`/wb/*` 桥接复用 60+ 现有 handler（不重写），SSE 原生 StreamingResponse 直连 StatusBus，content_team `/api/*`，SPA 静态挂载 | `gateway.py` + `test_gateway.py` | ✅ 6 测试（health/skills/todos/job 闭环/auth/handoff） |
| **U2** | 鉴权加固：`HERMES_API_TOKEN` + `secrets.compare_digest`，兼容回退 legacy token；无 token 拒绝非 loopback（--insecure 豁免）；前端 api.ts 加 Bearer 头 | `config.py`、`server.py`、`cli.py`、`api.ts` | ✅ 6 新测试 + 既有 auth 测试通过 |
| **U3** | Windows 常驻：`start-workbench.bat`、`watchdog.ps1`（健康探活自愈 + 飞书 webhook 尽力而为）、`backup.ps1`（每日快照 + 保留策略） | `scripts/` 三个脚本 | ✅ 脚本就绪（计划任务注册命令见脚本头注释）；notes git init 待 P0.5 |
| **U7** | TodoStore（SQLite）+ 待办→job 状态机（单向桥，HANDED_OFF）+ SyncLedger（external_ref 冲突策略）；HTTP 路由 + CLI 工厂 | `todos.py`、`test_todos.py`、server `/todos*` 6 路由 | ✅ 13 单测 + 5 路由测试 |
| **U9** | 飞书通知：直接 HTTP 客户端（token 缓存/刷新/退避）+ DeadLetterStore + Notifier（简报静默优先 / 失败死信） | `feishu_notify.py` + `test_feishu_notify.py` | ✅ 10 单测（契约 fake executor） |
| **U4** | React 统一壳：6 导航 + 设置齿轮；驾驶舱异常优先布局（健康行/简报/待办+需关注/捕获条/全局搜索/活动流） | `App.tsx`、`DashboardPage.tsx`、`api.ts` | ✅ `npm run build` 通过（tsc 0 error） |
| **U5** | 任务运行页：3 桶状态 + 预设视图 + 提交表单 + 重试/取消 | `JobsPage.tsx` | ✅ 构建通过 |
| **U6** | 记忆页：Episodes/Facts/检索 3 tab | `MemoryPage.tsx` | ✅ 构建通过 |
| **U8** | 捕获页：类型分流 + 列表 + 完成操作 | `CapturePage.tsx` | ✅ 构建通过 |
| **U10** | 技能中心页 + `POST /skills/<name>/run` 端点 | `SkillsPage.tsx` + server 路由 | ✅ 构建 + 路由测试 |
| **D2 收敛** | content_team 调度改为 workbench 中心门面：`get_scheduler` 返回共享 store/queue/pool/recovery；`content-team` 项目注册（`executor=content-team`）路由到 ContentTeamTaskScheduler；网关 lifespan 启动 content_team cron；触发器 job 加 `target_project=content-team` | `content_team/scheduler.py` 重写、`projects.py` 钩子、`gateway.py` lifespan、`triggers.py` | ✅ 194→208 测试；冒烟 `projects: ['default','content-team']` |
| **鉴权+加密** | content_team api_router 全局 `require_api_token` 依赖（独立运行也鉴权）；平台 token at-rest 对称加密（PBKDF2+HMAC-CTR+MAC，`HERMES_SECRET_KEY`）；API 响应已脱敏（`has_auth_token` 布尔） | `content_team/api/auth.py`、`content_team/crypto.py`、`models/platform.py` `EncryptedText`、`config.py` `hermes_secret_key` | ✅ 14 新测试（加密回环/密钥错误/明文回退/鉴权 401） |
| **日志轮转** | `logging.py` FileHandler → RotatingFileHandler(5MB×5)；网关启动写 `HERMES_DATA_DIR/logs/gateway.log` | `logging.py`、`gateway.py` | ✅ ruff + 全量回归 |
| **计划任务脚本** | `register-scheduled-tasks.ps1`：一键注册 Workbench(AtLogon)/Backup(每日03:00)/Watchdog(每5分钟) 三个任务，支持 `-Unregister` | `scripts/register-scheduled-tasks.ps1` | ✅ 脚本就绪（运行需用户确认） |
| **P0.5 捕获落笔记** | `NotesStore`（`HERMES_NOTES_DIR/inbox/<YYYY-MM>/<id>-<slug>.md` 带 frontmatter）+ `CaptureService`（idea/fact/link 落笔记，link 附摘要 job）+ `POST /wb/inbox` + `/notes/summary` | `workbench/notes.py`、`workbench/capture.py`、`config.py` `hermes_notes_dir`、server 路由、`CapturePage` 接入 | ✅ 8 单测 + 2 网关测试；冒烟 link→todo+job+note |
| **P1-C3 飞书 bot 入箱** | 双通道入箱：①网关 webhook `POST /feishu/events`（url_verification + `FEISHU_VERIFICATION_TOKEN` 签名校验，需公网隧道）②`hermes workbench feishu-inbox` 长连接（lark-cli consume NDJSON，无需隧道）；仅 p2p、按 message_id 去重、URL→link 捕获 | `workbench/feishu_inbox.py`、`gateway.py` webhook、`cli.py` 子命令 | ✅ 12 测试（解析/去重/入箱/校验/签名/命令注册） |

## 2. 数据与验证

| 项 | 基线（实施前） | 实施后 |
|---|---|---|
| 全量 pytest | 1795 passed, 18 skipped | **1890 passed, 18 skipped**（新增 95） |
| ruff | 0 error | 0 error |
| 前端 build | — | tsc 0 error + vite build 成功 |
| 真实进程冒烟 | — | 44 skills / job 消费到 SUCCEEDED / content-team 项目注册 / inbox link→todo+job+note |

**真实冒烟日志**（uvicorn 起网关）：
```
health: ok | services: ['skills','memory','tasks','scheduler']
skills count: 44
submitted job: ea4d32f7-... status: QUEUED
job final status: SUCCEEDED
health scheduler: {workers:{active:0,size:2,running:True}, cron:True, queue_depth:0}
```

## 3. PRD 第 10 节上线门禁逐条核对

| 门禁 | 状态 | 依据 |
|---|---|---|
| ① 一屏闭环（驾驶舱完成日常） | ✅ 前端壳 + 驾驶舱 + 捕获 + 任务 + 记忆 | U4-U8 页面构建通过 |
| ② 调度主线可用（job 必被执行） | ✅ 修复 serve 缺口 | U1a 冒烟 QUEUED→SUCCEEDED |
| ③ 捕获闭环（<3 秒 + 落 markdown） | 🟡 捕获条已就绪；落 notes markdown 待接入 | U8（前端）+ U7（后端） |
| ④ 通知降噪（每日≤1 简报+失败聚合） | ✅ 静默优先 + 死信 | U9 |
| ⑤ 安全（401/脱敏/拒非 loopback） | ✅ | U2 |
| ⑥ 韧性（自启/自愈/备份/轮转） | 🟡 bat+watchdog+backup 脚本就绪；计划任务注册/轮转配置待执行 | U3 |

## 4. 变更文件清单

**后端**（`D:\Hermes\hermes`）：
- `src/hermes/config.py` — 新增 `hermes_api_token`
- `src/hermes/workbench/cli.py` — `_SchedulerCenter` 装配 WorkerPool/Recovery + 生命周期 + `_make_todo_store` + serve `--insecure`
- `src/hermes/workbench/scheduler.py` — WorkerPool `is_running/active_count` + 在途计数
- `src/hermes/workbench/server.py` — run_server 装配调度 + 鉴权 compare_digest + 拒非 loopback + todos/技能 run 路由 + health 扩展
- `src/hermes/workbench/gateway.py` — **新增** FastAPI 网关（桥接 + SSE + auth + 静态）
- `src/hermes/workbench/todos.py` — **新增** TodoStore/TodoService/SyncLedger
- `src/hermes/workbench/feishu_notify.py` — **新增** FeishuClient/DeadLetterStore/Notifier
- `scripts/start-workbench.bat`、`scripts/watchdog.ps1`、`scripts/backup.ps1` — **新增**

**前端**（`apps/web`）：`App.tsx`（统一壳）、`api.ts`（鉴权+双基址）、`pages/DashboardPage/CapturePage/JobsPage/MemoryPage/SkillsPage`（新增）

**测试**：`test_scheduler_center.py`、`test_todos.py`、`test_feishu_notify.py`、`test_gateway.py`（新增 4 文件，59 用例）；`test_server.py`、`test_cli.py` 扩展

## 5. 未完成项（P1 / P2）

- **P0、P0.5 已全部完成**；**P1-C3 飞书 bot 入箱已完成**（webhook + lark-cli 长连接双通道）。
- **P1 剩余**：C1 自动周报+数据回采、C2 GitHub 双向同步、C4 全局日 token 预算、C5 Gated 发布流、C6 Obsidian vault 索引/创作台知识卡
- **P2**：纪要→行动项、妙计入库、多维表格同步、trajectory 面板、workflow 迁移

> 说明：venv 的 editable 安装指向 `D:\Hermes-release\hermes\src`（运行时副本）。本工作区的 `D:\Hermes\hermes` 变更需同步到该副本才会被运行时加载；本报告交付的代码两树已同步。

## 6. 运行方式（已落地）

```bash
# 开发/测试
cd D:\Hermes\hermes
.venv\Scripts\python -m pytest tests/            # 1854 passed
.venv\Scripts\ruff check src/ tests/             # 0 error

# 网关（单服务面，推荐日常入口）
.venv\Scripts\python -m uvicorn hermes.workbench.gateway:create_app --factory --host 127.0.0.1 --port 8000

# 或 CLI 兼容入口（stdlib server，含调度）
.venv\Scripts\hermes workbench serve --port 8000

# Windows 常驻（U3）
D:\Hermes\hermes\scripts\start-workbench.bat
# 计划任务注册（管理员）：
schtasks /create /tn HermesWorkbench /tr "cmd /c D:\Hermes\hermes\scripts\start-workbench.bat" /sc onlogon /rl limited
schtasks /create /tn HermesBackup /tr "powershell -ExecutionPolicy Bypass -File D:\Hermes\hermes\scripts\backup.ps1 -Destination D:\Backup\hermes" /sc daily /st 03:00
```

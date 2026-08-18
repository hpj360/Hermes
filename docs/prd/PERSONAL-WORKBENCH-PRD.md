# 个人 AI 工作台（Personal Workbench）产品需求文档 PRD

> 版本：v4（最终版）| 状态：待确认 | 生成日期：2026-08-18
> 评审过程：两轮、六个对抗性角色（产品 / 技术 / UX / 运维 / 综合评审 / 实施可行性）

---

## 0. 文档信息

| 项 | 值 |
|---|---|
| 产品名称 | Hermes 个人 AI 工作台（Personal Workbench） |
| 产品定位 | 通用个人 AI 管理平台：任务调度、记忆、技能为主线；内容管线、酒类知识库为领域模块 |
| 目标用户 | 本人（技术型酒类内容创作者）+ 1-5 人小团队（协作仅经飞书通道，无账号体系） |
| 运行形态 | 本地 Windows 常驻服务 + 浏览器 Web 驾驶舱 + 飞书单向通知 |
| 版本历史 | v1 初版 → 决策确认（通用管理为主 / Web+飞书 / Windows 常驻 / KB 底座 / 简报推送）→ v2 定稿候选 → v3 修订 → **v4 最终版** |

---

## 1. 背景与问题定义

### 1.1 资产盘点（仓库审视结论）

| 资产 | 定位 | 关键能力 | 成熟度 |
|---|---|---|---|
| `hermes/` v0.6.0 | Agent 引擎 + Workbench 运行时 | 调度中心（jobs/triggers/DAG/cron/recovery）、三层记忆 + Mem0 + RRF 检索、24+ skills、Loop 多 Agent、65+ HTTP 端点、content_team FastAPI 子包 + React 前端 | 高（~1700 测试） |
| `Hermes-workbench/` | 发行仓（v0.3） | workflow / projects / SSE / audit / prototype Dashboard | 中（与 v0.6 割裂） |
| `hermes-kb/` | 酒类知识库 | FastAPI + React + RAG（独立服务 + 独立 6k 行 SPA） | 高 |
| `content-team/` | 自媒体运营仓 | 选题→创作→发布→数据管线 | 中（与主仓重复建设，冻结为资产源） |
| 根目录 | Obsidian vault + 飞书 Base 导出 | 个人知识层 | 低 |
| 环境 | 飞书全套 lark-cli | 外部协作通道 | 未接入产品 |

### 1.2 核心问题

1. **有引擎无驾驶舱**：调度、记忆、技能全有 CLI/API，但日常操作在终端；三套 UI（apps/web、dashboard.py、prototype）互不相通。
2. **内容管线缺闭环**：选题→发布有基础，但数据回采→复盘→知识回流断链。
3. **知识不流动**：hermes-kb RAG、content-team、Obsidian、飞书四座孤岛，无输入/捕获通道，记忆层空转。
4. **外部能力闲置**：飞书全套能力未进入产品。

### 1.3 产品目标与北极星指标

- **目标**：把「今天要做什么、做到哪了、记得什么」装进一屏；AI 执行与提醒，人只做关键决策（Gated 半自动原则）。
- **北极星**：日常任务闭环率（提交→查看→执行→确认）+ 打开 CLI 的次数降为 0。

---

## 2. 目标与非目标

### 2.1 目标
1. 一屏完成日常：看简报、管任务、记记忆、跑技能
2. 飞书每天最多打扰 1 次（简报），失败实时聚合提醒
3. Windows 开机自启，崩溃自愈，数据每日备份
4. 捕获（记灵感/存链接）摩擦 < 3 秒，低于 Obsidian

### 2.2 非目标（明确不做）
- 多用户账号体系与 RBAC（协作仅飞书确认卡/只读链接）
- 移动端 App（飞书卡片作为移动皮肤）
- 复杂 BI 报表（自动周报已覆盖）
- 社交化
- hermes-kb 6k 行 SPA 的合并重写（P0 只做检索入口/代理）

---

## 3. 用户场景（用户旅程）

| 时刻 | 场景 | 工作台动作 |
|---|---|---|
| 09:00 | 晨会 | 飞书 1 条简报：完成 X / 失败 Y / 新记忆 Z / 待决策 N（无活动不发） |
| 09:30 | 捕获 | 顶栏捕获条 1 秒记灵感/存链接（同步落 vault markdown，异步摘要） |
| 10:00 | 选题 | 趋势源 + 知识库检索生成候选选题评分（P1） |
| 14:00 | 创作 | Loop 生成草稿 + 知识卡联动（P1），Gated 确认 |
| 16:00 | 发布 | 半自动检查单 → 人工发布 → 状态回填（P0 检查单 / P1 全流程） |
| 20:00 | 复盘 | 数据回采（半自动人工导出优先）→ 自动周报 → 知识回流（P1） |

---

## 4. 功能需求（模块详设）

### 4.1 信息架构（6 一级导航 + 齿轮）

```
① 驾驶舱（默认首页，只读投影，异常优先）
│   ├─ 顶栏：系统健康点 + 运行中 job 数 + 全局搜索框 + 捕获条
│   ├─ 今日简报（主区 60%）：昨夜产出摘要 / 待决策事项 / 新记忆 N 条
│   ├─ 待我处理（右 40%）：待办 ≤5（可勾选，可「派给 agent」转 job）+ 需关注 jobs ≤5
│   └─ 最近活动流（底部，SSE 增量）
② 捕获 / Inbox（P0 核心，输入唯一入口）
│   ├─ 全局捕获条：类型分流（灵感→选题池 / 摘记链接→知识库待索引 / 事实→facts / 待办→TodoStore）
│   ├─ 带 URL 捕获：同步落 markdown 到 D:\Hermes\notes + 异步摘要 job（best-effort，失败进需关注可重试）
│   └─ 未整理列表 + 一键分发（P1 起支持飞书 bot 入箱）
③ 任务运行（Jobs）
│   ├─ 预设视图 chips：需关注(默认) / 进行中 / 已完成 / 全部（带计数）
│   ├─ 高级筛选（折叠）：8 精确状态 + 时间范围 + skill 类型
│   ├─ 状态 3 桶：进行中(蓝, P/Q/R) / 成功(绿) / 需关注(红, F/C/T/A)，8 态仅在详情页
│   ├─ 详情三栏：列表 | 详情(attempts 时间线+日志+重试/取消) | 活动流
│   ├─ 提交表单（含「完成后提醒我」开关，默认关）
│   ├─ Triggers cron 编辑器（次级 tab，配置型低频）
│   └─ GitHub Issues 只读卡片（P0）/ 双向同步（P1）
④ 记忆
│   ├─ 检索（默认 tab，RRF；语义/FTS/子串 3 路默认，跨库聚合可选）
│   ├─ Episodes 时间线 / Facts 表格 / 画像表单
⑤ 内容管线（领域模块）
│   ├─ 选题 / 创作 / 发布 3 tab（现有 apps/web 3 页整合）
│   └─ 数据看板 + 半自动发布检查单 + 待发布队列（P0 壳，P1 全量）
⑥ 知识库（领域模块）
│   ├─ 检索入口（网关 /kb/ 代理 hermes-kb）+ 结果页（带来源）
│   └─ 来源管理（索引状态 / 来自捕获的文档）
⚙ 设置（齿轮，不进主导航）
│   ├─ 技能中心（降频：list/详情/运行/依赖预检）
│   ├─ 集成：GitHub / 飞书 / 平台账号（token 加密+脱敏）
│   ├─ 通知档位：全部 / 仅异常 / 仅简报 / 关闭（默认「仅异常 + 简报」）
│   └─ 外观（深色默认）与快捷键（Ctrl+K / / / n / j/k / Esc）
```

**IA 硬规则**：
- 驾驶舱是任务中心的**只读过滤视图**（同一个组件不同 filter），杜绝第三处状态真相。
- 「待办（人要做的）」与「运行任务（agent 执行的 job）」是两类实体，命名与存储分离，靠「派给 agent」按钮显式桥接。
- 空状态即教学：空 jobs 给示例模板、空 facts 给示例 placeholder、首启 3 步检查单（记第一条事实 / 跑一个示例 job / 连飞书），可永久跳过。

### 4.2 通知策略（三级降噪）

| 事件 | 策略 |
|---|---|
| job SUCCEEDED | 静默（除非提交时勾选「完成后提醒我」） |
| job FAILED/TIMEOUT | 5 分钟窗口聚合，同 job 家族每小时 ≤1 条，带 job_id 深链 + 首行失败原因 |
| 每日简报 | 每天最多 1 条飞书卡片；**有活动才发**（静默优先）；内容=完成 X/失败 Y/新记忆 Z/待决策 N；行业摘要按需生成 |
| 反馈 | 卡片带「有用 / 太吵」按钮，作为通知档位调参信号 |
| 通道 | 飞书为尽力而为通道：失败不阻塞主流程，落死信统计（SQLite），下一轮简报合并重发（仅统计，不重复轰炸） |

### 4.3 待办→job 状态机（新增数据实体）

- **TodoStore**（SQLite 表，HERMES_DATA_DIR 下）：字段 id / title / type / status / due / source / external_ref / job_id / created_at / updated_at。
- 状态机：`pending` → 到期自动或手动 `handed_off`（生成 job）→ job 终态**不回写**待办状态（单向桥，单一事实源）→ 待办手动 `done`/`cancelled`。
- GitHub Issues 同步账本：`external_ref` 记录 issue# ↔ 待办/job 映射；冲突策略：本地已 `done` 的对应 issue 只读，pull 不回改 closed（P0 建立，P1 启用写方向）。

---

## 5. 技术架构（最终版）

### 5.1 进程拓扑（三进程）

```
┌──────────────────────────────────────────────────────────────┐
│ 网关进程（唯一常驻主体，uvicorn 单进程 127.0.0.1:8000）         │
│  ├─ FastAPI lifespan：RecoveryManager.recover() →              │
│  │   WorkerPool(2).start() → CronScheduler.start()            │
│  │   （修复 v0.6 serve 不执行 job 的缺口；收敛为唯一调度中心）    │
│  ├─ /wb/*  workbench 路由并入 FastAPI router（删除 ThreadingHTTPServer 透传）│
│  ├─ /api/* content_team router（业务）                          │
│  ├─ /api/dashboard/* 聚合端点（进程内读单例组装简报/待办/健康）    │
│  ├─ /kb/*  反向代理 hermes-kb（含静态 SPA）                      │
│  ├─ SSE    StreamingResponse 直连 StatusBus（不经 HTTP 代理）   │
│  └─ /      挂载 React SPA dist                                  │
├──────────────────────────────────────────────────────────────┤
│ hermes-kb sidecar（独立进程 127.0.0.1:8765）                    │
│  ├─ 自带 SQLite + JWT + RAG + 6k 行 SPA（不内嵌，避免 /api 前缀冲突）│
│  └─ 新增轻量 GET /api/search（供网关检索，服务端 JWT 注入）        │
├──────────────────────────────────────────────────────────────┤
│ 监督层：start-workbench.bat（sidecar 健康轮询拉起三进程）          │
│  └─ Windows 计划任务开机自启 + watchdog 循环（探活→重启→飞书告警→死信）│
└──────────────────────────────────────────────────────────────┘
```

### 5.2 关键架构决策（经评审裁决）

| # | 决策 | 理由 |
|---|---|---|
| D1 | workbench 65+ 端点**机械迁移**为 FastAPI router（挂 /wb/*），删除内嵌 ThreadingHTTPServer | 单一服务面/单一鉴权/单一 CORS；双 HTTP+双鉴权是重复建设 |
| D2 | 调度所有权**收敛为单一中心**：以 workbench `_SchedulerCenter` 为准；content_team 的 scheduler/triggers 改为代理接入，冻结其旧测试并适配 | 双 JobStore/双 WorkerPool 会双写 job、抢任务 |
| D3 | 鉴权统一 `hermes_api_token` + `secrets.compare_digest`；无 token 默认拒绝非 loopback 监听（`--insecure` 显式豁免）；旧 `OPENCLAW_GATEWAY_TOKEN` 仅一次性迁移 | v0.6 现用裸 `==`，content_team 无鉴权，CORS `*` |
| D4 | 数据绝对路径锚定：`HERMES_DATA_DIR=D:/Hermes/data`（content_team DB、.state、日志均锚定） | 现用相对路径，CWD 漂移即 DB 分裂 |
| D5 | 统一日志 `D:\Hermes\logs\<svc>.log` + RotatingFileHandler(5MB×5)；JSONL 定时归档 | 现无轮转，常驻会撑爆磁盘 |
| D6 | 平台账号 token DB 对称加密 + API 脱敏返回 | 现明文 Text 列且 `/api/accounts` 明文返回 |
| D7 | hermes-kb 保持独立 sidecar，不内嵌 | 自带 SQLite 单例 + JWT + 前缀冲突 |
| D8 | 捕获同步落盘必成（markdown+元数据），摘要异步 best-effort，失败进「需关注」可重试 | 摘要失败不丢 URL 条目 |
| D9 | vault 与仓库分离：capture 限 `D:\Hermes\notes` 子目录，vault git 仅跟踪该子目录，KB 索引排除 `.git/**` 与代码 | 根目录即 vault 且含三个 git 仓库，避免互相污染 |

### 5.3 数据模型（新增/变更）

- **TodoStore**（SQLite）：见 4.3。
- **Sync ledger**（SQLite）：`external_ref` 映射（issue# ↔ 待办/job）+ 冲突策略。
- **Notify dead-letter**（SQLite）：飞书发送失败记录 + 退避重试状态。
- **Daily token budget 计数**：记录每次 LLM 调用 token 用量（P0 采集，P1 前置熔断）。
- 既有：content_team SQLite、workbench `.state` JSON、hermes-kb RAG 库、`D:\Hermes\notes` markdown。

---

## 6. 运维、安全与成本

### 6.1 P0 必做运维安全清单（评审裁决的最小集合）
1. **绝对路径锚定**（D4）——消除 DB 分裂。
2. **每日自动备份 + 每季度恢复演练**：`backup.ps1`（计划任务）先 `PRAGMA wal_checkpoint(TRUNCATE)`/`VACUUM INTO` 再复制 `*.db` + `.state/` + `hermes-kb` + `notes/` 到外部盘；`D:\Hermes\notes` git init + 每日 commit；恢复演练降为季度（不过度设计）。
3. **强制 Bearer 鉴权**（D3）+ CORS 收紧 + 平台 token 不返回明文（D6）。
4. **全局 LLM 日预算**：P0 采集用量，P1 前置熔断（超限降级本地 Ollama/跳过）。
5. **日志轮转 + 磁盘水位告警**（D5 + 每日磁盘 <10GB 告警）。

### 6.2 密钥与配置
- `.env` 收敛为单一数据目录 + `HERMES_INHERIT_ENV_PATHS` 指针；`HERMES_MAIN_REPO_PATH` 在 Windows 显式修正；NTFS ACL 仅当前用户可读。

### 6.3 飞书通知实现
- 直接 HTTP 优先：`FEISHU_APP_ID/SECRET` → tenant_access_token（缓存 + 刷新），429/5xx 指数退避，`httpx` 客户端接口化 + 契约测试；lark-cli 仅调试/兜底；失败落死信。
- 飞书 bot 事件订阅（私聊/转发入箱）→ **P1**（需长连接 + 重连 + 幂等，P0 不建）。

---

## 7. 多轮评审结论与决策记录

### 7.1 Round 1（产品 / 技术 / UX / 运维 四角色）

| 关键发现 | 采纳情况 |
|---|---|
| 缺「捕获/收件箱」，简报与记忆空转 | ✅ 新增 IA 模块 ②，P0 核心 |
| 任务中心与 GitHub Issues 习惯脱节 | ✅ P0 只读卡片，P1 双向同步 |
| 全局搜索遗漏（后端 RRF 已就绪） | ✅ 驾驶舱顶栏全局搜索框 |
| 通知疲劳风险 | ✅ 三级降噪（4.2） |
| 空状态教学性 | ✅ 4.1 IA 硬规则 |
| **serve 不执行 job（调度主线断）** | ✅ D1/D2 lifespan 显式启动调度组件 |
| /kb/search 端点不存在 | ✅ D7 新增 /api/search + JWT |
| 鉴权字段缺失 / 明文比较 / 前端无头 | ✅ D3 |
| 双调度栈 + CWD 相对路径 | ✅ D2/D4 |
| SSE 经 HTTP 代理的坑 | ✅ 直连 StatusBus |
| 无备份 / 日志无轮转 / 无预算护栏 / 明文 token | ✅ 第 6 章 |

### 7.2 Round 2（综合评审 / 实施可行性）

| 裁决 | 采纳情况 |
|---|---|
| 需大改：P0 范围超载（3-4 周不可行） | ✅ P0 拆 P0a/P0b，承诺 8-9 周（单人） |
| 待办存储未定义 | ✅ TodoStore + 状态机（4.3） |
| 双 HTTP 服务器 + 双鉴权重复建设 | ✅ D1 并入 FastAPI |
| 捕获摘要失败/成本兜底 | ✅ D8 + P0 默认本地模型/降级 |
| vault 与仓库互相污染 | ✅ D9 |
| 空状态教学性回归遗漏 | ✅ 4.1 恢复 |
| 过度设计项（月度演练/五路 RRF/死信重发/行业摘要） | ✅ 降级：季度演练、默认 3 路、死信仅统计、摘要按需 |
| 三份 config.py 副本漂移 | ✅ 以单一 venv 安装点为准，删除 vendored 副本 |
| content-team 是旧整包副本 | ✅ P0 严禁在其中开发 |

---

## 8. 交付计划

### 8.1 交付单元（P0，估算依据：单人，实测 ~1700 测试回归约束）

| # | 单元 | 人日 | 前置 | 验收标准 |
|---|---|---|---|---|
| U1a | 调度修复：lifespan 启动 Recovery+WorkerPool+CronScheduler；双调度收敛为单一中心 | 3 | — | `POST /wb/jobs` 被消费到终态；SSE 收到状态流 |
| U1b | workbench 路由机械迁移为 FastAPI router（/wb/*），删除 ThreadingHTTPServer；契约冻结+逐路由 diff | 5 | U1a | 全路由 smoke；~1700 测试回归通过 |
| U2 | 鉴权（hermes_api_token+compare_digest+content_team 依赖）+ 路径锚定 + 日志轮转 | 2 | U1b | 无/错 token 均 401；重启落盘 D:/Hermes/data |
| U3 | Windows 常驻（bat+计划任务+watchdog）+ backup.ps1 + notes git | 2 | U2 | 进程死亡 30s 自愈；备份产物无 WAL 残留 |
| U4 | React 统一壳 + 驾驶舱（异常优先/SSE 断线降级/顶栏搜索+捕获条） | 5-6 | U1b,U2 | 后端不可达仍渲染骨架；SSE 自动重连 |
| U5 | 任务运行页（3 桶/预设视图/详情/提交/重试取消/Triggers 编辑） | 4 | U4 | job 经 SSE 实时迁移 3 桶；cron 到点产出 |
| U6 | 记忆页（检索 3 路/Episodes/Facts/画像） | 2-3 | U4 | 4 类检索有结果且一致 |
| U7 | TodoStore + 待办→job 状态机 + sync ledger | 2-3 | U1b,U2 | 到期自动入队且联动；schema 迁移测试 |
| U8 | 捕获 Inbox（捕获条/类型分流/落 markdown/摘要 job best-effort） | 4 | U4,U7 | URL 捕获出 md+摘要 job 可见；失败进需关注可重试 |
| U9 | 飞书通知管线（token 管理/简报静默优先/失败聚合/死信） | 3 | U1b,U7 | 无活动零发送；失败进死信+退避 |
| U10 | 壳+最小可用（技能中心/内容 3 tab/发布检查单/KB 入口） | 3 | U4-U6 | 各 tab 可达；无 KB URL 时降级不崩 |

**合计 ≈ 35 人日；净 7 周，含缓冲 8-9 周（单人）**。关键路径：U1a→U1b→U2→U4→U8（约 4 周到可演示闭环）。

### 8.2 裁剪建议（若需压缩）
- P0 必做：U1-U9（6.5 周净 / 8 周含缓冲）。
- 可延后 P0.5：U10 全部 + 飞书死信统计降日志 + 驾驶舱简报先本地渲染。
- 已移出 P0：飞书 bot 入箱、GitHub 双向写、数据回采、自动周报、Gated 发布流、知识卡联动、妙记、多维表格同步、trajectory 面板、workflow 迁移（P1/P2）。

### 8.3 路线图

| 阶段 | 范围 | 交付标准 |
|---|---|---|
| P0（8-9 周） | U1a-U10（8.1） | 一屏日常闭环：简报/待办/任务/记忆/捕获/通知；开机自启+每日备份 |
| P0.5 | U10 延后项 + 驾驶舱简报本地化 | 内容管线最小可用 |
| P1 | GitHub 双向同步、飞书 bot 入箱、Obsidian vault 索引、数据回采（半自动人工导出优先）、自动周报、Gated 发布流（飞书确认卡）、创作台知识卡、全局日 token 预算 | 选题→发布全流程可在驾驶舱完成，人只确认节点 |
| P2 | 纪要→行动项→任务中心、妙记入知识库、多维表格同步选题池、trajectory 面板、workflow 引擎迁移（随发行仓收敛） | 知识回流闭环 |

### 8.4 实施纪律
- 每单元结束全量 `pytest` + `ruff`；U1b 是回归重灾区，单独过 ~1700 测试。
- P0 严禁在 `content-team/`（旧整包副本）开发。
- 统一 venv 安装点为 hermes 主仓，删除三处 config.py 副本漂移。

---

## 9. 风险登记册

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R1 | v0.6 路由迁移回归（65+ 端点，~1700 测试） | 高 | 契约冻结 + 逐路由 golden diff；错误映射统一 exception handler |
| R2 | 双调度栈冲突（workbench vs content_team scheduler） | 高 | D2 单一调度中心，U1a 硬验收 |
| R3 | SSE 直连（阻塞事件循环/订阅泄漏/断线） | 中 | 并发测试 + unsubscribe 泄漏单测 + 心跳 + 队列读放线程（async_bridge 现成） |
| R4 | 飞书外部依赖（无既有客户端） | 中 | 半天 spike 验证 token 换取；接口化 + fake 契约测试；失败绝不阻塞主流程 |
| R5 | 前端改造量（3 页→8+ 视图） | 中 | 壳先行（U4 独立）；复用 wouter+tailwind；共享 api client + 统一 Authorization |
| R6 | 平台回采合规（抖音/小红书无官方接口） | 中 | 半自动人工导出优先，自动抓取 gated 默认关闭 |
| R7 | LLM 成本失控 | 中 | P0 用量采集，P1 前置熔断，超限降级 Ollama |
| R8 | 单机磁盘故障全丢 | 高 | backup.ps1 每日 + 季度恢复演练 + notes git |

---

## 10. 验收标准（上线门禁）

1. **一屏闭环**：驾驶舱完成看简报 / 勾待办 / 提交 job / 记记忆 / 跑技能，无需 CLI。
2. **调度主线可用**：提交的 job 必被执行到终态；失败可见可重试。
3. **捕获闭环**：从捕获条记一条灵感 < 3 秒；URL 捕获同步落 notes markdown，摘要失败可见可重试。
4. **通知降噪**：飞书每天 ≤1 条简报 + 失败聚合提醒；成功静默；通知档位可调。
5. **安全**：无/错 token 对 /api/*、/wb/* 均 401；平台 token 不出网；无 token 拒绝非 loopback。
6. **韧性**：开机自启；进程死亡 30s 内自愈；数据每日备份；日志有轮转。

---

## 11. 待确认事项

> 按项目约束，每项决策均补充「背景 → 影响 → 建议」。

### D-A. P0 周期与拆分

- **背景**：实施可行性评审实测代码后确认，P0 全量约 35 人日（单人 7 周净、含缓冲 8-9 周），远超 v1 承诺的 2-3 周；若按原承诺交付必然延期或带病上线。
- **影响**：接受 8-9 周 → 节奏可控、每单元有可测验收；压缩 → 需将 U10（技能中心/内容整合/发布检查单/KB 入口）及简报降级延至 P0.5，第一版只交付「地基 + 驾驶舱 + 捕获 + 任务 + 记忆 + 通知」。
- **建议**：推荐接受 8-9 周并拆 P0a（U1-U3 地基）/ P0b（U4-U9 核心闭环），理由：P0a 落地即解锁调度主线与安全底线，P0b 交付可演示闭环；延后项收益低、不阻塞主价值。

### D-B. 调度所有权收敛

- **背景**：Round 2 新发现 workbench `_SchedulerCenter`（.state）与 content_team 自带 scheduler（data/content_team_jobs）各持一套 JobStore/WorkerPool，统一网关若并存会双写 job、抢任务。
- **影响**：以 workbench 为唯一调度中心、content_team 调度改代理接入 → 需冻结 content_team 旧调度测试并适配（约 1-2 人日）；不收敛 → 两个任务列表分裂、发布/回采定时任务与 workbench jobs 互相干扰，聚合视图失真。
- **建议**：推荐收敛为单一中心。理由：这是 P0 最大架构隐患（R2 高风险项），U1a 硬验收已覆盖，越晚处理回归成本越高。

### D-C. 单一服务面（删内嵌 ThreadingHTTPServer）

- **背景**：技术评审裁定 v0.6 的 stdlib HTTP server 与 FastAPI 网关并存会造成双端口、双 CORS、双鉴权、双路由表，且 65+ 端点已全部经 cli.py 服务工厂薄适配、迁移成本低。
- **影响**：workbench 路由并入 FastAPI（挂 /wb/*）、删除 ThreadingHTTPServer → 迁移含机械改造 + 契约冻结 + 逐路由回归（约 5 人日，U1b）；保留 → 鉴权加固收益被第二入口抵消，运维双面。
- **建议**：推荐并入 FastAPI。理由：一次性收敛换取单一鉴权/CORS/路由表，与 D-B 共同支撑"单一运行时底座"决策。

### D-D. vault 与仓库分离策略

- **背景**：D:\Hermes 根目录本身是 Obsidian vault 且内含三个 git 仓库，若对整根目录 git init 会纳管代码产生嵌套仓库；KB 索引若不排除会把源码当知识索引进库。
- **影响**：capture 落 `D:\Hermes\notes` 子目录、仅对该子目录 git init、KB 索引排除 `.git/**` 与代码 → 笔记与代码互不污染，备份/索引边界清晰；不分离 → vault 每日 commit 噪音大、KB 索引混入代码、备份范围失控。
- **建议**：推荐采纳子目录隔离。理由：成本近乎零，消除 Obsidian/代码/备份三方污染，符合"通用个人管理"下知识层的干净边界。

### D-E. 通知默认档位

- **背景**：UX 评审确定三级降噪原则（成功静默/失败聚合/每日 ≤1 简报），但默认档位未拍板——档位过松会消息疲劳，过紧会漏掉重要失败。
- **影响**：默认「仅异常 + 简报」→ 每天最多 1 条简报 + 失败实时聚合，噪音最小且不遗漏异常；默认「全部」→ 完成通知轰炸致用户静音后失败也一起被忽略。
- **建议**：推荐默认「仅异常 + 简报」，并在设置页提供「全部 / 仅异常 / 仅简报 / 关闭」四档可调，卡片附「有用/太吵」反馈键做动态调参。

---

**确认方式**：以上 5 项互相独立，可分别拍板；回复每项编号 + 确认/修改即可。确认后按 U1a（调度修复）开始实施。

*PRD 附：两轮评审原始结论见 `docs/review/`（评审纪要归档）。*

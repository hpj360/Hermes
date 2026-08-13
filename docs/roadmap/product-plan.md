# Hermes 产品规划与架构设计（v1.0）

> 状态：已评审（架构师 / PM / SRE 三方反方评审）+ 用户三项决策拍板
> 日期：2026-08-14
> 前置文档：`docs/roadmap/iter-v0.6-to-v1.0.md`（技术迭代 Spec，P0-P3 已交付）
> 本文档：**产品与架构层规划**，作为后续启动的蓝图

---

## 0. 决策记录（本次已拍板）

| # | 决策 | 结论 |
|---|---|---|
| D1 | 定位叙事 | **一个产品（个人 AI 工作台）+ 第一个垂直场景（content-team）**，不搞"两个平级产品" |
| D2 | PM Framework 归属 | 24 个 PM skill **上收到 hermes 主仓**（单一资产信源），workbench 只留发行薄壳 |
| D3 | 执行节奏 | **先完整规划与设计，后续再启动**（本文档即规划产物） |
| D4 | 真实 API | 愿意接入微信/小红书等真实平台凭证；**数据回采真实性优先，发布半自动** |
| D5 | 四仓收敛 | 保持独立 git + 独立迭代，但**解除 fork 关系、改为单向依赖** |

---

## 1. 产品定位

### 1.1 一句话定位
> **Hermes = 一个"半自动 + 对抗校验"的个人 AI 工作台**，content-team 是它上面的第一个垂直场景（自媒体运营）。

### 1.2 目标用户
- **主**：独立开发者、AI 重度用户（用 Hermes 编排自己的 AI 工作流）
- **场景**：1-5 人自媒体小团队（用 content-team 做选题→创作→发布→数据）

### 1.3 北极星指标
> **一个用户从零安装到「半自动发布第一篇真实内容并看到真实数据」的时间**（目标 < 30 分钟）。

### 1.4 差异化护城河（押注方向）
**「半自动 + 对抗校验」**——人机协作的可控性：
- 别的 agent 一口气做到底；Hermes 在关键节点停下来等你确认（`--gated`）
- builder/checker 对抗循环（builder 生成、checker 独立否决）
- 三层记忆 + GEPA 自进化（让"AI 越用越懂你"可感知）

这是 n8n/Dify（工作流）、Letta（记忆）、Cursor（IDE agent）都没主打的点，且已实现 80%。

---

## 2. 现状诊断（六仓）

### 2.1 真实仓拓扑（评审实盘结论）

| 仓 | 本质 | 关键事实 |
|---|---|---|
| `hermes` | 引擎主仓（唯一可信源） | 包名 `hermes` 0.6.0，44 skill，含一份 content_team（比 content-team 仓**更新**） |
| `content-team` | 引擎 **fork** + 业务 | 包名也是 `hermes` 0.6.0，完整 copy 引擎 + content_team 业务，21 skill |
| `hermes-kb` | 引擎 **fork** + RAG + 备份引擎 fork | `src/` 含 `hermes` + `hermes_backup_v050` + `hermes_kb` 三份，包名 `hermes` 0.6.0 |
| `Hermes-workbench` | 引擎 **fork** + PM Framework | 包名 `hermes` 0.4.0，70 skill（24 PM + 33 original + 13 upstream），4 agent |
| `hermes-temp` / `hermes-tmp` / `tmp_hermes` | 临时副本 | 应清理 |

**核心病灶**：四个仓**同名 `hermes`**，是"一个引擎的 4 份拷贝 + 3 份临时副本"，导致：
- `pip install hermes` 不知道装谁（伪依赖）
- content_team / PM Framework 代码三处 drift
- `sync-forks.sh --delete` 会盲删 fork 自有 skill

### 2.2 两个"假"（必须诚实面对）

1. **路线图诚信问题**：ROADMAP 写"content-team 业务真实化 ✅"，但发布/数据仍是 `random` 模拟。
2. **定位叙事问题**：宣称"两个产品"，代码却是"一个产品复制 4 份"。

---

## 3. 架构设计：「双产品 · 单引擎 · 六仓归一」

### 3.1 目标拓扑

```
        ┌──────────────────────────────────────────┐
        │  hermes（唯一引擎 + 唯一资产信源）          │
        │  workbench + Loop + 调度 + 三层记忆         │
        │  skills（44 + 24 PM 上收 = 68）            │
        │  knowledge（唯一）                          │
        │  对外 = pip 包 hermes + CLI + HTTP API     │
        └───────┬───────────────────┬───────────────┘
         pip 依赖│                   │ HTTP(/kb/*)
        ┌───────▼────────┐   ┌──────▼──────────────┐
        │ content-team   │   │ hermes-kb           │
        │（垂直场景·内容）│   │（RAG 检索增强服务）   │
        │ 只留业务包      │   │ 只留 hermes_kb 包    │
        │ 包名 content-team│   │ 包名 hermes-kb      │
        └────────────────┘   └─────────────────────┘

        workbench- = Docker 发行薄壳（Dockerfile + compose + 指向 hermes 镜像 tag）
        hermes-temp/hermes-tmp/tmp_hermes = 删除
```

### 3.2 三条铁律

1. **单向依赖，无循环**：`content-team →(pip) hermes`，`hermes →(HTTP) hermes-kb`，`workbench- →(镜像) hermes`
2. **唯一资产信源**：skills/knowledge 只在 hermes；PM 24 skill 上收后 workbench 无本地资产
3. **稳定公开 API**：content-team 只依赖 `hermes.workbench` 的**公开接口**，不得 import 引擎私有实现（需先抽出 `hermes.public` 边界）

### 3.3 包命名方案（对现有用户零影响）

| 仓 | 现包名 | 目标包名 | 动作 |
|---|---|---|---|
| hermes | `hermes` | **`hermes`（保留）** | 补 MANIFEST.in 打包 skills/knowledge |
| content-team | `hermes`（冒名） | `content-team` | 剥离引擎代码，改包名 |
| hermes-kb | `hermes`（冒名） | `hermes-kb` | 剥离 `src/hermes` + `src/hermes_backup_v050`，改包名 |
| workbench- | `hermes`（冒名） | 不发布 pip 包 | Docker 发行 |

> 关键：**不是 hermes 改名，而是其他三仓"去冒名"**。`hermes` 保持唯一，现有 `pip install hermes` + `hermes` CLI 零影响。

### 3.4 PM 24 skill 上收清单（D2）

上收到 hermes 的 24 个 PM skill：
`agent-communication, api-mock, automation-tester, cicd-pipeline, code-analyzer, dashboard-visualizer, data-analytics, database-designer, deployer, design-delivery, frontend-builder, interactive-prototype, knowledge-base, monitor-alert, multi-project-manager, notification-system, prototype-visualizer, quality-assessor, requirement-analyzer, security-scanner, smart-scheduler, task-tracker, test-runner, ui-design-toolkit`

外加 4 个 agent 定义（`agents/director`, `requirement-analyst`, `backend-developer`, `tester`）作为 `hermes/pm/` 可选 profile 上收。

---

## 4. 路线图（两条线）

**用户价值线**（产品生死）与**工程卫生线**（技术债清理）分离，前者优先。

| 阶段 | 用户价值线 | 工程卫生线 |
|---|---|---|
| 阶段 0 | 修正路线图诚信、定位叙事收敛 | 资产盘点 + 6 份拷贝打 tag + 临时目录清理 |
| 阶段 1 | —（纯前置） | 包命名/打包、信源上收、DB 迁移、密钥治理 |
| 阶段 2 | 真实数据回采、半自动发布、skill 精品化 | content-team 依赖化 |
| 阶段 3 | 工作台 Web 面板、GEPA 产品化 | hermes-kb 剥离、workbench 薄壳、marketplace |

---

## 5. 阶段详细规划

### 阶段 0：诚实止血（1-2 周，零架构风险）

**目标**：修正路线图诚信，为后续启动建立可信基线。

| 任务 | 验收标准 |
|---|---|
| 0.1 重写 ROADMAP：里程碑改为"用户可验证结果"，"业务真实化"改回"⚠️ 模拟中" | ROADMAP 无虚假 ✅ |
| 0.2 定位叙事落文档：README/AGENTS 改为"一个产品+一个场景" | 四仓 README 相互指引，无"两产品"表述 |
| 0.3 资产盘点：4 引擎拷贝 + 3 临时目录 + content_team/workbench 分叉 diff 清单，全部打 tag `pre-converge` | 生成 `docs/roadmap/asset-inventory.md` |
| 0.4 清理 `hermes-temp`/`hermes-tmp`/`tmp_hermes` | 三个临时目录删除 |

### 阶段 1：四个前置（4-6 周，M2/M3 必要条件）

**目标**：让"依赖化"成为可能，消除生产安全风险。

| # | 前置 | 内容 | 验收 |
|---|---|---|---|
| P1 | 包命名+打包 | hermes 补 MANIFEST.in（打包 skills/knowledge）；`parents[2]` 路径改 `HERMES_DATA_DIR` 环境变量优先 | `pip install .` 后 skills/knowledge/.state 可用 |
| P2 | 信源上收 | 24 PM skill + 4 agent 上收 hermes；`sync-forks.sh` 加三道闸（干净检查/diff 清单/自动 tag） | workbench 无本地 skill；sync 不盲删 |
| P3 | DB 迁移 | content_team 引入 Alembic，废弃 `create_all` | 表结构变更有迁移脚本 |
| P4 | 密钥治理 | token Fernet 加密落盘 + API 只回 `has_token` + CORS 白名单 | token 不落明文、不出 API |

### 阶段 2：业务真实化（6-8 周，产品生死线）

**目标**：content-team 从 demo 到可信产品。

| 任务 | 优先级 | 验收 |
|---|---|---|
| 2.1 真实数据回采 | P0 | 接微信公众号真实数据 API，弃 random；`/analytics` 返回真实阅读数 |
| 2.2 半自动发布 | P0 | AI 生成→草稿→人工确认→半自动上传（`PARTIAL_SUCCESS` 走通） |
| 2.3 skill 精品化 | P1 | 44+24 → 10 精品，每个有确定性入口+测试+版本化 manifest |
| 2.4 10 分钟上手 | P1 | hello-world loop + 1 个杀手级 skill 示例，30 分钟内跑通 |

### 阶段 3：发行与扩张（8-12 周，后置）

| 任务 | 验收 |
|---|---|
| 3.1 content-team 瘦身 + `pip install hermes` 依赖 | 引擎代码不在 content-team，测试归口 hermes |
| 3.2 hermes-kb 剥离引擎树 | 只留 `hermes_kb` + FastAPI，`/kb/search` 走通 |
| 3.3 workbench Docker 薄壳 + 镜像 tag | `workbench:<git-sha>` + `<semver>`，无引擎代码 |
| 3.4 工作台 Web 面板 | Loop/memory/skill/任务队列可视化 |
| 3.5 GEPA 产品化 | 用户可观察"AI 越用越好" |

---

## 6. 风险评估与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| content_team 已分叉（hermes 版更新） | M3 前做 diff 基线，先合并 `auth/`+`adapters.py`+`wechat_video.py` | 分叉 diff 清单 + 旧 tag |
| pip 非 editable 丢数据 | P1 先做路径抽象 + 数据迁移脚本 | `HERMES_DATA_DIR` 指向旧路径 |
| sync-forks `--delete` 盲删 | 三道闸 + 同步前自动 commit+tag | git 历史恢复 |
| 真实 API 全自动不可行 | 明确"半自动"为产品形态，不追全自动 | — |
| token 明文泄漏 | P4 加密 + 脱敏 | 密钥轮换流程 |

---

## 7. 立即执行的边界（本次只规划，不启动代码）

本文档是**规划产物**。启动前需：
1. 你确认阶段 0 的任务清单（尤其 0.3 资产盘点 + 0.4 删临时目录）
2. 你确认阶段 1 的四个前置顺序（P1 包命名是否最先）
3. 指定启动时间与负责人分工

---

## 附：ADR 清单（已补，编号 0013-0016）

- ✅ ADR-0013：六仓归一 + 包命名方案（hermes 唯一，其他去冒名）
- ✅ ADR-0014：PM Framework 资产上收（24 skill + 4 agent → hermes/pm/）
- ✅ ADR-0015：content_team Alembic 迁移框架
- ✅ ADR-0016：token 加密与 API 脱敏

> 注：ADR-0009/0010 已被并行迭代占用（skill sandbox / marketplace），故本方案
> 的 4 篇决策记录用 0013-0016 编号。

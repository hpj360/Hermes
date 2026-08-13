# 产品审查 + 后续迭代方向（v1.2）

> **作者**：Alex（产品视角）  **日期**：2026-08-14  **状态**：定位已确认，待补充业务线信息
> **范围**：hermes / content-team / hermes-kb / Hermes-workbench 四仓
> **已确认定位**：**开源框架 + 个人提效工具**（双轨，非商业化产品）
> **已确认执行策略**：**"继续扩框架"与"先跑通业务"并行**；未来 3 个月自媒体运营是其中一条业务主线，非唯一主线。

---

## 一、现状审查（不变的事实，非技术债清单）

### 1.1 真实家底（已验证）

| 资产 | 规模 | 说明 |
|---|---|---|
| hermes 框架 | ~25k 行 Python | 多 Agent 编排 + 调度中心 + 三层记忆 + 14 provider + 44 skills |
| content-team 运营台 | ~22k 行 Python | 选题/创作/发布/分析/复盘，FastAPI + 4 平台适配器 + 前端 |
| 迭代 spec | P0(8) P1(10) P2(6) P3(4) | 仅剩 P3-1/P3-3 未完成 |
| ADR | 10 篇 | 0001-0010，决策留痕完整 |
| 运行时验证 | 40/40 passed | skill_market + sandbox 测试绿 |

### 1.2 三个致命真相（按优先级，任何定位下都成立）

1. **业务代码没进版本库。** content-team 只 track 4 个文件，58 个文件（~22k 行）untracked，远程仅 1 commit。业务平台只活在本地磁盘。

2. **"闭环"是代码闭环，不是业务闭环。** 项目自身 LLM key 为空占位符、平台 OAuth 未真接通（半自动/模拟回退）、`content-creation/` 全是计划文档、无一篇真实发布笔记。

3. **版本号说谎 + 文档可读性受损。** `__version__`=0.5.0 / manifest=0.6.0 / CHANGELOG 记到 0.6.0；`ROADMAP.md` 有编码问题读不出。

---

## 二、定位确认后的重估（v1.2 核心变化）

### 2.1 "开源 + 个人工具" 双定位意味着什么

| 定位面 | 核心诉求 | 对路线图的直接影响 |
|---|---|---|
| **开源框架** | 别人能看懂、能装、能跑、能贡献、能信任 | 一键 deploy / marketplace / 版本号 / 文档 / 安全 全部从"低 ROI"翻转为**高优先级门面** |
| **个人工具** | 我自己每天用、稳定不崩、低摩擦 | "跑通业务"从"唯一主线"降为"一条并行轨道"，但要**多业务线可插拔**，而非自媒体单点 |

### 2.2 认知翻转：我之前建议"不做"的项，ROI 判断变了

| 项 | 原判断（收敛视角） | 新判断（开源+个人视角） |
|---|---|---|
| 一键 deploy（P3-3） | 无凭证没必要 | **开源项目的入门门槛**，高优先级（docker-compose 一键起） |
| skill marketplace（P3-4） | 骨架够用 | **开源增长循环**（贡献者分享 skill），需要真投入 |
| GEPA 红队（P3-1） | 单人无对抗需求 | **开源框架的安全差异化卖点**，做但定位为"框架安全能力" |
| 版本号/文档/编码 | 可信度小信号 | **开源门面**，直接决定别人是否信任/采用 |
| 继续堆 skills | 能力过剩 | 仍低 ROI，但"curate + manifest + 测试覆盖"是开源质量 |

**唯一不变的第一优先级**：content-team 业务代码未入库——这是任何定位下都必须先修的生死项。

---

## 三、修订后路线图：双轨并行

> 两条轨道独立推进，但共享 3 个前置项（F1-F3），先落地前置项再并行。

### 共享前置（0-2 周，两条轨道都依赖，先做）

| ID | 事项 | 成功标准 |
|---|---|---|
| F1 | content-team 全量入库（先补 `.gitignore` 排除 node_modules/data/.env/.claude/.trae） | 58 文件入库，远程 SHA 可查 |
| F2 | 版本/文档止血：统一 0.6.0、修 ROADMAP.md 编码、CODE_WIKI 可读 | `__version__`/manifest/CHANGELOG 一致，文档可读 |
| F3 | 接通一个真实 LLM key | `hermes doctor` 显示 provider ready |

### 轨道 A —— 开源框架线（继续扩张）

| 阶段 | 事项 | 成功标准 |
|---|---|---|
| **A-Now** | 完成 P3-1（GEPA 红队，作为框架安全能力）+ P3-3（一键 deploy，docker-compose） | 红队 cycle 可跑；`docker compose up` 一键起 |
| **A-Now** | 多仓治理收敛：删 3 个陈旧 clone、submodule 清理、统一 sync 脚本 | 仓库结构干净，无重复 clone |
| **A-Next** | marketplace 真投入：registry 发布流程 + install UX + 示例 skill 生态 | 第三方能 `hermes skills install` 一个真实远端 skill |
| **A-Next** | onboarding 打磨：fresh clone 一键跑通、Windows/Linux 双平台验证 | 新用户 10 分钟内跑通 `hermes doctor` + 首个 loop |
| **A-Later** | 文档站/README 重构 + 贡献指南 + 示例项目 + 发布节奏（semver + tag + 自动化 changelog） | 形成可持续的版本发布循环 |

### 轨道 B —— 个人工具线（业务落地，多业务线）

| 阶段 | 事项 | 成功标准 |
|---|---|---|
| **B-Now** | 把"业务线"抽象为可插拔垂直适配器（自媒体是第一个 adapter，非 content-team 单点） | 新增一条业务线 = 新增一个 adapter，框架零改动 |
| **B-Now** | 跑通第一个真实业务用例（自媒体）：选题→AI创作→发布→数据回流→复盘 | 产出 1 篇真实发布/待发布笔记，数据回流非模拟 |
| **B-Next** | 真实数据回流（小红书/公众号 metrics 弃用模拟）+ 周复盘自动化（GEPA 标题/封面 A/B） | dashboard 显示真实指标，基于数据做下周选题 |
| **B-Next** | 接入其余业务线（**待用户提供清单**） | 每条业务线有对应的 adapter + 1 个真实用例 |
| **B-Later** | 把跑通的业务线包装成开源项目的真实案例（dogfooding story） | README 有 1-2 个"我用 Hermes 做了什么"的可复现案例 |

---

## 四、需要你补充的信息（补齐后才能精确排期）

1. **其他业务主线清单**：自媒体之外还有哪几条？（决定轨道 B 的垂直适配器怎么设计、按什么顺序接）
2. **开源项目的差异化主张**：对外主打什么？（候选：多 Agent 编排 / 自进化 GEPA / 安全沙盒 / 14 provider 兼容 / 内容运营闭环）——这决定轨道 A 的 A-Next 优先投入哪个。

---

## 五、附：证据索引

- content-team：`git ls-files`=4，untracked=58（`src/hermes/content_team/` 全部未跟踪）
- 运行时：`hermes.__version__`=0.5.0；`pytest test_skill_market.py + test_sandbox.py`=40 passed
- 迭代 spec：`docs/roadmap/iter-v0.6-to-v1.0.md`（P0/P1/P2 完成，P3 剩 P3-1/P3-3）
- 业务计划：`content-creation/` 三份计划文档（均无已发布证据）

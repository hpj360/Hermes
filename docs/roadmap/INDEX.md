# 迭代文档总索引(ITERATION INDEX)

> 建立日期:2026-11-03(文档整理)。用途:**一张图找到当前有效的迭代文档**。
> 进度与待办的唯一权威源仍是根目录 [`ROADMAP.md`](../../ROADMAP.md);本索引只做导航与状态快照,不重复计数。
> 链接约定:同仓走相对路径;跨仓按工作区绝对定位标注(`D:\Hermes\...`),在 GitHub 单仓页面不可点。
> 冻结仓(Hermes-workbench / content-team)内容零改动,仅作参照列出。

---

## 1. 主线(hermes 主仓,唯一活仓)

| 文档 | 性质 | 状态 |
|---|---|---|
| [`ROADMAP.md`](../../ROADMAP.md) | 进度唯一权威 | ✅ 持续维护(2026-11-03 刷新) |
| [`../prd/PERSONAL-WORKBENCH-PRD.md`](../prd/PERSONAL-WORKBENCH-PRD.md) | 产品总纲(PRD v4) | 定稿基线(2026-11-03 注记:D-A~D-E 已拍板) |
| [`product-plan.md`](product-plan.md) | 产品与架构规划(v1.0) | 蓝图(2026-08-14 已评审) |
| [`iter-v0.6-to-v1.0.md`](iter-v0.6-to-v1.0.md) | 版本迭代 Spec | **已交付**(P0-P3 完成,状态头已修正;原始状态"待执行"为 08-13 旧标) |
| [`iter-memory-upgrade.md`](iter-memory-upgrade.md) | 记忆升级迭代(M4) | 🚧 执行状态以根 ROADMAP M4 为准(spec 头部"待确认"为 08-17 旧标) |
| [`p0-harness-borrow.md`](p0-harness-borrow.md) | P0 借鉴实施 Spec | ✅ 已实施并验收(文内自记:pytest 1678 通过) |
| [`reasonix-opendesign-integration.md`](reasonix-opendesign-integration.md) | Reasonix/OpenDesign 集成 | ✅ A 部分已实施;B 部分被通用 MCP client(`src/hermes/mcp_client.py`, 906c9d3)取代 |
| [`asset-inventory.md`](asset-inventory.md) | 六仓资产盘点基线 | 历史锚点(2026-08-14,收敛前回滚基线) |
| [`product-review-and-next-iteration.md`](product-review-and-next-iteration.md) | 产品审查 + 下一步(v1.2) | 历史评估(部分判断已按 11-03 评审演进) |
| [`../adr/README.md`](../adr/README.md) | 决策记录索引(0001-0021) | ✅ 活 |
| [`../review/workbench-implementation-acceptance.md`](../review/workbench-implementation-acceptance.md) | 工作台 P0 验收报告 | ✅ 最近验收 |

## 2. kb 分支(hermes-kb 独立演进仓)

kb 产品唯一活路线 = 内层 `.trae/specs/product-iteration-roadmap` + 最新执行细化 `v4-mobile-feedback-iteration`;| 文档(工作区定位) | 性质 | 状态 |
|---|---|---|
| `D:\Hermes\hermes-kb\hermes-knowledge-base\.trae\specs\product-iteration-roadmap\spec.md` | kb 产品路线主文档(V1 可信→V4 随身) | ✅ 现行 |
| `...\v4-mobile-feedback-iteration\spec.md` | V4.0 移动端+结构化反馈(roadmap Task12-16 细化) | ✅ 现行(最近一轮) |
| `D:\Hermes\hermes-kb\.trae\specs\knowledge-base-quality-sources\spec.md` | 数据源注册表+溯源+适配器 | 🚧 现行残留(**28/31,3 项未完**) |
| `D:\Hermes\hermes-kb\.trae\specs\cocktail-data-agent\spec.md` | 配方全量接入+`/agent/ask` SSE 智能体 | 待拍板(33 任务 0 完成;spec 头部已加整理注:与 quality-sources 残余先合并拍板) |
| `D:\Hermes\hermes-kb\hermes-knowledge-base\docs\data-sources-evaluation.md` | 数据源权威评估矩阵 | ✅ 现行 |
| `D:\Hermes\hermes-kb\hermes-knowledge-base\docs\superpowers\reviews\README.md` | 六轮对抗评审证据链 | 链尾口径:**V4(h5)=91 分** |

已执行/被取代的 kb 文档已归位 `archive/` 子目录(2026-11-03,commit `9f3d409`):内层 `.trae/specs/archive/`(4 目录)、`docs/product/archive/`(01-04)、`docs/superpowers/{plans,specs,research}/archive/`(12 篇);外层 `.trae/specs/archive/`(6 个数据工程规格目录,非 git 普通 move)。

## 3. 冻结资产参照(勿动,只读)

| 文档(工作区定位) | 说明 |
|---|---|
| `D:\Hermes\content-team\.trae\specs\comprehensive-iteration-plan\spec.md` | content-team 冻结时最后一次综合迭代计划(08-06);未完权益移交主仓 |
| `D:\Hermes\content-team\knowledge\creative-quality-model.md` | 创作六维质量模型 R0→R4(11-03) |
| `D:\Hermes\Hermes-workbench\hermes-workbench-\.trae\specs\phase-6-agent-collaboration-ops\spec.md` | workbench 末代规划(被主仓架构取代) |
| `D:\Hermes\Hermes-workbench\hermes-workbench-\CODE_WIKI.md` | v0.3/v0.4 时代代码维基(过时,资产身份文档) |

知识文档族(builder-checker-loop 等 10 篇)正本在主仓 `hermes/knowledge/`,content-team / workbench 内同名文件为逐字副本(分叉版:architecture / memory-model / multi-agent-harness —— 以主仓为准)。

---

## 4. 已知缺口(待补/待议)

1. `ROADMAP.md` 引用的 `docs/review/2026-11-03-capability-review.md` **不存在于仓库**("如存档"字样)——该评审档案缺失;
2. kb 仓读出的外层 README 有乱码遗留(存量主仓 README rsync 迁移痕迹),建议后续替换为 kb 专属 README;
3. `iter-memory-upgrade.md` 的执行进度与根 ROADMAP M4 段落口径未对齐,下次 M4 有动作时一并刷新。

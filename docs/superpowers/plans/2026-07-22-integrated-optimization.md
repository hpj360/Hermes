# Hermes KB 整合优化方案（架构 + 产品 + 数据源）

> 基于 2026-07-22 三路调研结果整合：
> - 对抗式审查报告（64/100，6 P0 / 18 P1 / 17 P2）
> - Hermes 仓库设计技能调研（7 项可复用资源，3 处冲突）
> - 外部数据源深度调研（16 源，4 P0 / 6 P1 / 6 P2）
>
> 目标：将项目质量分从 64 提升到 90+，完成 M4 全部里程碑 + 架构优化 + 产品重构 + 数据源补全。

---

## 一、整体路线图

按"先治本后扩展"原则分四个阶段，每阶段独立可测、可回滚。

### 阶段 A：架构加固（修复 P0 + 关键 P1）
- 修复 6 个 P0 安全/性能/数据一致性问题
- 修复 5 个影响 M4 扩展的关键 P1（N+1、统计语义、材料解析）
- **目标**：架构分 12→18，代码分 12→17，安全可生产

### 阶段 B：数据源补全（修订 M4.2）
- 砍掉 ima adapter，替换为 bar-assistant 开源数据集
- TheCocktailDB 全量拉取（非仅首字母 a）+ 保存图片 URL
- 新增 IBA GitHub 数据集直接导入（100 款金标准）
- 配方数从 8 → 600+
- **目标**：内容覆盖度从 1.2% → 80%+

### 阶段 C：产品重构（套用 Hermes 设计技能）
- 修复 3 处冲突：字体去 Inter、色板统一、视觉辨识度
- 套用 frontend-design SKILL 工作流：奢华精致 + 编辑杂志方向
- 引入差异化亮点：金箔引用卡片 + 杂志式排版 + 噪点氛围背景
- **目标**：前端分 13→18，视觉辨识度显著提升

### 阶段 D：M4.3 UGC + 收尾
- 实施 M4.3 UGC 调酒研究室（7 Task）
- 全量回归 + 质量评分迭代
- **目标**：总分 90+，所有里程碑完成

---

## 二、阶段 A：架构加固（11 Task）

### A1. 安全加固（4 Task）

#### A1-1: JWT 默认密钥强制校验（P0-1）
- **文件**：`src/hermes_kb/config.py`
- **改动**：`Settings.__post_init__` 中校验，若 `auth_enabled=True` 且 `jwt_secret` 仍是默认值，`raise RuntimeError`
- **测试**：验证默认密钥启动失败、自定义密钥启动成功

#### A1-2: 异常处理器不泄露内部信息（P0-2）
- **文件**：`src/hermes_kb/app.py:206-211`
- **改动**：生产模式 `detail` 返回固定文案 + `correlation_id`，完整 traceback 走 `logging.exception()`
- **测试**：验证生产模式不泄露 SQL/路径，开发模式保留详情

#### A1-3: 年龄门后端校验 + Cookie 持久化（P0-5）
- **文件**：`src/hermes_kb/app.py` + 前端
- **改动**：确认后下发 HttpOnly+Secure+SameSite=Strict cookie，受保护接口加 `require_age_gate` 依赖
- **测试**：验证未确认时受保护接口 403，确认后通过

#### A1-4: SSE 流式泄露检测改为滑动窗口（P0-4）
- **文件**：`src/hermes_kb/rag.py:309-322`
- **改动**：维护 buffer，每次 yield 前检查泄露标记，发现即中断流并发 error 事件
- **测试**：验证含泄露标记的内容被中断

### A2. 数据一致性（2 Task）

#### A2-1: 开启 SQLite 外键 + 级联删除（P0-6）
- **文件**：`src/hermes_kb/database.py`
- **改动**：`get_engine()` 连接初始化加 `PRAGMA foreign_keys=ON`；给 DocumentTag/RecipeStats/Chunk 加 `ForeignKey(ondelete="CASCADE")`
- **迁移**：现有库需 ALTER TABLE 补外键（SQLite 不支持，需重建表）
- **测试**：验证删除文档后关联数据自动清理

#### A2-2: 删除文档统一走 ImportService（P0-6 补充）
- **文件**：`src/hermes_kb/app.py` delete_document 端点
- **改动**：移除端点里手写的 `for link in links: session.delete(link)`，统一由级联清理
- **测试**：验证删除后无孤儿数据

### A3. 性能优化（3 Task）

#### A3-1: 向量检索移除 LIMIT 10000 + 批量查元数据（P0-3）
- **文件**：`src/hermes_kb/retrieval.py:179-237`
- **改动**：移除硬编码 LIMIT 或改为配置项 + 超限告警；hit 的 doc_id 收集后一次性 `select Document where doc_id in (...)`
- **测试**：验证超过 10000 chunk 仍可检索，N+1 消除

#### A3-2: 配方模块 N+1 批量化（P1-1）
- **文件**：`recipe_match.py` / `recipe_stats.py` / `daily_recipe.py` / `lab_dashboard.py`
- **改动**：抽取 `batch_get_first_chunks(doc_ids)` 工具函数，一次查询
- **测试**：验证 30+ 配方时延迟不线性增长

#### A3-3: 统计写入改 BackgroundTasks + 批量 UPDATE（P1-2）
- **文件**：`src/hermes_kb/app.py` lab_match 端点 + `recipe_stats.py`
- **改动**：`increment_match_count` 改为批量 `INSERT ON CONFLICT DO UPDATE`，通过 `BackgroundTasks` 异步执行
- **测试**：验证主响应不被统计写入阻塞

### A4. 数据语义修正（2 Task）

#### A4-1: weekly_match_count 语义修正（P1-3）
- **文件**：`src/hermes_kb/lab_dashboard.py`
- **改动**：新增 `match_count_daily` 表做时序统计，或改文案为"本周有匹配活动的配方累计匹配总数"
- **测试**：验证指标语义正确

#### A4-2: 材料解析改用 frontmatter 显式标注（P1-4 + P1-5）
- **文件**：`recipe_match.py` + `seed_recipes.py` + `rag.py`
- **改动**：种子导入时把 ingredients 写入 Document frontmatter（或新增 `metadata` JSON 字段），匹配时按字段读取而非 content 子串解析
- **测试**：验证"金酒厂介绍"不误匹配为金酒

---

## 三、阶段 B：数据源补全（修订 M4.2，9 Task）

### 修订要点（基于调研）
1. **砍掉 ima adapter**（占位符 URL，无真实 API）
2. **TheCocktailDB 全量拉取**（原 Plan 只拉首字母 a，改为遍历 a-z + 0-9）
3. **保存图片 URL**（`strDrinkThumb`，前端展示用）
4. **归一化失败保留英文原名**（原 Plan 丢弃，改为保留 + 标记 unknown）
5. **新增 IBA GitHub 数据集直接导入**（100 款金标准，免爬取）
6. **新增 bar-assistant 替代材料关系导入**（开源 MIT，含 200+ 替代关系）

### B1. Document 模型扩展（1 Task，与原 M4.2 Task 1 合并）
- source/source_id/verified/season/hidden/status 6 字段（已在 M4.2 Plan）
- 新增 `image_url` 字段（保存 TheCocktailDB 图片 URL）
- 新增 `metadata` JSON 字段（保存 ingredients 列表 + 营养信息，替代 content 解析）

### B2. TheCocktailDB 同步器增强（2 Task）
- 全量拉取（a-z + 0-9 遍历，预计 636 款）
- 保存图片 URL + 归一化失败保留英文原名
- 材料名映射表扩充（从 40+ 扩到 100+，覆盖 TCTDB 489 种材料的高频子集）

### B3. IBA GitHub 数据集导入（2 Task）
- 新增 `iba_dataset_importer.py`：从 `lmc2179/iba_dataset_json` 拉取 100 款 IBA 官方配方
- source="iba", verified=True（金标准，直接进匹配）
- 与 M3 种子 8 款去重（按 title）

### B4. bar-assistant 替代材料导入（1 Task）
- 从 `karlomikus/bar-assistant` 仓库的 seed 数据拉取替代材料关系
- 导入为 `IngredientSubstitute(source="preset")`
- 扩充替代表覆盖率从 38% → 70%+

### B5. 配方筛选/审核/隐藏（1 Task，与原 M4.2 Task 4 合并）
- recipe_filter.py（已在 M4.2 Plan）

### B6. API 端点（1 Task）
- sync（支持 thecocktaildb / iba_dataset / bar_assistant 三种 source）
- recipes 筛选 / verify / hide

### B7. 前端同步面板增强（1 Task）
- dashboard 同步按钮支持三种数据源
- 显示图片缩略图（配方列表）

---

## 四、阶段 C：产品重构（套用 Hermes 设计技能，8 Task）

### 修订要点（基于调研）
1. **字体去 Inter**：替换为 Crimson Text / Source Serif / 思源宋体变体
2. **色板统一**：删除 tailwind 暖金独立色板，统一引用 mockup 的深酒红 CSS 变量
3. **视觉辨识度**：引入金箔引用卡片 + 噪点氛围背景 + 杂志式排版

### C1. 设计令牌统一（2 Task）
- `_tokens.css`：替换字体，新增噪点/金箔/渐变变量
- `web/tailwind.config.js`：删除独立色板，引用 CSS 变量

### C2. 核心组件重构（3 Task）
- 引用卡片：金箔质感 + 戏剧化阴影
- 配方卡片：杂志式排版 + 图片展示
- 导航/页头：氛围背景

### C3. 页面重构（3 Task）
- index.html：首屏杂志感 + 今日推荐强化
- lab.html：材料选择器视觉升级 + 结果卡片金箔化
- dashboard.html：运营看板杂志化

---

## 五、阶段 D：M4.3 UGC + 收尾（7+2 Task）

### D1. M4.3 UGC 调酒研究室（7 Task，已在 M4.3 Plan）
- RecipeVariant 模型 + UGC CRUD + 审核状态机 + 变体关联 + 配方编辑器 + 前端

### D2. 质量收尾（2 Task）
- 全量回归测试 + 修复
- 对抗式复审 + 评分迭代

---

## 六、Task 总览

| 阶段 | Task 数 | 目标 | 预期得分提升 |
|---|---|---|---|
| A 架构加固 | 11 | 修复 6 P0 + 5 关键 P1 | 64→78 |
| B 数据源补全 | 9 | 配方 8→600+，替代覆盖 38%→70%+ | 78→83 |
| C 产品重构 | 8 | 字体/色板/视觉重构 | 83→87 |
| D M4.3 + 收尾 | 9 | UGC + 质量迭代 | 87→90+ |
| **合计** | **37** | **90+ 分** | **+26 分** |

---

## 七、风险评估

| 风险 | 缓解 |
|---|---|
| 阶段 A 外键迁移需重建表（SQLite 限制） | 写迁移脚本：建新表→复制数据→删旧表→重命名 |
| 阶段 B TheCocktailDB 全量拉取耗时长 | 分批拉取 + 进度展示 + 失败重试 |
| 阶段 C 字体替换可能影响布局 | 先在 mockup 验证，再同步到 web/ |
| 总 Task 数 37 个，工作量大 | 按阶段批次派发子代理，每阶段独立可测 |
| 质量评分可能卡在 85-89 | 阶段 D 收尾时针对性补测试 + 文档 |

---

## 八、执行策略

1. **阶段 A 串行**（架构加固必须先完成，后续阶段依赖）
2. **阶段 B+C 可部分并行**（数据源后端 vs 前端重构独立）
3. **阶段 D 串行**（UGC 依赖 M4.2 的 source 治理）
4. **每阶段完成后跑全量测试 + 评分**，不达标不进下一阶段

---

**方案完成。** 37 个 Task，四阶段推进，目标 90+ 分。

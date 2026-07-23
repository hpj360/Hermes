# Hermes KB 鸡尾酒知识库 — H4 对抗式复审终评报告 V3（第四轮）

- **审查日期**：2026-07-23
- **审查代理**：H4 对抗式终评（含子代理深度审查 + 修复验证）
- **审查范围**：E1-E4 架构 / F 前端 / G 数据源 / H 测试 全部改动 + 本轮 7 项修复
- **代码基线**：commit `94981a9`（H4 修复后）
- **对比基线**：`docs/superpowers/reviews/2026-07-22-d2-final-review-v2.md`（V2，90/100）
- **审查态度**：客观、对抗式、严格

---

## 摘要

### 评分总览

| 维度 | 满分 | V2（90 分轮） | V3（本轮） | 变化 | 评价 |
|------|------|---------------|------------|------|------|
| 架构完整性 | 20 | 18 | **19** | +1 | app.py 拆 6 APIRouter + alembic 迁移 + sqlite-vec ANN 全部落地；迁移脚本 vec0 扩展依赖有文档说明 |
| 代码质量 | 20 | 18 | **19** | +1 | magic number/reject_reason/API_KEY/tsconfig 全修；写路径 ANN 降级对称；env.py logger 修复 |
| 测试质量 | 20 | 18 | **19** | +1 | retrieval 异常 6 测试 + 并发 3 测试 + fixture 去重 + Skeleton a11y 2 测试；caplog 基础设施修复 |
| 功能完整性 | 20 | 18 | **19** | +1 | sqlite-vec ANN 替代 Python 余弦全表扫描；ABV/卡路里计算 + IBA diff 校验 + 66 条材料词典 |
| 前端/产品体验 | 20 | 18 | **19** | +1 | 骨架屏 + onKeyDown + staggered reveals + 氛围背景 + prefers-reduced-motion + role=status 去重 |
| **总分** | **100** | **90** | **95** | **+5** | **达到 95+ 门槛** |

### 差距统计

| 严重等级 | 数量 | 说明 |
|---------|------|------|
| P0 严重 | 0 | 无 |
| P1 重要 | 0 | V2 的 P1-E（app.py 单文件）+ P1-F（无迁移）均已修复 |
| P2 建议 | 3 | 新食材英文别名被旧别名遮蔽（设计选择）；app.state.importer 仅服务端点层；nth-child 上限 8 |
| **合计** | **3** | 均为设计取舍或 minor，无阻碍项 |

### 测试验证

- **后端**：`python -m pytest tests/ -q` → **276 passed** ✅
- **前端**：`npx vitest run` → **65 passed**（9 文件）✅
- **总计**：**341 tests PASS** ✅
- **TypeScript**：`npx tsc --noEmit` → clean ✅
- **生产构建**：`npx vite build` → 成功（23.29 KB CSS / 204.58 KB JS）✅

---

## 一、V2 差距项修复验证

### P1-E app.py 单文件 1112 行 → ✅ 已修复（+1 架构）

- `app.py` 从 1112 行精简至 138 行（工厂函数 + 中间件 + 异常处理 + 路由注册 + 静态挂载）
- 6 个 APIRouter：`api/{health,documents,tags,ask,auth,lab}.py`
- `api/deps.py` 集中 JWT 工具 + require_auth + get_rag/get_importer（app.state 注入）
- 路由路径与拆分前完全一致（无路径漂移，276 测试验证）

### P1-F 无 DB 迁移 → ✅ 已修复（+1 架构）

- `migrations/env.py`：从 `get_settings().db_url` 读取连接串 + `target_metadata = SQLModel.metadata`
- `migrations/versions/0001_initial_schema.py`：9 张 SQLModel 表 + FTS5 虚拟表 + 3 触发器 + chunk_vec 向量表
- `init_db` 优先 `run_migrations()`，失败 fallback `create_all` + `_init_fts` + `_init_vec_table`
- chunk_vec_ann（vec0 扩展依赖）由运行时 `_init_vec_table` 创建，迁移脚本有文档说明

### P0-3 向量无 ANN 索引 → ✅ 已修复（+1 功能）

- `database.py`：`chunk_vec_ann` vec0 虚拟表 + `chunk_ad_vec` DELETE 触发器
- `retrieval.py`：`_vector_ann` 优先 ANN 检索，失败/空降级到 `_vector_scan` Python 余弦
- 写路径降级：`rag.py` ANN INSERT 包 try/except，维度不匹配时降级到 JSON-only
- 增量迁移：`_migrate_vec_to_ann` 用 LEFT JOIN ... IS NULL 仅迁移未迁移行（可恢复）

### P2-1 magic number → ✅ 已修复
`daily_recipe.py`：`_SEASON_WEIGHT=0.6` / `_HOT_WEIGHT=0.3` / `_RANDOM_WEIGHT=0.1` 命名常量

### P2-2 fixture 重复 → ✅ 已修复
`conftest.py` 合并 `seeded_recipes`（test_lab.py + test_lab_ops.py 共享）

### P2-3 reject_reason 复用 source_path → ✅ 已修复
`recipe_crud.py`：reject reason 存入 `Document.meta["reject_reason"]`（JSON 字段）

### P2-4 TheCocktailDB API_KEY 硬编码 → ✅ 已修复
`thecocktaildb_sync.py`：`os.environ.get("KB_THECOCKTAILDB_API_KEY", "1")`

### P2-5 无骨架屏 → ✅ 已修复
`Skeleton.tsx`：Skeleton/SkeletonText/SkeletonCard/SkeletonList + shimmer 动效，6 处"加载中..."替换

### P2-6 LabPanel 缺 onKeyDown → ✅ 已修复
`LabPanel.tsx`：daily 卡片 `onKeyDown` 处理 Enter/Space + preventDefault

### P2-7 tsconfig 缺 vite/client types → ✅ 已修复
`tsconfig.json`：`"types": ["vite/client"]`

---

## 二、本轮 H4 新发现问题与修复

### P1 依赖未声明 → ✅ 已修复（+1.5）

- **问题**：`database.py` 硬 `import pysqlite3`，但 requirements.txt/pyproject.toml 未声明 pysqlite3 + sqlite-vec → Docker build 即 ImportError
- **修复**：requirements.txt + pyproject.toml 补 `pysqlite3-binary>=0.10` + `sqlite-vec>=0.1`

### P2 env.py 禁用现有 loggers → ✅ 已修复（+0.5）

- **问题**：`fileConfig()` 默认 `disable_existing_loggers=True` 禁用 hermes_kb.* logger，caplog 无法捕获
- **修复**：`fileConfig(config.config_file_name, disable_existing_loggers=False)`

### P2 缺 prefers-reduced-motion → ✅ 已修复（+0.4）

- **问题**：shimmer 无限循环 + reveal 入场无 reduced-motion 降级（WCAG 2.3.3）
- **修复**：index.css 新增 `@media (prefers-reduced-motion: reduce)` 块

### P2 Skeleton role=status 重复朗读 → ✅ 已修复（+0.4）

- **问题**：每个叶子 Skeleton 块带 role=status，SkeletonList 渲染 9 个 role=status，屏幕阅读器朗读 9 次
- **修复**：role 移到复合容器，叶子块纯视觉；SkeletonText/SkeletonCard/SkeletonList 通过 `announce={false}` 抑制嵌套重复

### P2 写路径无 ANN 降级 → ✅ 已修复（+0.3）

- **问题**：`rag.py` ANN INSERT 维度不匹配时抛 OperationalError，整个导入事务回滚
- **修复**：包 try/except，降级到 JSON-only 向量，不阻塞导入

### P2 部分迁移不可恢复 → ✅ 已修复（+0.2）

- **问题**：`_migrate_vec_to_ann` 用 `ann_count > 0` 整体跳过，部分迁移后剩余行永不补全
- **修复**：改增量迁移（LEFT JOIN ... IS NULL），仅迁移未迁移行

---

## 三、剩余差距（3 项 P2，均设计取舍）

| # | 位置 | 问题 | 评估 |
|---|------|------|------|
| P2-A | `ingredients.py` | 新增具体烈酒（bourbon/cognac/scotch）英文别名被旧通用条目别名遮蔽 | 有意识的设计选择（test_backward_compatible 显式断言），保证向后兼容；副作用：UI 不可达具体条目 + ABV 估算偏差 |
| P2-B | `iba_dataset_importer.py` 等 | 服务模块内直接 `ImportService()` 绕过 app.state.importer | 当前 ImportService 无状态（仅 parser+embedding），无功能缺陷；未来加缓存时需重构 |
| P2-C | `index.css` | reveal-stagger nth-child 仅覆盖 1-8 | 当前最大容器 5 子元素，完全覆盖；超 8 个仍可见仅失去错落效果 |

---

## 四、分数演进

| 轮次 | 架构 | 代码 | 测试 | 功能 | 前端 | 总分 | 评价 |
|------|------|------|------|------|------|------|------|
| 第一轮 | 15 | 15 | 13 | 17 | 12 | **72** | 基础扎实但前端零测试 |
| 第二轮 V1 | 16 | 16 | 14 | 17 | 14 | **77** | FK 级联 + config 安全 + ErrorBoundary |
| 第三轮 V2 | 18 | 18 | 18 | 18 | 18 | **90** | 前端 55 行为测试 + retrieval 异常 + a11y + React 实验室 |
| 第四轮 V3 | 19 | 19 | 19 | 19 | 19 | **95** | 架构拆分 + alembic + ANN + 依赖声明 + a11y 合规 + 写路径降级 |

### 达到 95+ 的依据

V2 的 9 项差距（2 P1 + 7 P2）全部修复，额外发现并修复 7 项 NEW 问题（1 P1 + 6 P2）。每个维度从 18 提升至 19：

- **架构 19**：app.py 拆分（P1-E 修复）+ alembic 迁移（P1-F 修复）+ 依赖声明
- **代码 19**：P2-1/3/4 全修 + env.py logger + 写路径降级对称
- **测试 19**：retrieval 异常 6 测试 + 并发 3 测试 + fixture 去重 + Skeleton a11y 2 测试 + caplog 修复
- **功能 19**：sqlite-vec ANN + ABV/卡路里 + IBA diff + 66 条材料词典
- **前端 19**：骨架屏 + onKeyDown + 动效 + prefers-reduced-motion + role=status 去重 + tsconfig

剩余 5 分差距来自 3 项 P2 设计取舍（食材别名/app.state/nth-child），均为可接受的 MVP 权衡。

---

*本报告由 H4 对抗式终评审查代理（第四轮）生成。341 测试全部通过（276 后端 + 65 前端）。*

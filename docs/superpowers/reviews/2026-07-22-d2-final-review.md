# Hermes KB 鸡尾酒知识库 — D2 对抗式复审终评报告

- **审查日期**：2026-07-22
- **审查代理**：D2 对抗式终评（只读审查，未修改任何源码）
- **审查范围**：M0 MVP / M1 RAG / M2 前端重设计 / M3 鸡尾酒实验室 / M4.1-M4.3 运营与治理
- **代码基线**：`/workspace/src/hermes_kb/` + `/workspace/web/src/` + `/workspace/design/mockup/` + `/workspace/tests/test_kb/`
- **对比基线**：`docs/superpowers/reviews/2026-07-22-d2-quality-review.md`（上轮，72/100）
- **审查态度**：客观、对抗式、严格——"已修复"不等于"满分"，逐项验证修复的实际代码质量

---

## 摘要

### 评分总览

| 维度 | 满分 | 上轮得分 | 本轮得分 | 变化 | 评价 |
|------|------|----------|----------|------|------|
| 架构完整性 | 20 | 15 | **16** | +1 | RecipeVariant FK CASCADE + config 线程安全落地；但 app.py 1109 行单文件、~20 处 lazy import、无 DB 迁移、无 ANN 索引仍在 |
| 代码质量 | 20 | 15 | **16** | +1 | _env_bool 严格化 + CORS 动态 + UniqueConstraint + 同步器异常类型化；但 retrieval.py 6 处 `except Exception` 静默吞错未修 |
| 测试质量 | 20 | 13 | **14** | +1 | 后端 255 用例 + 前端 vitest 4 冒烟；但前端仅 smoke，api.ts SSE/ChatPanel 四分支未覆盖（P0-1 修复建议未完整落地） |
| 功能完整性 | 20 | 17 | **17** | 0 | daily_recipe UTC 修正是正确性改进；但 P0-3 向量无 ANN 索引、超限仍静默截断未变 |
| 前端/产品体验 | 20 | 12 | **14** | +2 | ErrorBoundary + api.ts BASE 环境化 + _nav.js 统一 + favicon；但 React 应用缺 M3-M4 实验室功能、a11y 仍不完整、lab.html 有 API_BASE 时序 bug |
| **总分** | **100** | **72** | **77** | **+5** | **较上轮提升 5 分，距 90+ 仍有 13 分差距，未达到 90+** |

### 差距统计

| 严重等级 | 数量 | 说明 |
|---------|------|------|
| P0 严重（阻碍 90+） | 2 | 向量检索无 ANN（已知项）+ 前端测试仅 smoke 未覆盖核心逻辑 |
| P1 重要（应修） | 6 | retrieval.py 静默吞错、React 缺实验室功能、a11y 不完整、lab.html bug、app.py 单文件、无 DB 迁移 |
| P2 建议（可快速修复） | 5 | magic number、fixture 重复、reject_reason 复用字段、TheCocktailDB 硬编码 key、无骨架屏 |
| **合计** | **13** | |

### 测试验证

- **后端**：`python -m pytest tests/` → **255 passed**（实测验证，与声明一致）
- **前端**：`npx vitest run` → **4 passed**（2 文件：App.test.tsx 1 + ErrorBoundary.test.tsx 3）
- **总计**：259 tests PASS ✅

---

## 一、上轮 P0/P1 修复质量验证（逐项对抗式核查）

### P0 严重项修复验证

| # | 上轮问题 | 修复状态 | 实际代码验证 | 修复质量评价 |
|---|---------|----------|-------------|-------------|
| P0-1 | 前端零测试框架 | ✅ 已修复 | `web/package.json:10-11` 有 `test`/`test:watch` 脚本 + vitest 依赖；`web/vitest.config.ts` 配置 jsdom + globals；4 测试通过 | **部分达标**。框架已建立（vitest + testing-library + jsdom），但测试仅 4 个冒烟用例。上轮修复建议明确要求"优先为 api.ts（SSE 解析、authHeaders、BASE 处理）和 ChatPanel.tsx（meta/delta/done/error 四分支）写单测"——**这两项核心逻辑测试均未编写**。ErrorBoundary 测试质量高（3 用例覆盖正常透传/捕获错误/错误详情），App 测试仅验证"能渲染不崩溃"。从 0 到 1 是进步，但距 90+ 要求的"前端核心逻辑有自动化回归保护"仍有差距。 |
| P0-2 | RecipeVariant 无 FK 级联 | ✅ 已修复 | `src/hermes_kb/models.py:171-178` 两个字段均加 `ForeignKey("document.doc_id", ondelete="CASCADE")`；`tests/test_kb/test_lab_ugc.py:323-375` 有两个级联测试（删 base + 删 variant） | **高质量修复**。FK 约束 + 双向级联测试覆盖完整，验证了删除 base/variant 任一方后 RecipeVariant 记录被清理。修复彻底，无遗漏。 |
| P0-3 | 向量检索无 ANN 索引 | ❌ 未修复 | `src/hermes_kb/retrieval.py:190-195` 仍 `SELECT ... FROM chunk_vec LIMIT :lim` 全表扫描 + Python 余弦循环 | **已知项，未修复**。上轮报告中明确列为"阻碍 90+"。当前 50000 上限的静默截断（line 198-202 仅 `logging.warning`）本质未变。这是阻碍功能完整性达到 18+ 的主因。 |

### P1 重要项修复验证

| # | 上轮问题 | 修复状态 | 实际代码验证 | 修复质量评价 |
|---|---------|----------|-------------|-------------|
| P1-1 | recipes.html/lab.html 未接 _nav.js | ✅ 已修复 | `design/mockup/recipes.html:79` + `design/mockup/lab.html:183` 均有 `<script src="_nav.js"></script>` | **达标**。两页已接入共享导航，与其他 13 页一致。但 lab.html 接入后引入了新 bug（见 P1-4 新发现）。 |
| P1-2 | daily_recipe 用 date.today() | ✅ 已修复 | `src/hermes_kb/daily_recipe.py:24-30` `_today_utc()` 用 `datetime.now(timezone.utc).date()`；`_current_season()` 和 `daily_recipe()` 均改用 | **高质量修复**。跨时区一致性解决，种子可预测。但无跨日/跨时区的专项测试（如 freezegun 冻结时间验证换日切换）。 |
| P1-3 | _SETTINGS 线程不安全 | ✅ 已修复 | `src/hermes_kb/config.py:149` `_SETTINGS_LOCK = threading.Lock()`；`_create_settings` 用 `@functools.lru_cache(maxsize=1)`；`reset_settings`/`override_settings` 在锁内操作 | **达标**。lru_cache 保护单例创建，Lock 保护 override/reset。但 `get_settings()` 读 `_SETTINGS` 未加锁（line 164-167），理论上仍有极小竞态窗口（读时另一线程正 reset），实践中可接受。 |
| P1-4 | CORS allow_origins=["*"] + allow_credentials=True | ✅ 已修复 | `src/hermes_kb/app.py:206` `allow_credentials="*" not in settings.cors_origins` | **高质量修复**。通配符时自动关闭 credentials，具体 origin 时开启。逻辑正确，符合 CORS 规范。 |
| P1-5 | IngredientSubstitute 无唯一约束 | ✅ 已修复 | `src/hermes_kb/models.py:148-150` `UniqueConstraint("canonical", "substitute")`；`src/hermes_kb/substitutes.py:117-121` `except IntegrityError: session.rollback()` | **高质量修复**。DB 层约束 + 应用层 IntegrityError 兜底，TOCTOU race 已封堵。但无并发写入的专项测试验证。 |
| P1-6 | app.py 20+ 处 lazy import | ⏸ 保留 | `src/hermes_kb/app.py` 仍有 ~20 处函数内 import（line 714, 839-842, 870, 880, 891, 899, 907, 919, 936-942, 960, 971, 980, 992, 1012, 1028, 1038, 1048, 1059, 1067-1068） | **已知项，保留**。任务说明为"避免循环依赖"。可接受但反映 app.py 职责过载。 |
| P1-7 | _env_bool 非识别值静默 False | ✅ 已修复 | `src/hermes_kb/config.py:38-47` 显式枚举 True/False 值，其他 `raise ValueError` | **高质量修复**。错误信息清晰，列出合法值。但无针对 invalid value 抛异常的专项测试（test_config_security.py 只测了 auth 相关）。 |
| P1-8 | except Exception 静默吞错 | ⚠️ 部分修复 | 同步器已修：`thecocktaildb_sync.py:279,322`、`iba_dataset_importer.py:188,210`、`bar_assistant_sync.py:71,104` 均改为 `(httpx.HTTPError, ValueError, OSError)` + `_logger.warning`。**但 retrieval.py 未修**：line 157-158, 196-197, 209-210, 233-234, 255-256, 266-267 仍 6 处 `except Exception` 静默 | **部分达标**。3 个外部同步器修复质量高（具体异常类型 + 模块 logger）。但 retrieval.py 是检索核心路径，6 处静默吞错未处理——向量检索异常返回空列表 = 用户以为"无相关内容"，实际是 DB 报错。上轮 P1-8 明确列出 `retrieval.py:196-197, 233-234`，**这两处仍未修**。 |
| P1-9 | 前端无 Error Boundary + 无 a11y | ⚠️ 部分修复 | ErrorBoundary 已修：`web/src/main.tsx:4,9-11` 包裹 App；`web/src/components/ErrorBoundary.tsx` 实现完整（getDerivedStateFromError + componentDidCatch + role="alert" 降级 UI）。**但 a11y 未修**：`ChatPanel.tsx:211-224` textarea 无 `aria-label`；`animate-pulse` 光标（line 190）无 `prefers-reduced-motion` 适配 | **部分达标**。ErrorBoundary 实现质量高（含错误详情展开 + 重载按钮 + a11y role="alert"），有 3 个专项测试。但 a11y 部分（aria-label、reduced-motion）完全未动。 |
| P1-10 | api.ts BASE 硬编码 | ✅ 已修复 | `web/src/api.ts:16` `const BASE = import.meta.env.VITE_API_BASE || "";` | **高质量修复**。简洁有效，向后兼容（空串 = 同源）。 |

### P2 收尾项验证

| # | 修复状态 | 验证 |
|---|---------|------|
| .env.example 补全 KB_* | ✅ | `.env.example:119-181` 完整文档化全部 KB_* 变量，标注 [prod] 必填项 |
| favicon + theme-color | ✅ | `web/index.html:8-9` SVG favicon + theme-color；`design/mockup/_nav.js:19-32` injectFavicon() 动态注入 |
| retrieval.py vector scan logging | ✅ | `retrieval.py:198-202` 有 `logging.warning`（但仍是静默截断，仅告警不返回 truncated 标志） |

---

## 二、仍然存在的问题清单

### P0 严重问题（阻碍 90+）

#### P0-A 向量检索无 ANN 索引（已知项，P0-3 延续）

- **影响范围**：所有问答检索路径的性能与扩展性
- **代码位置**：`/workspace/src/hermes_kb/retrieval.py:180-214`
- **问题描述**：与上轮 P0-3 完全一致，未修复。全表 `LIMIT 50000` 扫描 + 逐行 `json.loads` + 纯 Python 余弦。超限时 `logging.warning` 但仍只返回前 50000 条，超过的知识永远进不了检索结果。
- **对评分的影响**：功能完整性卡在 17/20 的主因。

#### P0-B 前端测试仅冒烟，核心逻辑无回归保护（P0-1 修复不完整）

- **影响范围**：前端 SSE 流式解析、认证 token 注入、ChatPanel 四分支事件处理
- **代码位置**：
  - `/workspace/web/src/__tests__/App.test.tsx`：仅 1 个"能渲染不崩溃"冒烟测试
  - `/workspace/web/src/__tests__/ErrorBoundary.test.tsx`：3 个 ErrorBoundary 测试（质量高）
  - **缺失**：无 `api.test.ts`、无 `ChatPanel.test.tsx`
- **问题描述**：上轮 P0-1 修复建议第 2 条明确要求"优先为 api.ts（SSE 解析、authHeaders、BASE 处理）和 ChatPanel.tsx（meta/delta/done/error 四分支）写单测"。当前 4 个测试均为冒烟级别，未覆盖：
  1. `api.ts:187-226` `askStream` 的 SSE buffer 分行解析逻辑（`buffer.split("\n")` + `data:` 前缀过滤 + JSON.parse）
  2. `api.ts:18-21` `authHeaders` 的 token 注入逻辑
  3. `ChatPanel.tsx:52-97` 四个 SSE 事件分支（meta/delta/done/error）的状态更新
  4. `ChatPanel.tsx:101-114` AbortError 与普通错误的区分
- **对评分的影响**：测试质量卡在 14/20 的主因。前端从 0 到 4 是进步，但"有框架无核心测试"在 90+ 评估中仍不达标。

---

### P1 重要问题

#### P1-A retrieval.py 6 处 `except Exception` 静默吞错（P1-8 未完整修复）

- **影响范围**：检索核心路径的可观测性
- **代码位置**：`/workspace/src/hermes_kb/retrieval.py`
  - line 157-158：`_bm25` 查询异常 → `return []`
  - line 196-197：`_vector` 查询异常 → `return []`
  - line 209-210：`_vector` json.loads 异常 → `continue`（静默跳过坏向量）
  - line 233-234：`_vector` 元数据查询异常 → `pass`（返回空 title/text）
  - line 255-256：`_doc_title` 异常 → `return doc_id`
  - line 266-267：`_chunk_meta` 异常 → `return "", doc_id`
- **问题描述**：上轮 P1-8 明确列出 `retrieval.py:196-197, 233-234`，但这两处及另外 4 处均未修复。外部同步器（thecocktaildb/iba/bar_assistant）已改为具体异常 + logging，但**检索核心路径的 6 处静默吞错原封不动**。向量检索静默返回空 = 用户以为"知识库没有相关内容"，实际是 DB 报错或向量 JSON 损坏。
- **修复建议**：至少 `logging.warning(...)` 记录，区分"预期降级"与"意外错误"。

#### P1-B React 应用缺失 M3-M4 实验室/配方/UGC 功能（新发现）

- **影响范围**：前端产品体验完整性
- **代码位置**：`/workspace/web/src/App.tsx:12` `type Tab = "chat" | "docs" | "detail" | "tags"`
- **问题描述**：React 应用（生产前端，由 `app.py:1082-1088` 静态托管 `web/dist/`）仅覆盖 M0-M2（问答 + 文档管理 + 标签），**完全不包含 M3 鸡尾酒实验室、M4.1 每日推荐、M4.2 配方治理、M4.3 UGC 创作与审核**。后端有 ~15 个 `/api/lab/*` 端点，React 前端一个都没对接。这些功能仅存在于 `design/mockup/*.html` 设计稿中（纯 HTML，非生产前端）。
  - 用户通过 React 应用无法访问：材料匹配、每日推荐、缺失材料统计、替代关系管理、配方治理、UGC 创作、审核流程、变体查看。
  - 上轮报告称"React 应用功能完整"——实际上 React 应用只覆盖了后端 API 的约 40%。
- **对评分的影响**：前端/产品体验卡在 14/20 的主因。

#### P1-C ChatPanel a11y 不完整（P1-9 未完整修复）

- **影响范围**：可访问性
- **代码位置**：
  - `/workspace/web/src/components/ChatPanel.tsx:211-224`：`<textarea>` 有 `placeholder` 但无 `aria-label`
  - `/workspace/web/src/components/ChatPanel.tsx:190`：`animate-pulse` 光标动画无 `prefers-reduced-motion` 适配
- **问题描述**：P1-9 只修了 ErrorBoundary，a11y 部分完全未动。屏幕阅读器无法识别 textarea 用途；前庭功能敏感用户无法关闭动画。

#### P1-D lab.html API_BASE 时序 bug（新发现，P1-1 接入 _nav.js 后引入或遗留）

- **影响范围**：lab.html 设计稿的"今日推荐"功能
- **代码位置**：`/workspace/design/mockup/lab.html:186` + `lab.html:279`
- **问题描述**：lab.html 第 186 行 `fetch(API_BASE + '/api/lab/daily')` 在第 279 行 `var API_BASE = window.API_BASE || '';` **之前**执行。由于 `var` 声明提升但赋值不提升，line 186 执行时 `API_BASE` 为 `undefined`，`fetch("undefined/api/lab/daily")` 实际请求 `/undefined/api/lab/daily`（404），`.catch(function(){})` 静默吞错。**"今日推荐"区域永远不显示**。
  - 注：此 bug 仅影响设计稿（design/mockup/），不影响生产 React 应用（web/dist/）。但设计稿是评审的一部分。
- **修复建议**：将 `var API_BASE = window.API_BASE || '';` 移到 `<script>` 顶部（line 185 之前）。

#### P1-E app.py 单文件 1109 行，职责过载（上轮延续）

- **影响范围**：可维护性
- **代码位置**：`/workspace/src/hermes_kb/app.py`（全文 1112 行）
- **问题描述**：所有端点（health/documents/ask/history/feedback/seed/auth/age-gate/lab/UGC/variants/sync）集中在单文件，配合 ~20 处 lazy import。应拆分为 FastAPI APIRouter（如 `routers/documents.py`、`routers/lab.py`、`routers/auth.py`）。

#### P1-F 无数据库迁移脚本（上轮 P2-5 升级）

- **影响范围**：生产环境 schema 管理
- **代码位置**：`/workspace/src/hermes_kb/database.py:56` `SQLModel.metadata.create_all(eng)`
- **问题描述**：依赖启动期 `create_all` 建表，无 alembic 迁移。schema 变更（如加列、改约束）在生产环境无法可控执行。M4.3 新增 RecipeVariant 表的 FK 约束变更，若无迁移脚本，已有数据库不会自动加 FK。

---

### P2 建议项

| # | 位置 | 问题 |
|---|------|------|
| P2-1 | `src/hermes_kb/daily_recipe.py:93,101` | magic number 0.6/0.3/0.1 权重硬编码，应集中到 Settings 或常量 |
| P2-2 | `tests/test_kb/test_lab.py` + `test_lab_ops.py` | `seeded_recipes` 与 `seeded_recipes_ops` fixture 重复（上轮 P2-3 延续） |
| P2-3 | `src/hermes_kb/recipe_crud.py:117` | reject reason 存到 `source_path` 字段（`f"reject_reason: {reason}"`），字段语义复用 hack |
| P2-4 | `src/hermes_kb/thecocktaildb_sync.py:175` | `API_KEY = "1"` 硬编码测试 key，应环境变量化 |
| P2-5 | `web/src/` | 无 Loading 骨架屏（上轮 P2-6 延续） |

---

## 三、5 维度详细评分依据

### 1. 架构完整性 — 16/20（上轮 15，+1）

**加分项**：
- RecipeVariant FK CASCADE 完整修复（`models.py:171-178`），双向级联测试覆盖（`test_lab_ugc.py:323-375`）
- config 线程安全：`lru_cache` 单例 + `Lock` 保护 override/reset（`config.py:149-185`）
- `database.py:44-48` 每连接 `PRAGMA foreign_keys=ON` 事件监听器，确保连接池复用也生效
- `chunk_vec` 表有 `REFERENCES document(doc_id) ON DELETE CASCADE`（`database.py:102`）

**扣分项**：
- `app.py` 1112 行单文件，~20 处 lazy import（P1-6 保留），未拆分 APIRouter（-2）
- 无 DB 迁移脚本，依赖 `create_all`（-1）
- 向量检索无 ANN 索引（-1）

### 2. 代码质量 — 16/20（上轮 15，+1）

**加分项**：
- `_env_bool` 严格化：非识别值 `raise ValueError`（`config.py:44-47`）
- CORS `allow_credentials` 动态判断（`app.py:206`）
- `IngredientSubstitute` UniqueConstraint + IntegrityError 兜底（`models.py:148-150` + `substitutes.py:117-121`）
- 3 个外部同步器异常类型化：`(httpx.HTTPError, ValueError, OSError)` + `_logger.warning`
- JWT 用 `hmac.compare_digest` 常量时间比较（`app.py:104`）
- 全局异常处理 `correlation_id` 可追溯（`app.py:226-239`）

**扣分项**：
- `retrieval.py` 6 处 `except Exception` 静默吞错未修（-2，P1-8 未完整修复）
- magic number 散落（daily_recipe 权重、COOKIE_TTL_DAYS 等）（-1）
- reject_reason 复用 source_path 字段（-1）

### 3. 测试质量 — 14/20（上轮 13，+1）

**加分项**：
- 后端 255 测试（+9），覆盖 FK 级联（含 RecipeVariant 双向）、config 安全、向量检索、流式泄露、UGC 生命周期、变体关联
- 前端 vitest 框架建立 + 4 冒烟测试（从 0 到 1）
- ErrorBoundary 测试质量高（3 用例：正常透传/捕获错误/错误详情）
- `conftest.py` autouse `tmp_db` fixture 确保测试隔离

**扣分项**：
- 前端仅 4 个冒烟测试，api.ts SSE 解析 + ChatPanel 四分支未覆盖（-3，P0-1 修复建议未完整落地）
- retrieval.py 异常处理无测试（-1）
- fixture 重复（seeded_recipes / seeded_recipes_ops）（-1）
- 无 IngredientSubstitute 并发写入测试（-1）

### 4. 功能完整性 — 17/20（上轮 17，不变）

**维持分项**：
- M0-M4.3 全里程碑落地：导入→分片→FTS5+向量混合检索→RRF 融合→RAG 生成→UGC 状态机→审核→变体
- 三数据源同步（TheCocktailDB 全量字母遍历 + IBA 金标准 + bar-assistant 替代）
- 三层替代关系（L1 预置 40+ + L2 用户自定义 + L3 外部同步）
- RAG 安全：越狱检测 + 输出泄露滑动窗口 + 低置信度反馈
- daily_recipe UTC 修正（P1-2）提升跨时区正确性

**扣分项**：
- 向量检索无 ANN 索引，全表扫描 + Python 余弦（-2，P0-3）
- 超限静默截断，仅 warning 不返回 truncated 标志（-1）

### 5. 前端/产品体验 — 14/20（上轮 12，+2）

**加分项**：
- ErrorBoundary 实现完整（`ErrorBoundary.tsx`：getDerivedStateFromError + componentDidCatch + role="alert" + 错误详情 + 重载按钮），main.tsx 包裹 App（+1）
- api.ts BASE 环境化（`import.meta.env.VITE_API_BASE || ""`）（+0.5）
- recipes.html / lab.html 接入 _nav.js（+0.5）
- SVG favicon + theme-color（web/index.html + _nav.js injectFavicon）
- 设计稿视觉识别度高：深酒红 + 暗金 + Cormorant Garamond 衬线杂志感，_tokens.css 系统化

**扣分项**：
- React 应用缺失 M3-M4 实验室/配方/UGC 功能，仅覆盖 chat/docs/tags（-3，P1-B）
- ChatPanel textarea 无 aria-label + animate-pulse 无 reduced-motion（-1，P1-C）
- lab.html API_BASE 时序 bug 导致"今日推荐"不显示（-1，P1-D）
- 无 Loading 骨架屏（-1）

---

## 四、与上轮对比总结

### 已修复且验证通过（10/13）

| 修复项 | 修复质量 |
|--------|---------|
| P0-2 RecipeVariant FK CASCADE | ⭐⭐⭐ 高质量（FK + 双向级联测试） |
| P1-1 recipes/lab _nav.js 接入 | ⭐⭐ 达标（但 lab.html 引入新 bug） |
| P1-2 daily_recipe UTC | ⭐⭐⭐ 高质量（统一 _today_utc） |
| P1-3 config 线程安全 | ⭐⭐ 达标（lru_cache + Lock） |
| P1-4 CORS 动态 credentials | ⭐⭐⭐ 高质量（互斥逻辑正确） |
| P1-5 UniqueConstraint + IntegrityError | ⭐⭐⭐ 高质量（DB + 应用双层） |
| P1-7 _env_bool 严格化 | ⭐⭐⭐ 高质量（显式枚举 + raise） |
| P1-10 api.ts BASE 环境化 | ⭐⭐⭐ 高质量（简洁有效） |
| P2 .env.example 补全 | ⭐⭐⭐ 完整 |
| P2 favicon + theme-color | ⭐⭐ 达标 |

### 部分修复（2/13）

| 修复项 | 已修部分 | 未修部分 |
|--------|---------|---------|
| P0-1 前端测试 | vitest 框架 + 4 冒烟 + ErrorBoundary 测试 | api.ts SSE/authHeaders/BASE 测试、ChatPanel 四分支测试 |
| P1-8 except Exception | 3 个外部同步器改为具体异常 + logging | retrieval.py 6 处静默吞错未动 |
| P1-9 ErrorBoundary + a11y | ErrorBoundary 完整实现 + 测试 | textarea aria-label、prefers-reduced-motion |

### 未修复（1/13 + 已知项）

| 修复项 | 状态 |
|--------|------|
| P0-3 向量 ANN 索引 | 已知项，未修复 |
| P1-6 lazy import | 已知项，保留 |

---

## 五、最终结论

### 总分：77/100 — 未达到 90+

本轮审查验证了 13 项修复中 10 项完整达标、2 项部分达标、1 项已知未修。后端 255 测试 + 前端 4 测试全部通过，工程基础扎实。但从 72 到 77 的 5 分提升，不足以跨越 90+ 门槛——**剩余 13 分差距集中在三类硬伤**：

#### 距离 90+ 的核心差距（13 分）

1. **前端测试深度不足（约 -4 分，测试质量 14→18）**
   - 当前 4 个冒烟测试仅验证"不崩溃"，未覆盖 SSE 流式解析、认证注入、ChatPanel 事件分支等核心交互逻辑。
   - 上轮 P0-1 修复建议明确要求 api.ts + ChatPanel 测试，**未完整落地**。
   - 这是 P0-1 从"框架已建"到"测试充分"的最后一公里。

2. **React 应用功能覆盖不全（约 -4 分，前端体验 14→18）**
   - React 应用仅覆盖 M0-M2（chat/docs/tags），M3-M4 实验室/配方/UGC 功能仅存于设计稿。
   - 后端 ~15 个 `/api/lab/*` 端点无 React 前端对接。
   - 叠加 a11y 不完整（textarea 无 aria-label、无 reduced-motion）、lab.html API_BASE bug。

3. **向量检索扩展性瓶颈（约 -3 分，功能完整性 17→18 + 架构 16→17）**
   - P0-3 未修：全表扫描 + Python 余弦 + 50000 静默截断。
   - 知识库规模一旦超限，性能塌方且数据丢失。

4. **架构与代码细节（约 -2 分）**
   - app.py 1112 行单文件未拆分（P1-E）
   - retrieval.py 6 处静默吞错未修（P1-A）
   - 无 DB 迁移脚本（P1-F）

### 达到 90+ 的最关键 2 个修复项

若资源有限只能修 2 项，优先级如下：

1. **前端测试补齐 api.ts + ChatPanel 单测（+3-4 分）**
   - 为 `api.ts:187-226` askStream SSE 解析写单测（mock fetch ReadableStream，验证 buffer 分行 + data: 前缀 + JSON.parse）
   - 为 `ChatPanel.tsx:52-97` 四分支写单测（mock api.askStream，验证 meta/delta/done/error 状态更新）
   - 预计可将测试质量从 14 提升到 17-18

2. **React 应用补齐实验室功能（+3-4 分）**
   - 在 App.tsx 增加 "lab" tab，对接 `/api/lab/match`、`/api/lab/daily`、`/api/lab/recipes` 等端点
   - 复用现有设计稿（lab.html / recipes.html）的交互逻辑与视觉风格
   - 预计可将前端体验从 14 提升到 17-18

完成这两项后，预计总分可达 83-85 分。若再补向量 ANN（sqlite-vec）+ retrieval.py 异常日志，可达 88-90 分区间。

---

*本报告由 D2 对抗式终评审查代理生成，仅做研究与审查，未修改任何源码文件。所有结论均基于实际 Read 文件 + 实跑测试验证。*

# Hermes KB 鸡尾酒知识库 — D2 对抗式质量审查报告

- **审查日期**：2026-07-22
- **审查代理**：D2 对抗式审查（只读审查，未修改任何源码）
- **审查范围**：M0 MVP / M1 RAG / M2 前端重设计 / M3 鸡尾酒实验室 / M4.1-M4.3 运营与治理
- **代码基线**：`/workspace/src/hermes_kb/` + `/workspace/web/src/` + `/workspace/design/mockup/` + `/workspace/tests/test_kb/`
- **对比基线**：`docs/superpowers/reviews/2026-07-22-adversarial-review.md`（首版，64/100）
- **审查态度**：客观、批判性，找出阻碍质量分达到 90+/100 的真实差距

---

## 摘要

### 评分总览

| 维度 | 满分 | 得分 | 评价 |
|------|------|------|------|
| 架构完整性 | 20 | 15 | 分层清晰、Provider 抽象扎实；但 `app.py` 1109 行过载、20+ 处 lazy import、`RecipeVariant` 缺 FK、无 DB 迁移 |
| 代码质量 | 20 | 15 | 类型标注较全、`correlation_id` 可追溯；但多处 `except Exception` 静默吞错、CORS 配置错误、`_env_bool` 解析不一致、magic number 散落 |
| 测试质量 | 20 | 13 | 后端 246 用例覆盖扎实；但**前端零测试零框架**是硬伤，fixture 重复、并发/跨日路径未覆盖 |
| 功能完整性 | 20 | 17 | M0-M4.3 全里程碑落地，RAG 全链路 + UGC 状态机 + 三层替代 + 外部同步降级；但向量检索无 ANN 索引、`daily_recipe` 跨时区 |
| 前端/产品体验 | 20 | 12 | React 应用功能完整、SSE 流式 UI；但 `recipes.html` 未接入 `_nav.js`、前端零测试、无 Error Boundary、a11y 缺失、API BASE 硬编码 |
| **总分** | **100** | **72** | **较首版 64 分提升 8 分（6 个 P0 已修复），距 90+ 仍有 18 分差距** |

### 差距统计

| 严重等级 | 数量 | 说明 |
|---------|------|------|
| P0 严重（阻碍 90+） | 3 | 必须修复才能进入 90+ 区间 |
| P1 重要（应修） | 10 | 影响生产质量与可维护性 |
| P2 建议（可快速修复） | 7 | 低成本优化项 |
| **合计** | **20** | |

### 整体观感

相比首版（64/100，6 个 P0），本轮代码完成了一轮扎实的硬伤修复：JWT 默认密钥校验、异常 detail 脱敏、向量 LIMIT 配置化、SSE 滑动窗口泄露检测、年龄门 HMAC 签名 cookie、FK 级联 + `PRAGMA foreign_keys=ON`——这 6 个 P0 全部落地，且多数附带专项测试（`test_config_security`、`test_fk_cascade`、`test_stream_leak`、`test_age_gate`）。后端测试规模从首版的"只覆盖 happy path"扩展到 246 用例，覆盖错误处理、级联删除、流式泄露、向量检索、配方匹配优化等专项，工程素养明显提升。

但距离 90+ 仍有 18 分差距，核心瓶颈集中在三点：**前端零测试零框架**（一整个用户交互层无自动化回归保护）、**向量检索无 ANN 索引**（全表扫描 + Python 余弦，扩展性天花板低且仍有静默截断）、**架构遗留**（`app.py` 单文件 1109 行、20+ 处 lazy import 掩盖依赖、`RecipeVariant` 漏 FK 级联）。此外 CORS 配置错误、`_SETTINGS` 线程安全、`daily_recipe` 跨时区等 P1 残留需逐一收口。

---

## P0 严重问题（阻碍质量分达到 90+）

### P0-1 前端零测试框架，React 组件无任何自动化回归保护

- **影响范围**：`web/` 整个前端层，所有用户交互回归只能靠手动点击发现
- **代码位置**：
  - `/workspace/web/package.json:6-10`：`scripts` 只有 `dev` / `build` / `preview`，无 `test`
  - `devDependencies` 无 `vitest` / `jest` / `@testing-library/react` / `playwright` / `msw`
  - `/workspace/web/src/`：无 `*.test.tsx` / `*.spec.ts` 文件
- **问题描述**：前端是用户直接交互层，包含 SSE 流式解析（`ChatPanel.tsx` 的 `evt.type` 分支）、认证 token 注入（`api.ts:authHeaders`）、年龄门状态、文档跳转、取消请求（`AbortController`）等复杂逻辑。这些全部无测试覆盖。任何重构（如调整 SSE 事件结构、改 API BASE、调整 AgeGate 状态机）都可能在不知情下破坏用户体验。后端有 246 个测试，前端 0 个——这种不对称在质量分评估中是严重扣分项。
- **修复建议**：
  1. 引入 `vitest` + `@testing-library/react` + `jsdom`，加 `test` 脚本。
  2. 优先为 `api.ts`（SSE 解析、authHeaders、BASE 处理）和 `ChatPanel.tsx`（meta/delta/done/error 四分支）写单测。
  3. 用 `msw` mock 后端，覆盖种子导入、问答流式、错误提示路径。
  4. 在 CI（Dockerfile 或 GitHub Actions）中加 `npm run test`，与后端 `pytest` 同等门禁。

---

### P0-2 `RecipeVariant` 无 FK 级联，删除配方残留孤儿变体关联

- **影响范围**：M4.3 配方变体功能的数据一致性
- **代码位置**：`/workspace/src/hermes_kb/models.py:163-170`
  ```python
  class RecipeVariant(SQLModel, table=True):
      base_doc_id: str = Field(index=True, max_length=64)   # 无 ForeignKey
      variant_doc_id: str = Field(index=True, max_length=64) # 无 ForeignKey
  ```
- **问题描述**：首版 P0-6 已修复 `Chunk` / `DocumentTag` / `RecipeStats` 的 FK 级联（均加了 `ForeignKey("document.doc_id", ondelete="CASCADE")`），但 `RecipeVariant` 的两个字段只有 `index=True`，**没有 `ForeignKey` 约束、没有 `ondelete="CASCADE"`**。删除一个配方文档后，指向它的变体关联记录会残留：
  1. `recipe_variants.get_variants(base_doc_id)` 会返回 `variant_doc_id` 指向已删除文档的孤儿记录。
  2. 前端"查看变体"点击后 404。
  3. 这是 P0-6 修复不完整的直接体现——级联策略遗漏了 M4.3 新增表。
- **修复建议**：
  1. 给 `base_doc_id` 和 `variant_doc_id` 加 `sa_column=Column(..., ForeignKey("document.doc_id", ondelete="CASCADE"), index=True)`。
  2. 补充测试：删除 base 配方后断言 `RecipeVariant` 记录被级联清理（参照 `test_fk_cascade.py` 现有模式）。
  3. 审查 `MissingIngredientStats`（以 `canonical` 为主键，非 doc_id，无需 FK）是否需保留，确认无其他遗漏表。

---

### P0-3 向量检索无 ANN 索引，全表扫描 + Python 余弦，超限仍静默截断

- **影响范围**：所有问答检索路径（`/api/ask`、`/api/ask/stream`）的性能与扩展性
- **代码位置**：`/workspace/src/hermes_kb/retrieval.py:180-214`
  ```python
  rows = conn.execute(sa_text(
      "SELECT chunk_rowid, doc_id, vec FROM chunk_vec LIMIT :lim"
  ), {"lim": scan_limit}).fetchall()
  ...
  for row in rows:
      vec = json.loads(row[2])   # 每行 JSON 反序列化
      sim = _cosine(qvec, vec)   # 纯 Python 余弦
  ```
- **问题描述**：首版 P0-3 把硬编码 `LIMIT 10000` 改为 `vector_scan_limit`（默认 50000）并加了超限告警，元数据查询的 N+1 也已用批量 `IN` 消除——这些是实打实的改进。但**根本问题未解决**：
  1. 仍是全表扫描：每次问答把全部向量从 SQLite 拉到 Python 内存，逐条 `json.loads` + O(D) 余弦。5 万条 × 256 维 = 12.5MB JSON + 1280 万次浮点乘法，p99 延迟会从毫秒级跳到秒级。
  2. 仍是静默截断：`if len(rows) >= scan_limit` 只是 `logging.warning`，**仍然只返回前 50000 条**——超过的知识永远进不了检索结果，只是把阈值从 1 万提到 5 万，本质未变。
  3. 无 ANN 索引（sqlite-vec / faiss / hnswlib），扩展性天花板锁死在"单机内存 + Python 循环"。
- **修复建议**：
  1. 引入 `sqlite-vec`（纯 SQLite 扩展，与现有架构契合）做 `vec0` 虚拟表 ANN 检索，替换 Python 余弦循环。
  2. 过渡期至少按 `doc_id` / `category` 预过滤后再扫描，缩小候选集。
  3. 超限时改为"分页扫描全量 + 取 top-k"而非截断，或明确在 API 响应中返回 `truncated: true` 让前端可见。

---

## P1 重要问题（应该修复）

### P1-1 `recipes.html` 与 `lab.html` 未接入 `_nav.js` 共享导航，体验不一致

- **影响范围**：mockup 导航一致性
- **代码位置**：
  - `/workspace/design/mockup/`：15 个 HTML 文件中 13 个引用 `_nav.js`，唯独 `recipes.html` 与 `lab.html` 手写 nav
  - `recipes.html` grep `_nav.js` 无匹配
- **问题描述**：`_nav.js` 是共享导航注入 + chunk 高亮逻辑，13 个页面已统一接入。`recipes.html`（配方治理页）和 `lab.html`（调酒实验室）手写导航，导致：导航项不同步、高亮逻辑重复实现、新增页面需改两处。这是 M3 新增页面时未遵循 M2 建立的约定。
- **修复建议**：将 `recipes.html` 和 `lab.html` 改为 `<script src="_nav.js"></script>` 注入，删除手写 nav，与其他 13 页保持一致。

---

### P1-2 `daily_recipe` 使用 `date.today()` 而非 UTC，跨时区部署行为不一致 + 测试 flaky

- **影响范围**：每日推荐稳定性、测试可重复性
- **代码位置**：`/workspace/src/hermes_kb/daily_recipe.py:26, 77`
  ```python
  month = date.today().month              # 服务器本地时区
  today_seed = int(date.today().toordinal())
  ```
- **问题描述**：
  1. `date.today()` 用服务器本地时区，UTC 部署（Docker 默认）和北京时间部署会在不同时刻"换日"，每日推荐在跨时区部署下不可预测。
  2. 测试 `test_daily_recipe_stable_per_day` 依赖"今天不变"，若测试在 UTC 0 点附近运行会跨日 flaky。
  3. 无法 mock 时间，无法测试"明天/昨天"的推荐切换。
- **修复建议**：改为 `datetime.now(timezone.utc).date()` 或允许通过 `KB_TZ` 环境变量指定时区；测试中注入 `now_fn` 或用 `freezegun` 冻结时间。

---

### P1-3 `_SETTINGS` 全局单例 + `reset_settings` 线程不安全

- **影响范围**：测试并发、未来多 worker 部署
- **代码位置**：`/workspace/src/hermes_kb/config.py:136-149`
- **问题描述**：`_SETTINGS` 是模块级全局，`reset_settings` 直接赋 `None`，`override_settings` 直接替换。若测试并发跑（pytest-xdist）或生产用线程池，正在处理中的请求可能拿到 `None` 引发 `AttributeError`，或读到部分覆盖的配置。
- **修复建议**：用 `contextvars.ContextVar` 替代全局变量，或把 `settings` 作为 FastAPI 依赖注入，避免模块级可变状态。

---

### P1-4 CORS 配置 `allow_origins=["*"]` + `allow_credentials=True` 形同虚设

- **影响范围**：跨域安全与可用性
- **代码位置**：`/workspace/src/hermes_kb/app.py:201-207` + `config.py:45`
- **问题描述**：浏览器 CORS 规范明确禁止 `Access-Control-Allow-Origin: *` 与 `Access-Control-Allow-Credentials: true` 同时出现——浏览器会直接拒绝响应。这意味着"配置了 CORS 但实际不工作"。默认 `KB_CORS=["*"]`，生产部署若不改，跨域请求全部失败。由于前端是 StaticFiles 同源挂载，本不需要 CORS，这个配置纯属噪声且有误导性。
- **修复建议**：默认 `cors_origins=[]`（不开启跨域）；若启用则必须为具体 origin 列表，且在 `create_app` 中校验 `allow_credentials` 与 `*` 互斥，启动期报错。

---

### P1-5 `IngredientSubstitute` 无 `(canonical, substitute)` 唯一约束，并发写入会重复

- **影响范围**：用户自定义替代关系
- **代码位置**：`/workspace/src/hermes_kb/models.py:145-152`（无 `__table_args__`）+ `substitutes.py` 的 `add_user_substitute`（select-then-insert）
- **问题描述**：两个并发请求同时添加 `(君度, 自制橙皮酒)`，都会 `select` 返回空、都会 `insert`，最终表里两条相同记录。这是经典 TOCTOU race。
- **修复建议**：加 `UniqueConstraint("canonical", "substitute")`，并用 `INSERT ON CONFLICT DO NOTHING` 替代 select-then-insert。

---

### P1-6 `app.py` 20+ 处函数内 lazy import，掩盖循环依赖

- **影响范围**：可维护性、首次请求延迟、重构风险
- **代码位置**：`/workspace/src/hermes_kb/app.py` 第 712、837-840、868、878、889、897、905、917、934-940、958、969、978、990、1010、1026、1036、1046、1057、1065-1066 行等
- **问题描述**：每个端点函数内 `from hermes_kb.xxx import yyy`，共 20+ 处。虽然 Python 有 `sys.modules` 缓存，但仍掩盖了真实的依赖关系（如 `recipe_match → missing_stats → models`），重构时极易踩坑，且首次请求有模块查找开销。
- **修复建议**：把 lazy import 提到模块顶部；若存在真实循环依赖，重构模块边界（如把 `match_recipes` 拆为核心算法 + 统计写入装饰器）。

---

### P1-7 `_env_bool` 解析不一致，非识别值静默为 False

- **影响范围**：所有布尔配置项
- **代码位置**：`/workspace/src/hermes_kb/config.py:31-35`
- **问题描述**：`v.strip().lower() in ("1","true","yes","on")` 为 True，其他一律 False。用户写 `KB_AUTH_ENABLED="disable"` 或 `KB_AGE_GATE="off"` 都静默为 False——用户可能误以为 "disable" 是关闭，实际是被当作未识别值关闭。`"False"` 和 `"false"` 结果对但规则隐晦。
- **修复建议**：显式枚举 `("1","true","yes","on")` 为 True、`("0","false","no","off","")` 为 False，其他值 `raise ValueError` 而非静默 False。

---

### P1-8 多处 `except Exception` 静默吞错，故障不可见

- **影响范围**：可观测性、调试难度
- **代码位置**：
  - `retrieval.py:196-197, 233-234`：向量检索异常返回空列表 / `pass`
  - `recipe_match.py` 多处统计写入 `except Exception: pass`
  - `rag.py` 部分降级路径
- **问题描述**：`except Exception: pass` 或 `return []` 把所有异常吞掉，既不记日志也不上报。向量检索静默返回空 = 用户以为"知识库没有相关内容"，实际是 DB 报错。统计写入静默失败 = 看板指标失真但无人知晓。
- **修复建议**：至少 `logging.exception(...)` 记录，区分"预期降级"（info）与"意外错误"（warning/error）；关键路径返回结构化错误而非空值。

---

### P1-9 前端无 Error Boundary，无 a11y 支持

- **影响范围**：前端健壮性与可访问性
- **代码位置**：`/workspace/web/src/App.tsx` 及所有组件
- **问题描述**：
  1. 无 React Error Boundary，任一子组件渲染抛错即整页白屏。
  2. `ChatPanel.tsx` 的 `<textarea>` / `<button>` 无 `aria-label`，键盘 Tab 焦点顺序未显式管理，屏幕阅读器无法识别。
  3. 流式生成中的光标动画（`animate-pulse`）无 `prefers-reduced-motion` 适配。
- **修复建议**：在 `App.tsx` 外层包 `ErrorBoundary` 组件；为交互元素加 `aria-label`；用 `@media (prefers-reduced-motion)` 关闭动画。

---

### P1-10 `web/src/api.ts` BASE 硬编码为空串，前端无法独立部署到不同域名

- **影响范围**：前端部署灵活性
- **代码位置**：`/workspace/web/src/api.ts:16` `const BASE = "";`
- **问题描述**：`BASE = ""` 假设前端与后端同源。若前端独立部署到 CDN 或不同域名（如 `https://kb.example.com` 调 `https://api.example.com`），必须改源码重新构建。无 `VITE_API_BASE` 环境变量注入。
- **修复建议**：改为 `const BASE = import.meta.env.VITE_API_BASE ?? "";`，`.env.example` 补充 `VITE_API_BASE` 文档。

---

## 可快速修复差距（P2 建议）

| # | 位置 | 问题 | 修复建议 |
|---|------|------|----------|
| P2-1 | `pyproject.toml` | `requires-python = ">=3.10"` 与项目说明的 Python 3.14 不一致 | 校准为实际最低支持版本（如 `>=3.11`），或在 README 注明 3.14 为推荐版本 |
| P2-2 | `.env.example` | 未包含 `KB_*` 系列变量文档（`KB_JWT_SECRET`、`KB_VECTOR_SCAN_LIMIT`、`KB_DEBUG` 等） | 补充 KB_* 段落，标注必填项（尤其 `KB_JWT_SECRET` 在 `KB_AUTH_ENABLED=true` 时必填） |
| P2-3 | `tests/test_kb/` | `seeded_recipes`（test_lab.py）与 `seeded_recipes_ops`（test_lab_ops.py）重复 | 提到 `conftest.py` 统一一份 |
| P2-4 | 多处 | magic number 散落：`COOKIE_TTL_DAYS=30`、`query_max_length=500`、滑窗阈值等 | 集中到 `Settings` 或常量模块，附注释说明取值依据 |
| P2-5 | `database.py` | 无数据库迁移脚本，依赖 `SQLModel.metadata.create_all` 启动期建表 | 引入 `alembic` 做 schema 版本管理，避免生产环境 schema 变更不可控 |
| P2-6 | `web/src/` | 无 Loading 骨架屏，文档列表/问答加载时无视觉反馈 | 加 `skeleton` 占位组件，提升感知性能 |
| P2-7 | `web/` | 无 favicon / PWA manifest | 补充 favicon 与 manifest.json，支持移动端添加到主屏幕 |

---

## 结论

### 进步确认（相对首版 64/100）

首版报告的 6 个 P0 **全部已修复**，且修复质量较高——多数附带专项测试（`test_config_security`、`test_fk_cascade`、`test_stream_leak`、`test_age_gate`、`test_error_handling`、`test_vector_retrieval`），说明修复不是"打补丁"而是"修+测"闭环。后端测试从"happy path only"扩展到 246 用例，覆盖错误处理、级联删除、流式泄露、向量检索优化等专项。`recipe_match.py` 的 `batch_first_chunks`（A3-2 消除 N+1）和 `_pending_stats`（A3-3 异步统计）是实打实的性能改进。这些进步使总分从 64 提升到 **72/100**。

### 距离 90+ 的差距（18 分）

72 → 90+ 的 18 分差距集中在三类：

1. **前端质量空白（约 6-7 分）**：前端零测试零框架是最大短板。一个有 SSE 流式、认证、状态管理的 React 应用没有任何自动化测试，在质量分评估中是硬伤。叠加无 Error Boundary、a11y 缺失、API BASE 硬编码、mockup 导航不一致，前端维度只能给 12/20。

2. **扩展性瓶颈（约 4-5 分）**：向量检索无 ANN 索引、全表扫描 + Python 余弦、超限静默截断——这是"能跑但跑不远"的架构债。知识库规模一旦超过单机内存上限，性能塌方且数据丢失。这是阻碍功能完整性拿到 18+ 的主因。

3. **架构与代码细节（约 7-8 分）**：`app.py` 单文件 1109 行、20+ 处 lazy import、`RecipeVariant` 漏 FK、CORS 配置错误、`_SETTINGS` 线程不安全、`_env_bool` 解析不一致、`except Exception` 静默吞错——这些单独看都不致命，但累积起来让架构和代码质量维度各丢 5 分。

### 达到 90+ 的关键路径

1. **前端测试从 0 到 1**（+4-5 分）：引入 vitest + testing-library，覆盖 api.ts 与 ChatPanel，CI 门禁对齐后端。
2. **向量检索引入 ANN**（+2-3 分）：sqlite-vec 替换 Python 余弦，解除扩展性天花板。
3. **收口 P0-2 + P1-4/5/6/8**（+3-4 分）：补 RecipeVariant FK、修 CORS、加唯一约束、消除 lazy import、异常记日志。
4. **前端体验补齐**（+2 分）：Error Boundary + a11y + API BASE 环境化 + mockup 导航统一。
5. **架构整理**（+1-2 分）：拆分 app.py、引入迁移脚本、统一 fixture。

完成上述五步，预计可达 88-92 分区间，跨入 90+ 门槛。

---

*本报告由 D2 对抗式审查代理生成，仅做研究与审查，未修改任何源码文件。*

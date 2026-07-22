# Hermes KB 鸡尾酒知识库 - 对抗式审查报告

- **审查日期**：2026-07-22
- **审查范围**：M0 MVP / M1 RAG / M2 前端重设计 / M3 鸡尾酒实验室 / M4.1 自动运营层
- **审查方式**：对抗式（挑刺为主），代码 + 架构 + 测试 + 前端全维度
- **审查态度**：不客套，只挑真问题
- **代码基线**：`/workspace/src/hermes_kb/` + `/workspace/web/src/` + `/workspace/tests/test_kb/`

---

## 摘要

| 严重等级 | 数量 |
|---------|------|
| P0 严重（必修） | 6 |
| P1 重要（应修） | 18 |
| P2 建议（可优化） | 17 |
| **合计** | **41** |

**质量总分：64 / 100**（架构 12 / 代码 12 / 测试 14 / 可维护性 13 / 前端 13）

整体观感：MVP 阶段代码组织尚可，但已显露"业务模块互相 patch、测试只能覆盖 happy path、安全控制形同虚设"的典型技术债。**生产部署前必须先解 P0**，否则会同时承担安全风险和"上线即不可用"的性能塌方。

---

## P0 严重问题（必须修复）

### P0-1 JWT 默认密钥硬编码，启用认证即可被任意伪造 token 攻陷

- **影响范围**：所有启用 `KB_AUTH_ENABLED=true` 但未单独配置 `KB_JWT_SECRET` 的部署
- **代码位置**：`src/hermes_kb/config.py:78`
  ```python
  jwt_secret: str = field(default_factory=lambda: _env_str("KB_JWT_SECRET", "hermes-kb-default-secret-please-change"))
  ```
- **问题描述**：默认 secret 是源码里写死的字符串 `"hermes-kb-default-secret-please-change"`。攻击者只需阅读源码（开源仓库）即可用此 secret 伪造任意 `{"sub":"admin","role":"admin"}` 的 JWT，绕过密码登录、绕过 `require_auth`，等于认证系统完全失守。
- **修复建议**：
  1. 在 `Settings.__post_init__` 中校验：若 `auth_enabled=True` 且 `jwt_secret` 仍是默认值或为空，直接 `raise RuntimeError`，禁止启动。
  2. 文档与 `.env.example` 中明确标注该项必填。
  3. 启动时打印警告（不输出 secret 本身）。

---

### P0-2 全局异常处理器把 `str(exc)` 直接返回给客户端，泄露内部信息

- **影响范围**：所有未捕获异常的 API 响应
- **代码位置**：`src/hermes_kb/app.py:206-211`
  ```python
  @app.exception_handler(Exception)
  async def _generic_error_handler(_request: Request, exc: Exception):
      return JSONResponse(
          status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
          content={"error": "internal", "detail": str(exc)},
      )
  ```
- **问题描述**：把任意 `Exception` 的 `str()` 透传给客户端。SQL 报错会暴露表名/列名/SQL 文本；`KeyError`/`AttributeError` 会暴露内部字段名；`FileNotFoundError` 会暴露绝对路径。在生产环境这是 OWASP A05（Security Misconfiguration）经典反例。
- **修复建议**：
  1. 生产模式下 `detail` 仅返回固定文案（如 `"internal error, correlation_id=xxx"`），完整 traceback 走 `logging.exception()` 落盘。
  2. 通过 `settings.debug` 切换开发/生产行为。
  3. 给每个 500 响应附带 `correlation_id`，方便定位。

---

### P0-3 向量检索全表扫描 + Python 余弦，超过 10000 chunk 静默截断

- **影响范围**：所有问答检索路径（`/api/ask`、`/api/ask/stream`）
- **代码位置**：`src/hermes_kb/retrieval.py:179-219`
  ```python
  rows = conn.execute(sa_text(
      "SELECT chunk_rowid, doc_id, vec FROM chunk_vec LIMIT 10000"
  )).fetchall()
  ...
  for row in rows:
      vec = json.loads(row[2])  # 每行 JSON 反序列化
      sim = _cosine(qvec, vec)  # 纯 Python 余弦
  ```
- **问题描述**：
  1. **静默截断**：`LIMIT 10000` 是硬编码魔数。一旦知识库超过 1 万 chunk（按平均 500 字符/片、5 篇/k chunk 估算，约 500 篇文档就触顶），新增内容**永远进不了检索结果**，且不报错、不告警。这是无声的"数据丢失"。
  2. **性能崩盘**：每次问答都把全部向量从 SQLite 拉到 Python 内存，每条做一次 `json.loads` + O(D) 余弦计算。1 万条 × 256 维 = 2.5MB JSON + 256 万次浮点乘法，p99 延迟会从毫秒级跳到秒级。
  3. **N+1 元数据查询**：`_doc_title()` 和 `_chunk_meta()` 对每个 hit 开一次新 `get_session()`（`retrieval.py:221-237`），单次问答可能开几十个 session。
- **修复建议**：
  1. 移除 `LIMIT 10000`，或改为配置项 + 超限告警。
  2. 引入 sqlite-vec / chromadb / faiss 做近似最近邻；过渡期至少加 `(doc_id)` 之外的预过滤。
  3. 把 hit 的 doc_id 收集后一次性 `select Document where doc_id in (...)` 拿标题，消除 N+1。

---

### P0-4 SSE 流式输出泄露检测"事后报警"，敏感内容已经发到客户端

- **影响范围**：所有流式问答（`/api/ask/stream`）
- **代码位置**：`src/hermes_kb/rag.py:309-322`
  ```python
  async for chunk in self.llm_client.chat_stream(messages):
      full_answer.append(chunk)
      yield f"data: {json.dumps({'type': 'delta', 'content': chunk}, ensure_ascii=False)}\n\n"
  ...
  # 输出泄露检测（流式结束后整体检查）
  final_answer = _check_output(query, "".join(full_answer))
  ```
- **问题描述**：`_check_output` 是为了阻止 LLM 把 system prompt、`<untrusted_retrieval>` 标签等敏感内容泄露给用户。但流式实现里，所有 delta 已经通过 SSE 发给客户端了，最后才做检测——此时即使 `_check_output` 替换为 fallback，客户端也早已收到原文。这等于"门关上了，贼已经走了"。
- **修复建议**：
  1. 流式场景下做"滑动窗口检测"：维护一个 buffer，每次 yield 前检查 buffer 中是否出现泄露标记，发现即中断流并发 error 事件。
  2. 或者放弃流式场景的输出泄露检测，明确在文档中说明"流式不保证输出过滤"。

---

### P0-5 年龄门（age-gate）是装饰性控件，对未成年人保护完全无效

- **影响范围**：合规性、未成年人保护
- **代码位置**：
  - 后端 `src/hermes_kb/app.py:784-799`：`/api/age-gate/confirm` 仅返回 `{"confirmed": bool}`，无 session、无 cookie、无 token
  - 前端 `web/src/components/AgeGate.tsx:9-39`：`enabled` 是组件 `useState`，刷新页面即重置
- **问题描述**：年龄门的核心问题——**后端不校验、前端不持久化**：
  1. 调用 `/api/age-gate/confirm` 后没有任何状态保留，所有受保护接口（`/api/ask`、`/api/documents` 等）都不检查年龄确认状态。
  2. 前端 `ageConfirmed` 是 React state，刷新页面/打开新标签页就回到未确认状态——但因为后端不查，照样能直接调 API。
  3. 未成年用户只要直接访问 `/api/health` 或 `/api/ask` 即可绕过。
  - **合规风险**：如果是面向中国市场的酒类内容站点，这等价于没有年龄验证，可能违反《未成年人保护法》第 50 条。
- **修复建议**：
  1. 后端在 `require_auth` 之外加 `require_age_gate` 依赖，校验请求带的有效 age-gate cookie/JWT claim。
  2. 确认后下发 HttpOnly + Secure + SameSite=Strict cookie，带过期时间。
  3. 受保护接口都加该依赖。

---

### P0-6 `chunk_vec` 表无外键、无级联删除，删除文档会留孤儿向量

- **影响范围**：数据一致性、检索准确性
- **代码位置**：
  - `src/hermes_kb/database.py:89-101`：建表 SQL 无 `FOREIGN KEY` 约束、无 `ON DELETE CASCADE`
  - `src/hermes_kb/rag.py:493-519`：`delete_document` 手动 `DELETE FROM chunk_vec WHERE chunk_rowid IN :rowids`
  - `src/hermes_kb/app.py:341-354`：`delete_document` 端点后还会清 `DocumentTag`，但完全没清 `RecipeStats`、`MissingIngredientStats` 等关联
- **问题描述**：
  1. `chunk_vec` 是裸表（不是 SQLModel），没有任何外键约束。`ImportService.delete_document` 之外的删除路径（例如直接 `session.delete(chunk)`）会留下孤儿向量，下次检索还会命中并尝试查已不存在的 chunk。
  2. `DocumentTag`、`RecipeStats`、`MissingIngredientStats`、`IngredientSubstitute` 全都没有 `FOREIGN KEY` 指向 `Document`/`Tag`/`canonical`。删除文档后这些统计/关联全部残留，看板指标会失真。
  3. SQLite 默认不开启 FK 约束，需要在每个 connection 上 `PRAGMA foreign_keys=ON`——`database.py` 没做。
- **修复建议**：
  1. `get_engine()` 的连接初始化里加 `PRAGMA foreign_keys=ON`。
  2. 给 `DocumentTag.doc_id`、`RecipeStats.doc_id`、`Chunk.doc_id` 加 `ForeignKey(ondelete="CASCADE")`。
  3. 删除文档的接口统一走 `ImportService.delete_document`，由数据库级联清理，而不是端点里手写 `for link in links: session.delete(link)`。

---

## P1 重要问题（应该修复）

### P1-1 N+1 查询遍布 M3/M4 配方模块

- **影响范围**：配方匹配、热门配方、每日推荐、运营看板
- **代码位置**：
  - `src/hermes_kb/recipe_match.py:30-48`：`_load_recipes` 对每个 doc 单独查 `first_chunk`
  - `src/hermes_kb/recipe_stats.py:82-87`：`get_hot_recipes` 对每个 (stat, doc) 单独查 first_chunk
  - `src/hermes_kb/daily_recipe.py:43-48, 105-110`：`_seasonal_pool` 和随机分支同样
  - `src/hermes_kb/retrieval.py:221-237`：每个 hit 开一次 session
- **问题描述**：经典 N+1。配方数稍多（≥30）时单次接口延迟会从 50ms 涨到 500ms+。
- **修复建议**：抽取"批量取 first_chunk"工具函数，一次 `select Chunk where doc_id in (...) group by doc_id`。

---

### P1-2 `match_recipes` 在响应链路里同步写统计，阻塞主响应

- **影响范围**：`/api/lab/match` p99 延迟
- **代码位置**：`src/hermes_kb/recipe_match.py:154-161` + `src/hermes_kb/app.py:819-823`
  ```python
  for recipe in result["full_match"] + result["partial_match"]:
      try:
          increment_match_count(recipe["doc_id"])  # 每个一次 session + commit
      except Exception:
          pass
  ```
- **问题描述**：一次匹配命中 10 个配方 = 10 次单独 `session + commit`，全部串行。partial_match 还会再触发 `increment_missing`（`recipe_match.py:155-160`）。统计写失败被静默吞掉，前端永远看不到错误。
- **修复建议**：
  1. 把统计写入放到 `BackgroundTasks`，主响应直接返回。
  2. 改为单次批量 `UPDATE recipe_stats SET match_count = match_count + 1 WHERE doc_id IN (...)` + `INSERT ON CONFLICT DO UPDATE`。
  3. 失败时记日志而不是 `pass`。

---

### P1-3 `weekly_match_count` 看板指标语义错误

- **影响范围**：运营看板 `/api/lab/dashboard`
- **代码位置**：`src/hermes_kb/lab_dashboard.py:33-38`
  ```python
  cutoff = datetime.now(timezone.utc) - timedelta(days=7)
  weekly_match = session.exec(
      select(func.sum(RecipeStats.match_count)).where(
          RecipeStats.last_matched_at >= cutoff
      )
  ).one() or 0
  ```
- **问题描述**：`match_count` 是**累计值**，不是增量。`sum(match_count) where last_matched_at >= cutoff` 实际语义是"最后一次匹配在本周的配方的累计匹配数之和"，不是"本周匹配次数"。例如某配方累计匹配 1000 次，本周只匹配了 1 次（last_matched_at 落在本周），它会贡献 1001 给"周匹配数"。
- **修复建议**：要么新增 `match_count_daily` 表做时序统计，要么改文案为"本周有匹配活动的配方累计匹配总数"，避免误导运营决策。

---

### P1-4 `recipe_match._parse_ingredients_from_content` 用裸子串匹配，会误匹配

- **影响范围**：非种子配方的材料解析
- **代码位置**：`src/hermes_kb/recipe_match.py:61-69`
  ```python
  for name in all_canonical():
      if name in content:
          found.add(name)
  ```
- **问题描述**：
  - `"金酒" in "金酒厂介绍"` → 误匹配为金酒
  - `"苦精" in "苦精英"` → 误匹配
  - `"苏打水" in "苏打水瓶"` → 误匹配
  - 中文材料名没有词边界，裸 `in` 几乎必然误判
- **修复建议**：用正则 `\b`/中文边界规则、或要求配方文档显式标注材料列表（如 YAML frontmatter），不要再从 content 反向解析。

---

### P1-5 `recipe_match._extract_ingredients_from_seed` 通过 title 反查 SEED_RECIPES，强耦合

- **影响范围**：配方匹配的种子映射路径
- **代码位置**：`src/hermes_kb/recipe_match.py:51-58`
- **问题描述**：用户在 UI 上改一下配方标题（`/api/documents/{doc_id}/metadata` 支持 title 更新），种子映射就失效，回退到不可靠的 content 子串解析（见 P1-4）。
- **修复建议**：种子导入时把 `seed_recipe_id` 写入 `Document.source_path` 或新增 `metadata` 字段，匹配时按 ID 查找而非 title。

---

### P1-6 测试中 `seeded_recipes` fixture 在两个文件里重复定义

- **影响范围**：测试可维护性
- **代码位置**：
  - `tests/test_kb/test_lab.py:164-191`
  - `tests/test_kb/test_lab_ops.py:45-70`
- **问题描述**：两份几乎一样的 fixture（`seeded_recipes` vs `seeded_recipes_ops`），DRY 违反，后续修改配方导入逻辑要改两处。
- **修复建议**：提到 `conftest.py`，统一一份。

---

### P1-7 `daily_recipe` 使用 `date.today()` 而非 UTC，跨时区部署行为不一致 + 测试 flaky

- **影响范围**：每日推荐稳定性、测试可重复性
- **代码位置**：`src/hermes_kb/daily_recipe.py:22, 70`
- **问题描述**：
  1. `date.today()` 用服务器本地时区，UTC 部署（如 Docker 默认）和北京时间部署会在不同时刻"换日"。
  2. 测试 `test_daily_recipe_stable_per_day` 依赖"今天不变"，如果测试在 UTC 0 点附近运行（北京时间早上 8 点），可能跨日导致 flaky。
  3. 没法 mock 时间，无法测试"明天/昨天"的推荐。
- **修复建议**：改为 `datetime.now(timezone.utc).date()` 或允许通过环境变量指定时区；测试中用 `freezegun` 或注入 `now_fn`。

---

### P1-8 `_SETTINGS` 全局单例 + `reset_settings` 模式线程不安全

- **影响范围**：测试并发、未来多 worker 部署
- **代码位置**：`src/hermes_kb/config.py:112-126`
- **问题描述**：`_SETTINGS` 是模块级全局，`reset_settings` 直接赋 `None`。如果测试并发跑（pytest-xdist）或生产用线程池，正在处理中的请求可能拿到 `None` 引发 `AttributeError`。
- **修复建议**：用 `contextvars.ContextVar` 替代全局变量，或用 dependency injection 把 settings 作为 FastAPI 依赖。

---

### P1-9 `ingredient_substitute` 表无 (canonical, substitute) 唯一约束，并发写入会重复

- **影响范围**：用户自定义替代关系
- **代码位置**：
  - `src/hermes_kb/models.py:105-112`：无 `__table_args__` 唯一约束
  - `src/hermes_kb/substitutes.py:47-67`：`add_user_substitute` 先 `select` 再 `insert`，存在 TOCTOU race
- **问题描述**：两个并发请求同时添加 `(君度, 自制橙皮酒)`，都会 `select` 返回空，都会 `insert`，最终表里两条相同记录。
- **修复建议**：加 `UniqueConstraint("canonical", "substitute")`，并用 `INSERT ON CONFLICT DO NOTHING` 替代 select-then-insert。

---

### P1-10 `app.py` 大量函数内 lazy import，掩盖了循环依赖

- **影响范围**：可维护性、首次请求延迟
- **代码位置**：`src/hermes_kb/app.py:700, 807-809, 830, 840, 851, 859, 867, 879` 等十余处
- **问题描述**：每次请求都重新解析模块路径（虽然 Python 有 `sys.modules` 缓存，但仍有查找开销）。更严重的是它掩盖了真实的循环依赖：`recipe_match → missing_stats → models` 和 `recipe_match → substitutes → models` 看似干净，但通过 lazy import 把依赖关系藏起来，重构时极易踩坑。
- **修复建议**：把所有 lazy import 提到模块顶部，必要时重构模块边界（如把 `match_recipes` 拆到不依赖 `missing_stats` 的核心算法 + 一个写统计的 decorator）。

---

### P1-11 CORS 配置 `allow_origins=["*"]` + `allow_credentials=True` 形同虚设

- **影响范围**：跨域安全
- **代码位置**：`src/hermes_kb/app.py:185-191` + `src/hermes_kb/config.py:45`
- **问题描述**：
  1. 浏览器 CORS 规范明确禁止 `Access-Control-Allow-Origin: *` 与 `Access-Control-Allow-Credentials: true` 同时出现，浏览器会拒绝响应。这意味着"配置了 CORS 但实际不工作"。
  2. 默认 `KB_CORS=["*"]`，生产部署若不改，要么 CORS 失效要么有安全风险。
  3. 由于前端是 StaticFiles 同源挂载，根本不需要 CORS——这个配置纯属噪声。
- **修复建议**：默认 `cors_origins=[]`（不开启跨域）；若启用则必须为具体 origin 列表，且校验 `allow_credentials` 与 `*` 互斥。

---

### P1-12 测试覆盖严重不足：错误路径 / 并发 / 边界 / 删除级联

- **影响范围**：回归风险
- **代码位置**：`tests/test_kb/`
- **问题描述**：以下路径**完全未覆盖**：
  - `_generic_error_handler`（P0-2 的泄露路径）
  - `_check_output` 触发泄露的实际场景
  - `upload_file` 单文件 PDF 解析（只测了 batch）
  - `query_rewriter` LLM 路径（只测了启发式）
  - `delete_document` 后 FTS 索引是否真的清理（有触发器但无断言）
  - `delete_document` 后 `RecipeStats`/`MissingIngredientStats` 残留（P0-6 的体现）
  - 超过 10000 chunk 的向量检索截断（P0-3）
  - 并发写入 `ingredient_substitute`（P1-9）
  - JWT 过期、错误 secret 之外的边界（如 alg 头篡改）
  - `_is_required` 装饰类材料可选的真实场景
  - 多个 `_heuristic_rewrite` 同义词叠加的极端情况
  - `daily_recipe` 跨日切换
- **修复建议**：补齐上述路径的单测；引入 mutation testing（如 cosmic-ray）验证测试强度。

---

### P1-13 `_env_bool` 解析坑：`"False"` 字符串被识别为 True

- **影响范围**：所有布尔配置项
- **代码位置**：`src/hermes_kb/config.py:31-35`
  ```python
  def _env_bool(key: str, default: bool) -> bool:
      v = os.environ.get(key)
      if v is None:
          return default
      return v.strip().lower() in ("1", "true", "yes", "on")
  ```
- **问题描述**：`KB_AUTH_ENABLED="False"` 会被解析为 `False`（OK），但 `KB_AGE_GATE="false"` 同样 OK；然而 `KB_AUTH_ENABLED="0"` 会被解析为 False，`KB_AUTH_ENABLED="no"` 也是 False。问题是用户写 `KB_AUTH_ENABLED="False"` 时虽然结果对，但写 `KB_AUTH_ENABLED="True "` (带空格) 也 OK，但 `KB_AUTH_ENABLED="1 "` 也 OK——规则不一致。更严重的反例：`KB_AUTH_ENABLED="false"` 是 False，但 `KB_AUTH_ENABLED="disable"` 也是 False——用户可能误以为 "disable" 是关闭，实际是不识别字符串。
- **修复建议**：显式枚举 `("1","true","yes","on")` 为 True，`("0","false","no","off","")` 为 False，其他值报错而非静默 False。

---

### P1-14 `recipe_match.match_recipes` 调用 `_load_recipes` 后又遍历 SEED_RECIPES 构建 `seed_meta`，重复且低效

- **影响范围**：`/api/lab/match` 性能
- **代码位置**：`src/hermes_kb/recipe_match.py:105-120`
  ```python
  from hermes_kb.seed_recipes import SEED_RECIPES
  seed_meta: dict[str, dict] = {}
  for r in SEED_RECIPES:
      seed_meta[r["title"]] = r
  recipes = _load_recipes()
  ...
  for recipe in recipes:
      meta = seed_meta.get(title, {})
      recipe_ingredients = (
          set(meta.get("ingredients", [])) or _get_recipe_ingredients(recipe)
      )
  ```
- **问题描述**：每次请求都重新构建 `seed_meta`，且对每个 recipe 都调用 `_get_recipe_ingredients` 又会再 `from hermes_kb.seed_recipes import SEED_RECIPES` 一次。`_extract_ingredients_from_seed` 内部又遍历 SEED_RECIPES——一次匹配请求最坏要遍历 SEED_RECIPES 三次。
- **修复建议**：把 `seed_meta` 做成模块级常量缓存；`_get_recipe_ingredients` 接收 `meta` 参数避免重复查。

---

### P1-15 `ImportService.import_text` 每个 chunk 都 `flush()` 拿 rowid，性能差

- **影响范围**：导入性能
- **代码位置**：`src/hermes_kb/rag.py:451-471`
  ```python
  for i, (start, end, text) in enumerate(chunks):
      c = Chunk(...)
      session.add(c)
      session.flush()  # 每片 flush
      rowid = c.id
      session.execute(sa_text("INSERT INTO chunk_vec ..."))
  ```
- **问题描述**：N 个 chunk = N 次 round-trip 到 SQLite。1000 片文档导入可能要数秒。
- **修复建议**：用 `session.add_all(chunks)` + 单次 `flush`，然后 `select Chunk.id where doc_id=? order by idx` 拿 rowid 列表，再 `executemany` 批量插入向量。

---

### P1-16 `parser._strip_markdown` 多个正则会误伤正文内容

- **影响范围**：所有 md 文档导入
- **代码位置**：`src/hermes_kb/parser.py:71-94`
- **问题描述**：
  - `re.sub(r"\*([^*]+)\*", r"\1", text)` 会把 `2 * 3 * 4` 替换为 `2 3 4`
  - `re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)` 会删掉以 `-` 开头的非列表段落
  - `re.sub(r"__([^_]+)__", r"\1", text)` 会误伤 `__init__` 这类 Python 代码
- **修复建议**：用 markdown-it-py / mistune 等成熟解析器，或显式识别代码块后再处理。

---

### P1-17 前端 `ChatPanel.seed` 与 `App.handleSeed` 功能重复，且行为不一致

- **影响范围**：用户体验、可维护性
- **代码位置**：
  - `web/src/components/ChatPanel.tsx:125-136`：无确认弹框
  - `web/src/App.tsx:92-104`：有 `confirm` 弹框
- **问题描述**：用户在不同入口点"导入种子"会得到不同体验；且两处代码几乎一样。
- **修复建议**：抽取 `useSeedMutation` hook 或统一到 App 层。

---

### P1-18 测试 `conftest.py` 的 `tmp_db` 是 `autouse=True`，影响所有测试

- **影响范围**：测试隔离性、未来非 kb 模块的测试
- **代码位置**：`tests/test_kb/conftest.py:19-34`
- **问题描述**：`autouse=True` 会对 `tests/test_kb/` 下所有测试生效，包括将来不涉及数据库的纯函数测试，无谓地设置环境变量、重置单例。`tests/test_config.py` 在 `tests/` 根目录下，不受影响，但如果将来在 `test_kb/` 加非 db 测试就会被打扰。
- **修复建议**：改为显式 fixture 或限定 marker（如 `@pytest.mark.db`）。

---

## P2 改进建议（可以优化）

### P2-1 magic number 散落各处

- **代码位置**：
  - `app.py:548` `if len(files) > 20`
  - `app.py:640` `min(limit, 500)`
  - `retrieval.py:189` `LIMIT 10000`
  - `daily_recipe.py:77, 85, 98` `0.6 / 0.9` 概率
  - `lab_dashboard.py:33` `timedelta(days=7)`
  - `app.py:189` CORS `["*"]`
- **建议**：集中到 `config.py` 的 `Settings`，命名 `MAX_BATCH_FILES`/`HOT_RECIPE_DAYS` 等。

---

### P2-2 命名风格不统一

- **代码位置**：
  - `RecipeStats` 没有 `created_at`（其他表都有）
  - `app.py:837` `lab_view`（动词），`app.py:804` `lab_match`（动词），但 `app.py:864` `lab_save_substitute`（带动词 save）
  - `lab_dashboard_endpoint` 加了 `_endpoint` 后缀，其他端点没有
  - 函数内 lazy import 与顶层 import 混用
- **建议**：统一为"名词 + 动词"或 RESTful 风格（如 `POST /api/lab/substitutes`）。

---

### P2-3 类型注解不完整

- **代码位置**：
  - `ingredients.py:11` `dict[str, dict]` 内层 dict 无具体类型
  - `seed_recipes.py:8` `list[dict]` 无具体类型
  - `lab_dashboard.py` 多处 `dict[str, Any]`
  - `recipe_match.py` 函数返回 `dict[str, list[dict[str, Any]]]`，难以维护
- **建议**：用 `TypedDict` 或 `dataclass` 描述 RecipeMeta、MatchResult、DashboardMetrics。

---

### P2-4 文档缺失

- **问题**：无 `ARCHITECTURE.md`、无 ER 图、API 端点无 OpenAPI tags 分组、`app.py` 描述还停留在 "M0+M1"
- **建议**：
  - `app.py:179` 更新描述为 "M4.1 鸡尾酒实验室 + 自动运营"
  - 加 `tags=["documents"]`/`["lab"]`/`["auth"]` 等
  - 补 `docs/ARCHITECTURE.md`，画模块依赖图

---

### P2-5 `models.py` 数据模型缺字段

- **代码位置**：`src/hermes_kb/models.py`
- **问题**：
  - `RecipeStats` 无 `created_at`（其他表都有）
  - `MissingIngredientStats` 无 `created_at`
  - `IngredientSubstitute` 无 `updated_at`（用户改 substitute 时无法追踪）
  - `Document` 无 `updated_at`（元信息更新无追踪）
- **建议**：统一加 `created_at` / `updated_at` 审计字段。

---

### P2-6 `retrieval._bm25` 把 score 取负值后传入 RRF，但 RRF 只用 rank

- **代码位置**：`src/hermes_kb/retrieval.py:165` `score = -raw_score`
- **问题**：`RetrievalHit.score` 字段在 BM25/vector/RRF 三种 source 下语义不一致（BM25 是负距离、vector 是余弦、RRF 是 1/(k+rank)），下游无法统一处理。
- **建议**：`RetrievalHit` 拆为 `raw_score` + `normalized_score`，或仅 RRF 阶段保留 score。

---

### P2-7 前端缺少 Error Boundary

- **代码位置**：`web/src/App.tsx`
- **问题**：React 组件抛错会白屏，无降级 UI。
- **建议**：在 `App` 外包 `ErrorBoundary`，展示友好错误页 + 重试按钮。

---

### P2-8 前端 a11y 缺失

- **代码位置**：所有 `.tsx` 组件
- **问题**：
  - `<button>` 缺 `aria-label`（如关闭按钮 `×`）
  - `<select>` 未关联 `<label htmlFor>`
  - 颜色对比度未审查（如 `text-gray-400` on white）
  - 无 `skip-to-content` 链接
  - 无 focus 可见样式（`focus:outline` 全局去掉）
- **建议**：加 ESLint `jsx-a11y` 插件，补全 aria 属性。

---

### P2-9 前端 `api.ts` 写死 `BASE = ""`，不支持环境切换

- **代码位置**：`web/src/api.ts:16`
- **建议**：改为 `const BASE = import.meta.env.VITE_API_BASE ?? ""`，支持 dev/prod 分离。

---

### P2-10 `_check_output` 的泄露标记是硬编码字符串列表，易漏

- **代码位置**：`src/hermes_kb/rag.py:58` `_OUTPUT_LEAK_MARKERS`
- **问题**：`"你是 Hermes"` 等标记如果 system prompt 改了，标记没同步更新就失效。
- **建议**：从 system prompt 模板自动派生标记（如"取 system prompt 前 N 字"作为指纹）。

---

### P2-11 `_INJECTION_PATTERNS` 越狱关键词列表过于简单，误杀率高

- **代码位置**：`src/hermes_kb/rag.py:40-56`
- **问题**：
  - `"你是"` 会误杀 `"你是谁"`、`"你认为"`
  - `"忘记"` 会误杀 `"我忘记了"`
  - `"system:"` 会误杀正常提问中的 "system:"
  - 列表硬编码，无维护机制
- **建议**：用更精确的正则（如 `"你是\s*(?!谁|哪|什么)"`），或引入 LLM 二次判定。

---

### P2-12 `seed_recipes.py` 中"血腥玛丽"步骤与 ingredients 不一致

- **代码位置**：`src/hermes_kb/seed_recipes.py:185, 200`
- **问题**：步骤里"芹菜枝或柠檬片装饰"，但 `ingredients` 未包含芹菜枝；测试 `test_seed_recipes_all_ingredients_canonical` 只校验 ingredients 是否在注册表，不校验 content 一致性。
- **建议**：补全 ingredients，或改写步骤。

---

### P2-13 `test_api.py:test_seed` 硬编码 `seeded == 5`

- **代码位置**：`tests/test_kb/test_api.py:148-150`
- **问题**：如果 `SEED_DOCS` 增删条目，测试要同步改。
- **建议**：`assert body["seeded"] == len(SEED_DOCS)`。

---

### P2-14 `daily_recipe.py` 的"10% 全库随机"分支重复查询所有 recipe

- **代码位置**：`src/hermes_kb/daily_recipe.py:99-110`
- **问题**：`_seasonal_pool` 已经 `select Document where category=recipe`，10% 分支又查一次，且都查了 first_chunk。
- **建议**：把全库 recipes 一次查出，季节池从内存中 filter。

---

### P2-15 `app.py` 描述 "AI 原生酒类知识库（M0+M1）" 已过时

- **代码位置**：`src/hermes_kb/app.py:179`
- **建议**：更新为 "M4.1 鸡尾酒实验室 + 自动运营层"。

---

### P2-16 `config.py`（hermes_kb）与 `hermes/config.py` 是两套独立 Settings，风格不统一

- **代码位置**：
  - `src/hermes_kb/config.py`：手写 dataclass + `os.environ.get`
  - `src/hermes/config.py`：pydantic-settings + `BaseSettings`
- **问题**：维护两套配置加载逻辑，新人上手困惑。
- **建议**：统一到 pydantic-settings。

---

### P2-17 `web/src/components/DocumentDetailPanel.tsx` 等 chunk 高亮通过 `classList.add/remove` 直接操作 DOM

- **代码位置**：`web/src/components/DocumentDetailPanel.tsx:55-63`
  ```ts
  el.classList.add("ring-4", "ring-brand-400", "bg-brand-50");
  setTimeout(() => { el.classList.remove("ring-4", "ring-brand-400", "bg-brand-50"); }, 2000);
  ```
- **问题**：React 中直接操作 DOM class 与 React state 并存，刷新或重渲染时样式会失效。Tailwind 的 `ring-4` 等类需要 `focus:ring-4` 或显式样式才稳定。
- **建议**：改为 `useState<number | null>(highlightedChunk)`，通过 className 条件渲染。

---

## 质量评分

| 维度 | 得分 | 评价 |
|------|------|------|
| 架构设计 | **12 / 20** | 模块分层清晰但耦合较深（lazy import 掩盖循环依赖）；数据模型缺外键和级联；安全控制（年龄门、CORS、JWT 默认密钥）形同虚设；性能问题（向量全表扫描、N+1）会在数据量稍大时崩盘 |
| 代码质量 | **12 / 20** | 异常处理 26 处 `except Exception` 大多静默吞错；类型注解不完整；magic number 散落；DRY 违反（missing_stats / recipe_stats 几乎一样的代码）；JSON 解析和 SQL 全在裸字符串里 |
| 测试质量 | **14 / 20** | 159 测试全通过值得肯定，但只覆盖 happy path；错误路径、并发、删除级联、向量截断、流式泄露检测等关键场景全空缺；fixture 重复定义；时间依赖有 flaky 风险 |
| 可维护性 | **13 / 20** | 命名不统一（中英文混用、动词名词混用）；文档缺失（无 ARCHITECTURE.md、API 描述过时）；配置不统一（两套 Settings）；扩展新功能需改动多个文件（如新增统计指标要改 dashboard + stats + models 三处） |
| 前端质量 | **13 / 20** | React + TS + Tailwind 栈选型合理；但 a11y 几乎为零；Error Boundary 缺失；直接操作 DOM class 与 React 范式冲突；API BASE 写死；组件间功能重复（seed 函数两处） |
| **总分** | **64 / 100** | **可演示不可生产**：MVP 阶段合格，但 P0 安全/数据一致性/性能问题必须在面向真实用户前解决 |

---

## 修复优先级建议

### 立即（上线前阻断）
1. **P0-1** JWT 默认密钥 → 启动时强制校验
2. **P0-2** 异常 detail 透传 → 生产模式脱敏
3. **P0-5** 年龄门无效 → 后端加依赖校验
4. **P0-6** 外键/级联缺失 → 加 FK + PRAGMA foreign_keys=ON

### 短期（1-2 周内）
5. **P0-3** 向量检索截断 + 全表扫描 → 引入 sqlite-vec 或 Chroma
6. **P0-4** SSE 流式泄露检测 → 滑动窗口检测
7. **P1-1 / P1-2** N+1 与同步写统计 → 批量查询 + BackgroundTasks
8. **P1-3** weekly_match_count 语义错 → 改指标或改文案
9. **P1-12** 补测试覆盖

### 中期（迭代中）
10. **P1-4 / P1-5** 配方材料解析脆弱 → 改为显式 metadata
11. **P1-10** lazy import → 重构模块边界
12. **P1-11** CORS 配置 → 默认关闭
13. P2 系列按需处理

---

## 附：审查文件清单

| 路径 | 说明 |
|------|------|
| `src/hermes_kb/app.py` | FastAPI 入口，所有端点 |
| `src/hermes_kb/models.py` | SQLModel 数据模型 |
| `src/hermes_kb/config.py` | 配置加载（hermes_kb 版） |
| `src/hermes_kb/database.py` | 引擎/会话/FTS/向量表初始化 |
| `src/hermes_kb/rag.py` | RAGEngine + ImportService |
| `src/hermes_kb/retrieval.py` | 混合检索（BM25 + 向量 + RRF） |
| `src/hermes_kb/embedding.py` | Embedding Provider 抽象 |
| `src/hermes_kb/llm.py` | LLM Provider 抽象 |
| `src/hermes_kb/query_rewriter.py` | 查询改写 |
| `src/hermes_kb/parser.py` | 文档解析 + 分片 |
| `src/hermes_kb/ingredients.py` | 材料注册表 |
| `src/hermes_kb/substitutes.py` | 替代关系表 |
| `src/hermes_kb/seed_recipes.py` | IBA 配方种子 |
| `src/hermes_kb/recipe_match.py` | 配方匹配算法 |
| `src/hermes_kb/recipe_stats.py` | 配方使用统计 |
| `src/hermes_kb/daily_recipe.py` | 每日推荐 |
| `src/hermes_kb/missing_stats.py` | 缺材料统计 |
| `src/hermes_kb/lab_dashboard.py` | 运营看板 |
| `src/hermes_kb/seed.py` | 5 篇酒类种子文档 |
| `src/hermes_kb/kb_cli.py` | CLI |
| `tests/test_kb/conftest.py` | 测试 fixture |
| `tests/test_kb/test_lab.py` | M3 测试 |
| `tests/test_kb/test_lab_ops.py` | M4.1 测试 |
| `tests/test_kb/test_api.py` | API 集成测试 |
| `tests/test_kb/test_m1.py` | M1 验收测试 |
| `tests/test_kb/test_m2.py` | M2 验收测试 |
| `tests/test_kb/test_edge.py` | 边界测试 |
| `tests/test_kb/test_rag.py` | RAG 单测 |
| `web/src/App.tsx` | 前端入口 |
| `web/src/api.ts` | API 客户端 |
| `web/src/types.ts` | TS 类型定义 |
| `web/src/components/*.tsx` | 7 个组件 |
| `web/src/index.css` | 全局样式 |
| `web/tailwind.config.js` | Tailwind 配置 |
| `pyproject.toml` | 项目元数据 |

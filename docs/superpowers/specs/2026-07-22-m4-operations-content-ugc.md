# M4 运营层 + 内容扩充 + UGC 设计 Spec

> 本 spec 基于 M3 已交付的"鸡尾酒实验室"（材料匹配 + 配方统计 + 热门推荐），规划 M4 三个增量方向：自动运营层、L3 外部数据源、UGC 调酒研究室。三者按里程碑梯度交付，各自独立可测。

## 1. 背景与定位

### 1.1 战略位置

M3 已交付实验室核心闭环（选材料 → 匹配配方 → 引用溯源 → 统计计数）。M4 把实验室从"静态查询工具"升级为"活起来的运营平台"：

```
M3 已交付（查询闭环）            M4 增量（运营 + 内容 + 创作）
┌─────────────────────┐      ┌──────────────────────────────┐
│ 材料选择 + 配方匹配   │      │ M4.1 自动运营层              │ ← 每日推荐/反馈/看板
│ 配方统计 + 热门 Top3  │      │ M4.2 L3 外部数据源           │ ← TheCocktailDB/ima
│ 8 款 IBA 种子配方     │ ←──→ │ M4.3 UGC 调酒研究室          │ ← 用户创作+审核
└─────────────────────┘      └──────────────────────────────┘
```

### 1.2 里程碑划分

| 里程碑 | 方向 | 核心交付 | 依赖 | 优先级 |
|---|---|---|---|---|
| M4.1 | 自动运营层 | 每日推荐 + 缺材料反馈 + 运营看板 | M3 recipe_stats（已有） | P0 |
| M4.2 | L3 外部数据源 | TheCocktailDB 同步 + ima adapter | M3 配方文档模型（已有） | P1 |
| M4.3 | UGC 调酒研究室 | 配方编辑器 + 审核流程 + 变体关联 | M4.2 source 治理 | P2 |

**实施顺序**：M4.1 → M4.2 → M4.3。M4.1 不依赖内容扩充即可见效（基于 M3 的 8 款配方）；M4.2 扩充内容让 M4.1 的推荐更有意义；M4.3 最重，需审核流程且依赖 M4.2 的 source 治理机制。

### 1.3 不做什么（M4 范围外）

- 不做个性化推荐（M5，需用户口味画像）
- 不做商业合作接口（M5+，需与知识层物理隔离）
- 不做配方图片识别/OCR（远期探索）

---

## 2. M4.1 自动运营层

### 2.1 每日推荐

**目标**：实验室入口展示"今日推荐配方"，基于季节 + 热门 + 随机加权，每日轮换。

**算法**：
```python
def daily_recipe() -> dict:
    """每日推荐：季节权重 60% + 热门权重 30% + 随机 10%"""
    season = current_season()  # spring/summer/autumn/winter
    seasonal_pool = recipes_with_tag(f"{season}-recipe")
    hot_pool = get_hot_recipes(limit=20, days=30)
    # 季节池非空则 60% 概率从中选，否则回退热门池
    # 最终 10% 概率从全库随机
    # 当日固定（按日期 seed，同一天返回同一款）
```

**季节标签**（配方 frontmatter 或 seed_recipes 扩展）：
- `spring-recipe`：清新花香（吉姆雷特、白色佳人）
- `summer-recipe`：清爽冰凉（莫吉托、龙舌兰日出）
- `autumn-recipe`：温暖醇厚（古典鸡尾酒、曼哈顿）
- `winter-recipe`：热烈浓烈（热红酒、爱尔兰咖啡）

**日期稳定性**：同一天内多次调用返回同一款（用 `date.today().isoformat()` 作随机种子）。

**API**：`GET /api/lab/daily` → `{title, doc_id, chunk_rowid, reason, base_spirit, difficulty}`
- `reason` 字段说明推荐理由（如"夏日清爽"、"本周热门"、"随机发现"）

### 2.2 缺材料反馈循环

**目标**：统计哪些材料最常"缺"，反向优化替代关系表。

**数据模型**：
```python
class MissingIngredientStats(SQLModel, table=True):
    """M4.1：缺失材料统计。"""
    canonical: str = Field(primary_key=True, max_length=64)
    missing_count: int = Field(default=0)
    last_missing_at: datetime | None = Field(default=None)
```

**统计时机**：`/api/lab/match` 返回 partial_match 时，对每个 `missing` 材料计数 +1。

**运营动作**：
- 每周生成"高频缺失材料榜"（管理后台或 API 返回）
- 当某材料 `missing_count > 50` 且无预置替代时，在运营看板告警
- 用户点替代 chip `+` 加入的材料，若不在预置替代表，提示"是否保存为自定义替代？"

**API**：
- `GET /api/lab/missing-stats?limit=10` → 缺失材料排行
- `POST /api/lab/substitute` → 用户保存自定义替代（body: `{canonical, substitute}`）

### 2.3 运营看板扩展

**目标**：`dashboard.html` 增加"实验室健康度"卡片组。

**布局**：
```
┌─────────────────────────────────────┐
│ 实验室运营                           │
├─────────────────────────────────────┤
│ 配方总数：8    │ 本周匹配：12 次     │
│ Top 配方：马天尼 │ 高频缺失：君度(3) │
│ 替代表覆盖：38% │ 用户自定义：0 条    │
│ 今日推荐：莫吉托 │ 季节标签覆盖：50%  │
└─────────────────────────────────────┘
```

**指标定义**：
- 配方总数 = `Document.category == "recipe"` 计数
- 本周匹配 = 近 7 天 `RecipeStats.match_count` 总和
- Top 配方 = `get_hot_recipes(limit=1)`
- 高频缺失 = `MissingIngredientStats` Top 1
- 替代表覆盖率 = 有替代关系的材料数 / 总材料数
- 用户自定义 = `IngredientSubstitute.source == "user"` 计数
- 今日推荐 = `daily_recipe()` 的 title
- 季节标签覆盖 = 带 season 标签的配方数 / 配方总数

**API**：`GET /api/lab/dashboard` → 上述所有指标聚合

---

## 3. M4.2 L3 外部数据源

### 3.1 TheCocktailDB 同步

**目标**：从 TheCocktailDB（开源免费 API）拉取 200+ 配方扩充知识库。

**数据源**：`https://www.thecocktaildb.com/api.php`（免费，无需 Key，有 CORS 支持）

**同步机制**：
- 定时任务：每日 03:00 增量同步（APScheduler 或 cron）
- 手动触发：管理后台"同步外部数据源"按钮 → `POST /api/lab/sync`
- 去重：按 `source + source_id` 唯一约束（source="thecocktaildb", source_id=API 返回的 idDrink）
- 审核：L3 同步的配方 `verified=false`，默认不进实验室匹配，用户报告问题后人工审核

**配方文档 frontmatter 扩展**：
```yaml
---
title: Mojito
category: recipe
source: iba          # iba | user | thecocktaildb | ima | ugc
source_id: "iba-042"  # 或 thecocktaildb 的 idDrink
verified: true        # 是否经过审核（L3 同步默认 false）
tags: [recipe, rum-base, summer-recipe]
season: summer        # spring/summer/autumn/winter（用于每日推荐）
---
```

**材料名归一化**：TheCocktailDB 返回英文材料名（如 "Light rum", "Lime", "Mint"），需通过 `ingredients.py` 的 `canonicalize()` 映射到中文标准名。未命中的材料记录到 `unknown_ingredients` 日志，供后续扩充注册表。

**API**：
- `POST /api/lab/sync` → 触发同步（body: `{source: "thecocktaildb", limit: 50}`）
- `GET /api/lab/sync/status` → 同步状态（上次同步时间、新增数、失败数）

### 3.2 ima 知识库 adapter

**目标**：接 ima（用户提供 Key）拉取专业酒类配方、品鉴笔记。

**接入方式**：ima adapter，按需拉取（非定时同步）。
- 用户在设置页填入 ima API Key
- 实验室搜索时可选"包含 ima 来源"
- ima 配方 `source="ima"`，`verified=false`

**M4.2 范围**：仅实现 adapter 接口骨架 + 配置项，实际拉取逻辑视 ima API 文档而定（可能需逆向）。若 ima API 不可用，降级为"仅 IBA + TheCocktailDB"。

### 3.3 数据源治理

**优先级**：L1 > L2 > L3 > L4 > L5（同款配方多来源时，高优先级覆盖低优先级）

**冲突处理**：配方内容冲突时保留 L1 IBA 官方版本，其他来源存为"变体"（关联同一 canonical title，但不同 source）。

**下架机制**：用户可隐藏任意来源的配方（`hidden=true` 标记，不影响知识库数据，仅影响实验室展示）。

**API**：
- `GET /api/lab/recipes?source=thecocktaildb&verified=false` → 按来源/状态筛选
- `POST /api/lab/recipes/{doc_id}/verify` → 审核通过（verified=true）
- `POST /api/lab/recipes/{doc_id}/hide` → 隐藏配方

---

## 4. M4.3 UGC 调酒研究室

### 4.1 配方编辑器

**目标**：用户可创作自定义配方，沉淀为 `category=recipe, source=ugc` 的文档。

**页面**：`lab.html` 增加"创作"入口，或独立 `recipe-editor.html`。

**编辑器字段**：
- title（配方名，必填）
- base_spirit（基酒，下拉选自 INGREDIENT_REGISTRY）
- difficulty（easy/medium/hard）
- ingredients（材料列表，从注册表选择 + 自定义输入）
- steps（步骤，富文本或 Markdown）
- flavor（风味描述）
- season（季节标签，可选）
- tags（自定义标签）

**材料选择器**：复用 lab.html 的 chip 组件，但增加"自定义材料"输入框（输入后自动 canonicalize，未命中则提示"将作为新材料"）。

**保存**：`POST /api/lab/recipes` → 创建配方文档（source=ugc, verified=false）

### 4.2 审核流程

**状态机**：`draft → pending → published / rejected`

- draft：用户编辑中，仅自己可见
- pending：用户提交审核，进入审核队列
- published：审核通过，进实验室匹配（verified=true）
- rejected：审核驳回，附驳回理由

**审核入口**：dashboard 增加"待审核配方"列表，管理员可 approve/reject。

**API**：
- `POST /api/lab/recipes` → 创建（status=draft）
- `POST /api/lab/recipes/{doc_id}/submit` → 提交审核（draft → pending）
- `POST /api/lab/recipes/{doc_id}/approve` → 通过（pending → published）
- `POST /api/lab/recipes/{doc_id}/reject` → 驳回（body: `{reason}`）

### 4.3 变体关联

**目标**：用户可基于已有配方创作"变体"（如"辛辣版马天尼"），关联到原配方。

**数据模型**：
```python
class RecipeVariant(SQLModel, table=True):
    """M4.3：配方变体关联。"""
    id: int | None = Field(default=None, primary_key=True)
    base_doc_id: str = Field(index=True, max_length=64)  # 原配方
    variant_doc_id: str = Field(index=True, max_length=64)  # 变体配方
    variant_note: str = Field(default="", max_length=200)  # 变体说明
    created_at: datetime = Field(default_factory=_utcnow)
```

**展示**：配方详情页显示"变体列表"和"基于哪款配方"。

---

## 5. 数据模型新增汇总

| 模型 | 里程碑 | 用途 |
|---|---|---|
| `MissingIngredientStats` | M4.1 | 缺材料统计 |
| `RecipeVariant` | M4.3 | 变体关联 |
| `Document` 扩展字段 | M4.2 | `source` / `source_id` / `verified` / `season` / `hidden` / `status` |

**Document 扩展**（向后兼容，新增字段均有默认值）：
```python
class Document(SQLModel, table=True):
    # ... 已有字段 ...
    source: str = Field(default="local", max_length=32)  # local/iba/user/thecocktaildb/ima/ugc
    source_id: str | None = Field(default=None, max_length=64)
    verified: bool = Field(default=True)
    season: str | None = Field(default=None, max_length=16)  # spring/summer/autumn/winter
    hidden: bool = Field(default=False)
    status: str = Field(default="published", max_length=16)  # draft/pending/published/rejected
```

---

## 6. API 端点规划

### M4.1 自动运营层
| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/lab/daily` | 每日推荐 |
| GET | `/api/lab/missing-stats` | 缺失材料排行 |
| POST | `/api/lab/substitute` | 保存用户自定义替代 |
| GET | `/api/lab/dashboard` | 运营看板聚合指标 |

### M4.2 L3 外部数据源
| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/lab/sync` | 触发 TheCocktailDB 同步 |
| GET | `/api/lab/sync/status` | 同步状态 |
| GET | `/api/lab/recipes` | 按来源/状态筛选配方 |
| POST | `/api/lab/recipes/{doc_id}/verify` | 审核通过 |
| POST | `/api/lab/recipes/{doc_id}/hide` | 隐藏配方 |

### M4.3 UGC 调酒研究室
| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/lab/recipes` | 创建 UGC 配方 |
| PUT | `/api/lab/recipes/{doc_id}` | 编辑配方 |
| POST | `/api/lab/recipes/{doc_id}/submit` | 提交审核 |
| POST | `/api/lab/recipes/{doc_id}/approve` | 审核通过 |
| POST | `/api/lab/recipes/{doc_id}/reject` | 审核驳回 |
| GET | `/api/lab/recipes/{doc_id}/variants` | 查看变体列表 |

---

## 7. 前端页面规划

### M4.1
- `index.html`：首页热门区上方增加"今日推荐"卡片
- `dashboard.html`：增加"实验室运营"卡片组
- `lab.html`：匹配结果区上方增加"今日推荐"入口

### M4.2
- `dashboard.html`：增加"外部数据源同步"按钮 + 状态显示
- `docs.html`：配方列表增加 source/verified 筛选器

### M4.3
- `recipe-editor.html`（新建）：配方编辑器
- `doc-detail.html`：配方详情增加"变体列表" + "创作变体"入口
- `dashboard.html`：增加"待审核配方"队列

---

## 8. 交付物清单

### M4.1 自动运营层（优先实施）
- 后端：`daily_recipe.py` + `missing_stats.py` + `lab_dashboard.py`
- 数据模型：`MissingIngredientStats` 表
- API：4 个端点
- 前端：index.html 今日推荐 + dashboard.html 实验室卡片组
- seed_recipes.py 扩展：8 款配方增加 season 标签

### M4.2 L3 外部数据源
- 后端：`thecocktaildb_sync.py` + `ima_adapter.py`（骨架）
- 数据模型：Document 扩展 source/source_id/verified/season/hidden/status 字段
- API：5 个端点
- 前端：dashboard.html 同步按钮 + docs.html 筛选器

### M4.3 UGC 调酒研究室
- 后端：`recipe_crud.py`（创建/编辑/审核状态机）
- 数据模型：`RecipeVariant` 表 + Document status 字段
- API：6 个端点
- 前端：recipe-editor.html + doc-detail.html 变体区 + dashboard.html 审核队列

---

## 9. 决策记录

| ID | 决策 | 理由 |
|---|---|---|
| D32 | M4 拆三个独立里程碑 | 三方向可独立交付，M4.1 不依赖内容扩充即可见效 |
| D33 | 每日推荐用日期 seed 保稳定 | 同一天返回同一款，避免刷新变化让用户困惑 |
| D34 | 缺材料统计独立表 | 不污染 RecipeStats，缺失统计是材料维度而非配方维度 |
| D35 | L3 同步配方默认 verified=false | 避免未审核内容污染匹配结果，与 IBA 官方区分 |
| D36 | UGC 审核状态机 draft→pending→published | 平衡创作自由与内容质量，draft 可私存，published 才进匹配 |
| D37 | Document 扩展字段而非新建 Recipe 表 | 配方本就是文档，复用 chunk+RAG，扩展字段向后兼容 |
| D38 | 变体关联独立表 RecipeVariant | 多对多关系，一个配方可有多个变体，变体也可基于变体 |

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| TheCocktailDB 材料名归一化不全 | 未命中的材料记录到 unknown_ingredients 日志，定期人工扩充注册表 |
| ima API 不稳定/需逆向 | M4.2 仅实现骨架，API 不可用时降级 |
| UGC 审核成为瓶颈 | 支持"自审核"模式（单用户部署时自动通过），多用户才需人工审核 |
| Document 字段扩展导致旧数据不一致 | 所有新字段均有默认值，迁移脚本回填 verified=true / status=published |
| 每日推荐季节标签覆盖不全 | seed_recipes 8 款先补齐 season，未标 season 的配方不进季节池 |

---

**Spec complete.** M4 三个方向，按 M4.1 → M4.2 → M4.3 梯度交付。每个方向有独立 Plan。

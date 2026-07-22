# 鸡尾酒实验室（M3）设计 Spec

> 本 spec 基于 M2 已交付的"引用式私有知识管家"定位，规划 M3 增量功能"鸡尾酒实验室"。实验室把知识查询延伸到知识应用——用户用手头材料匹配可调制的鸡尾酒，配方结果复用 M2 的引用溯源机制。

## 1. 背景与定位

### 1.1 战略位置

M2 已交付"引用式私有酒类知识管家"（9 页面 + 3 modal）。M3 增量引入"鸡尾酒实验室"，作为知识应用层：

```
M2 已交付（知识查询）          M3 增量（知识应用）
┌─────────────────────┐      ┌──────────────────────┐
│ 品牌首页/问答/文档详情 │      │ 鸡尾酒实验室 lab.html │ ← 新增
│ 文档库/标签/历史/仪表盘│ ←顶栏→│ 材料选择 + 配方匹配   │
│ 审计/导出 + 3 modal   │      │ 复用引用卡片 + RAG    │
└─────────────────────┘      └──────────────────────┘
```

### 1.2 核心定位

- 实验室是知识库的一个"视图"，不是独立系统
- 配方作为 `category=recipe` 的特殊文档类型沉淀进知识库，复用 chunk + RAG
- 每款配方带 [N] 引用溯源，跳转 `doc-detail.html?chunk=N` 触发 M2 高亮动画

### 1.3 不做什么

- 不做 UGC 配方创作（调酒研究室，M4+ 远期）
- 不做购买指南/导购（商业化层，M5+ 需与知识层物理隔离）
- 不接 ima 知识库（M4 远期探索，API Key 留存备用）

## 2. 数据模型

### 2.1 配方文档结构

每款 IBA 配方作为 Markdown 文档导入知识库，带 frontmatter 元信息：

```markdown
---
title: 马天尼 Martini
category: recipe
tags: [recipe, gin-base, iba-classic]
base_spirit: gin
difficulty: easy
---

# 马天尼 Martini

## 配方
- 金酒 60ml
- 干味美思 10ml
- 橄榄 1 颗（装饰）

## 步骤
1. 冰镇马天尼杯
2. 调酒杯加冰，倒入金酒与味美思
3. 搅拌 30 秒
4. 滤冰倒入杯中
5. 放入橄榄

## 风味
干爽、清冽、杜松子主导。被誉为"鸡尾酒之王"。
```

格式与 M2 文档导入一致，RAG 可直接切片检索，用户也能用"基于此文档提问"追问配方细节。

### 2.2 材料分类（4 大类）

| 分类 | 字段名 | 示例 | chip 选中色 |
|---|---|---|---|
| 基酒 | base_spirit | 金酒、威士忌、朗姆、龙舌兰、白兰地、伏特加 | `--brand-700` 酒红底白字 |
| 辅料 | modifier | 味美思、苦精、糖浆、君度、利口酒 | `--gold-500` 暗金底深字 |
| 果汁 | juice | 柠檬汁、青柠汁、橙汁、蔓越莓汁 | `--ink-600` 暖灰底白字 |
| 装饰 | garnish | 橄榄、柠檬片、薄荷叶、樱桃 | `--ink-400` 浅灰底深字 |

### 2.3 材料标准化与别名

每个材料有标准名（canonical）+ 别名表（aliases），解决"金酒/Gin/Dry Gin/Gordon's"的归一化：

```python
# src/hermes_kb/ingredients.py
INGREDIENT_REGISTRY = {
    "gin": {
        "canonical": "金酒",
        "aliases": ["gin", "dry gin", "london dry", "杜松子酒", "gordon's"],
        "category": "base_spirit",
    },
    "cointreau": {
        "canonical": "君度",
        "aliases": ["cointreau", "triple sec", "橙味力娇酒"],
        "category": "modifier",
        "substitutes": ["干库拉索", "橙味力娇酒"],
    },
}
```

### 2.4 三层替代关系表

```python
# L1: 预置 IBA 替代关系（src/hermes_kb/substitutes.py）
SUBSTITUTES_PRESET = {
    "君度": ["干库拉索", "橙味力娇酒"],
    "青柠汁": ["柠檬汁"],
    "糖浆": ["蜂蜜糖浆"],
    "汤力水": ["苏打水 + 少许柠檬"],
}

# L2: 用户自定义替代（运行时合并，持久化到 SQLite）
# 表: ingredient_substitutes(canonical TEXT, substitute TEXT, source TEXT)
#   source = 'preset' | 'user'

# L3: 外部同步（M4 远期，接口预留）
```

### 2.5 匹配算法

```python
def match_recipes(user_ingredients: set[str]) -> list[RecipeMatch]:
    """材料集合 → 配方匹配，分三组返回。"""
    full_match = []      # 缺 0 种
    partial_match = []   # 缺 1-2 种
    # 缺 3+ 种不返回

    for recipe in all_recipes:
        recipe_ingredients = recipe.required_ingredients
        missing = recipe_ingredients - user_ingredients

        # 检查替代：缺的材料是否有用户已有的替代品
        resolved_missing = []
        for m in missing:
            subs = get_substitutes(m)  # L1+L2 合并查询
            if subs & user_ingredients:
                continue  # 有替代，不算缺
            resolved_missing.append(m)

        if len(resolved_missing) == 0:
            full_match.append(recipe)
        elif len(resolved_missing) <= 2:
            partial_match.append((recipe, resolved_missing))

    return sort_by_match_count(full_match) + sort_by_missing_count(partial_match)
```

关键规则：
- 替代品命中算"不缺"——用户有橙味力娇酒，君度缺了也能进"现在就能做"组
- 缺 3+ 种的配方不展示，避免噪声
- 排序：能做组按材料命中数降序，差一点组按缺少数升序

## 3. 页面结构

### 3.1 lab.html 布局

单页三区，极简垂直流，无侧栏：

```
┌─────────────────────────────────────────────┐
│ 顶栏（复用 _nav.js，lab 高亮）                │
├─────────────────────────────────────────────┤
│ 1. 材料选择区                                 │
│    [搜索框] + 4 大类折叠区 + 已选材料条        │
│    [匹配配方 →] 按钮                          │
├─────────────────────────────────────────────┤
│ 2. 匹配结果区（匹配后展开）                    │
│    ▼ 现在就能做（N）                          │
│      [配方卡] [配方卡] ...                    │
│    ▼ 差一种就能做（M）                        │
│      [配方卡 缺X] [配方卡 缺Y] ...            │
├─────────────────────────────────────────────┤
│ 3. 空状态/引导区（未匹配时）                   │
│    "选择材料，发现你能调的鸡尾酒"              │
└─────────────────────────────────────────────┘
```

### 3.2 交互流

1. 用户点材料 chip → chip 变金色选中 → 已选条更新
2. 点"匹配配方" → 结果区展开，`scroll-behavior: smooth` 平滑定位
3. 点配方卡 [N] 引用 → 跳转 `doc-detail.html?chunk=N`，复用 M2 chunk 高亮动画
4. 缺材料配方卡显示"可替代：橙味力娇酒" → 点替代 chip `+` 自动加入已选并重新匹配
5. "基于此配方提问"按钮 → 跳转 `ask.html?q=马天尼的做法`

## 4. 组件设计

### 4.1 材料选择器

```html
<div class="material-selector">
  <input class="input material-search" placeholder="搜索材料... 如 金酒">

  <details class="material-category" open>
    <summary>基酒 <span class="count">6</span></summary>
    <div class="chip-list">
      <button class="chip-chip selected">金酒 ✓</button>
      <button class="chip-chip">威士忌</button>
    </div>
  </details>
  <!-- 辅料/果汁/装饰同理，默认折叠 -->

  <div class="selected-bar">
    已选：<span class="selected-chip">金酒 ×</span>
    <button class="btn-ghost">清空</button>
  </div>

  <button class="btn-primary match-btn">匹配配方 →</button>
</div>
```

配色规则：
- 基酒 chip：未选 `--ink-100` 底 / 选中 `--brand-700` 底白字
- 辅料 chip：未选 `--ink-100` 底 / 选中 `--gold-500` 底深字
- 已选条：`--gold-100` 底 + `--gold-500` 左边框（与引用卡片一致）

### 4.2 配方卡片

```html
<div class="recipe-card full-match">
  <!-- 缺材料时 class 改为 partial-match -->
  <div class="recipe-header">
    <h3 class="recipe-name">马天尼 Martini</h3>
    <span class="match-badge match-full">材料齐全</span>
  </div>
  <div class="recipe-ingredients">
    <span class="ing have">✓ 金酒 60ml</span>
    <span class="ing have">✓ 干味美思 10ml</span>
    <span class="ing have">✓ 橄榄</span>
    <span class="ing missing">✗ 君度 15ml</span>
  </div>
  <div class="substitute-suggest">
    可替代：<button class="sub-chip">橙味力娇酒 +</button>
    <button class="sub-chip">干库拉索 +</button>
  </div>
  <div class="recipe-footer">
    <a href="doc-detail.html?chunk=42" class="citation-link">[1] 引用 IBA 百科</a>
    <button class="btn-ghost">基于此配方提问</button>
  </div>
</div>
```

替代推荐交互：点 `+` 替代 chip → 该材料自动加入已选条 → 重新匹配 → 此配方从"差一点"升入"现在就能做"组。

## 5. 与 M2 的集成

| 集成点 | 方式 |
|---|---|
| 导航 | `_nav.js` 新增 lab 链接，位于"问答"与"文档库"之间 |
| 设计 token | 直接引用 `_tokens.css`，不新增变量 |
| 组件样式 | 配方卡/材料 chip 新样式追加进 `_components.css` 的"实验室组件"区块 |
| 引用溯源 | 配方卡 [N] 跳转 `doc-detail.html?chunk=N`，复用 chunk 高亮动画 |
| RAG 召回 | 配方文档作为 `category=recipe` 普通文档进知识库，问答页也能问"马天尼怎么调" |
| 问答联动 | 配方卡"基于此配方提问"按钮跳转 `ask.html?q=马天尼的做法` |
| 种子数据 | 新增 `seed_recipes.py`，启动时导入 IBA 80 款配方（带 `recipe` 标签） |

## 6. 冷启动与空状态

| 场景 | 展示 |
|---|---|
| 首次进入实验室（未选材料） | 引导文案"选择手头的材料，发现你能调的鸡尾酒" + 3 个示例材料 chip（金酒/味美思/柠檬汁） |
| 选了材料未点匹配 | "匹配配方"按钮高亮脉动提示 |
| 匹配结果为空 | "没有匹配的配方，试试减少材料或添加替代品" + 清空按钮 |
| 配方库为空（未导入 IBA 种子） | 空状态"实验室需要配方数据，点击导入 IBA 种子配方" + 导入按钮 |

## 7. API 端点

### 7.1 配方匹配

```
GET /api/lab/match?ingredients=gin,vermouth
```

响应：

```json
{
  "full_match": [
    {
      "title": "马天尼 Martini",
      "doc_id": "recipe-martini",
      "chunk_rowid": 42,
      "ingredients": [
        {"name": "金酒", "amount": "60ml", "have": true},
        {"name": "干味美思", "amount": "10ml", "have": true},
        {"name": "橄榄", "amount": "1 颗", "have": true}
      ],
      "base_spirit": "gin",
      "difficulty": "easy"
    }
  ],
  "partial_match": [
    {
      "title": "白色佳人 White Lady",
      "doc_id": "recipe-white-lady",
      "chunk_rowid": 58,
      "ingredients": [
        {"name": "金酒", "amount": "40ml", "have": true},
        {"name": "君度", "amount": "15ml", "have": false, "substitutes": ["橙味力娇酒", "干库拉索"]},
        {"name": "柠檬汁", "amount": "20ml", "have": true}
      ],
      "missing_count": 1,
      "base_spirit": "gin",
      "difficulty": "medium"
    }
  ]
}
```

### 7.2 热门配方

```
GET /api/lab/hot?limit=3&days=30
```

响应：

```json
{
  "items": [
    {"title": "马天尼 Martini", "doc_id": "recipe-martini", "chunk_rowid": 42, "match_count": 128, "last_matched_at": "2026-07-21T10:30:00Z"},
    {"title": "莫吉托 Mojito", "doc_id": "recipe-mojito", "chunk_rowid": 58, "match_count": 96, "last_matched_at": "2026-07-21T09:15:00Z"},
    {"title": "尼格罗尼 Negroni", "doc_id": "recipe-negroni", "chunk_rowid": 71, "match_count": 84, "last_matched_at": "2026-07-20T22:00:00Z"}
  ]
}
```

排序规则：`match_count` 降序，`last_matched_at` 在 `days` 参数范围内（默认 30 天，避免历史陈旧）。

## 8. 交付物清单

### 8.1 文件清单

| 文件 | 动作 | 职责 |
|---|---|---|
| `src/hermes_kb/ingredients.py` | 新建 | 材料注册表 + 别名归一化 |
| `src/hermes_kb/substitutes.py` | 新建 | 三层替代关系表 + 合并查询 |
| `src/hermes_kb/recipe_match.py` | 新建 | 匹配算法 |
| `src/hermes_kb/seed_recipes.py` | 新建 | IBA 80 款配方种子数据 |
| `src/hermes_kb/recipe_stats.py` | 新建 | 配方使用统计（match_count/view_count） |
| `src/hermes_kb/db.py` | 修改 | 新增 `recipe_stats` + `ingredient_substitutes` 表 |
| `src/hermes_kb/api.py` | 修改 | 新增 `GET /api/lab/match` + `GET /api/lab/hot` |
| `design/mockup/lab.html` | 新建 | 高保真设计稿 |
| `design/prototype/lab.html` | 新建 | 低保真原型 |
| `design/mockup/_components.css` | 修改 | 追加实验室组件样式 |
| `design/mockup/_nav.js` | 修改 | 导航新增 lab 入口 |
| `design/mockup/index.html` | 修改 | 首页分类入口区增加 Top 3 热门配方 |
| `tests/test_lab.py` | 新建 | 匹配算法 + API + 统计测试 |

### 8.2 实现顺序

1. 数据层：`ingredients.py` + `substitutes.py` + `seed_recipes.py`
2. 算法层：`recipe_match.py` + 单元测试
3. API 层：`/api/lab/match` 端点 + 测试
4. 设计稿：`lab.html` 高保真 + 低保真
5. 集成：`_nav.js` + `_components.css` 更新
6. E2E：材料选择 → 匹配 → 引用跳转全链路

## 9. 决策记录

| ID | 决策 | 理由 |
|---|---|---|
| D25 | 页面形态：独立 lab.html 极简页 | 材料选择器是核心交互价值，独立路由便于入口曝光，但页面极简符合 P6 极简哲学 |
| D26 | 数据来源：本地 IBA 种子配方 | 开箱即用，与六大基酒种子同源，ima 暂缓 M4 |
| D27 | 材料选择器：搜索 + 分类平铺混合 | 兼顾新手（分类探索）与老手（搜索直达） |
| D28 | 结果展示：分组（现在就能做 / 差一种） | 兼顾即时动手与升级启发 |
| D29 | 替代关系：三层混合（预置 + 用户 + 外部） | L1 保证开箱即用，L2 灵活扩展，L3 远期探索 |
| D30 | 配方作为 recipe 分类文档进知识库 | 复用 M2 chunk + RAG，不新建独立存储，实验室是知识库的视图 |

## 10. 风险与边界

| 风险 | 缓解 |
|---|---|
| IBA 80 款配方种子数据量大 | 分批导入，启动时后台异步加载 |
| 材料别名覆盖不全 | L2 用户自定义补充，M4 L3 外部同步 |
| 替代关系主观争议 | 预置表基于 IBA 官方 + 主流调酒教材，标注来源 |
| 匹配算法性能 | 80 款配方 O(n) 遍历可接受，无需索引 |

## 11. 后续数据源规划

实验室数据采用三层叠加架构（对应 §2.4 的 L1/L2/L3），按里程碑梯度开放：

### 11.1 数据源梯度

| 层 | 里程碑 | 数据源 | 内容 | 接入方式 |
|---|---|---|---|---|
| L1 预置 | M3 | IBA 官方 80 款 | 经典配方 + 基础替代关系 | `seed_recipes.py` 启动时导入 |
| L2 用户自定义 | M3 | 用户本地 | 自定义替代关系、私人配方笔记 | SQLite `ingredient_substitutes` 表 + 文档导入 |
| L3a 外部 API | M4 | TheCocktailDB（开源免费） | 200+ 配方扩充、材料图片 | 定时同步任务，`/api/lab/sync` |
| L3b ima 知识库 | M4 | ima（用户提供 Key） | 专业酒类配方、品鉴笔记 | ima adapter，按需拉取 |
| L4 UGC | M5 | 社区贡献 | 用户创作配方、改良变体 | 配方编辑器 + 审核流程 |
| L5 商业合作 | M5+ | 品牌方 | 品牌赞助配方、新品发布 | 合作接口，标注"商业内容" |

### 11.2 数据源接入契约

所有数据源统一通过"配方文档"格式入库（§2.1），在 frontmatter 增加来源标记：

```yaml
---
title: 莫吉托 Mojito
category: recipe
source: iba          # iba | user | thecocktaildb | ima | ugc | brand
source_id: "iba-042"
verified: true        # 是否经过审核
tags: [recipe, rum-base, summer]
---
```

**L3 同步机制**（M4）：
- 定时任务：每日 03:00 增量同步 TheCocktailDB 新配方
- 手动触发：管理后台"同步外部数据源"按钮
- 去重：按 `source + source_id` 唯一约束
- 审核：L3 同步的配方 `verified=false`，用户报告问题后人工审核

### 11.3 数据源治理

| 治理项 | 规则 |
|---|---|
| 优先级 | L1 > L2 > L3 > L4 > L5（同款配方多来源时，高优先级覆盖低优先级） |
| 冲突处理 | 配方内容冲突时保留 L1 IBA 官方版本，其他来源存为"变体" |
| 下架机制 | 用户可隐藏任意来源的配方（不影响知识库数据，仅影响实验室展示） |
| 数据回流 | 用户匹配行为匿名统计，用于优化热门排序（见 §12.4） |

## 12. 自动运营机制

实验室不只是静态查询工具，需有"活起来"的运营层。按里程碑梯度建设：

### 12.1 运营机制梯度

| 机制 | M3 | M4 | M5 |
|---|---|---|---|
| 配方使用统计 | ✅ 计数 | ✅ 排行 | ✅ 趋势分析 |
| 热门推荐 | ✅ Top 3 | ✅ 首页轮播 | ✅ 个性化 |
| 每日推荐 | — | ✅ 季节+随机 | ✅ 智能推荐 |
| 缺材料反馈 | — | ✅ 统计+优化替代表 | ✅ 自动学习 |
| 运营看板 | — | ✅ dashboard 扩展 | ✅ 完整指标 |

### 12.2 配方使用统计（M3）

每次配方被匹配或查看，记录到 `recipe_stats` 表：

```sql
CREATE TABLE recipe_stats (
    doc_id TEXT PRIMARY KEY,
    match_count INTEGER DEFAULT 0,    -- 被匹配命中次数
    view_count INTEGER DEFAULT 0,     -- 被点击查看次数
    last_matched_at TEXT,             -- 最近命中时间
    last_viewed_at TEXT               -- 最近查看时间
);
```

**统计时机**：
- 匹配命中：`/api/lab/match` 返回结果时，对 `full_match` + `partial_match` 的配方 `match_count + 1`
- 查看详情：用户点配方卡 [N] 引用跳转时，`view_count + 1`

### 12.3 热门推荐（M3）

实验室入口（首页 `index.html` 的分类入口区）展示 Top 3 热门配方：

```html
<div class="hot-recipes">
  <h3>本周热门配方</h3>
  <a href="doc-detail.html?chunk=42" class="hot-recipe">1. 马天尼 · 命中 128 次</a>
  <a href="doc-detail.html?chunk=58" class="hot-recipe">2. 莫吉托 · 命中 96 次</a>
  <a href="doc-detail.html?chunk=71" class="hot-recipe">3. 尼格罗尼 · 命中 84 次</a>
</div>
```

**排序规则**：`match_count` 降序，取前 3，`last_matched_at` 在 30 天内（避免历史数据陈旧）。

### 12.4 缺材料反馈循环（M4）

统计哪些材料最常"缺"，反向优化替代关系表：

```sql
CREATE TABLE missing_ingredient_stats (
    canonical TEXT,
    missing_count INTEGER DEFAULT 0,
    last_missing_at TEXT,
    PRIMARY KEY (canonical)
);
```

**运营动作**：
- 每周生成"高频缺失材料榜"，提示运营补充这些材料的替代关系
- 当某材料 `missing_count > 50` 且无预置替代时，在管理后台告警
- 用户点替代 chip `+` 加入的材料，若不在预置替代表，提示"是否保存为自定义替代？"

### 12.5 每日推荐（M4）

基于季节 + 热门 + 随机的每日推荐配方：

```python
def daily_recipe() -> Recipe:
    """每日推荐：季节权重 60% + 热门权重 30% + 随机 10%"""
    season = current_season()  # spring/summer/autumn/winter
    seasonal_pool = recipes_with_tag(f"{season}-recipe")
    hot_pool = top_n_recipes(20)
    # 季节池非空则 60% 概率从中选，否则回退热门池
    # 最终 10% 概率从全库随机
```

**季节标签**（配方 frontmatter）：
- `spring-recipe`：清新花香（吉姆雷特、白色佳人）
- `summer-recipe`：清爽冰凉（莫吉托、龙舌兰日出）
- `autumn-recipe`：温暖醇厚（古典鸡尾酒、曼哈顿）
- `winter-recipe`：热烈浓烈（热红酒、爱尔兰咖啡）

### 12.6 运营看板扩展（M4）

`dashboard.html` 增加"实验室健康度"卡片组：

```
┌─────────────────────────────────────┐
│ 实验室运营                           │
├─────────────────────────────────────┤
│ 配方总数：80    │ 本周匹配：1,240 次  │
│ Top 配方：马天尼 │ 高频缺失：君度(52) │
│ 替代表覆盖：68%  │ 用户自定义：12 条   │
└─────────────────────────────────────┘
```

**指标定义**：
- 替代表覆盖率 = 有替代关系的材料数 / 总材料数
- 高频缺失 = `missing_count` Top 1 材料
- 用户自定义 = L2 层 `source='user'` 的记录数

### 12.7 个性化推荐（M5）

基于用户历史匹配记录的个性化推荐：

- 记录用户每次匹配的"已选材料集合"
- 计算用户的"口味画像"（偏好基酒、偏好难度、常缺材料）
- 推荐"你可能喜欢"的配方（无需选材料，直接推荐）

**隐私边界**：匹配历史仅本地存储，不离开设备，不上报服务器（除非用户开启"贡献匿名数据"开关）。

## 13. 更新的决策记录

| ID | 决策 | 理由 |
|---|---|---|
| D25 | 页面形态：独立 lab.html 极简页 | 材料选择器是核心交互价值，独立路由便于入口曝光，但页面极简符合 P6 极简哲学 |
| D26 | 数据来源：本地 IBA 种子配方 | 开箱即用，与六大基酒种子同源，ima 暂缓 M4 |
| D27 | 材料选择器：搜索 + 分类平铺混合 | 兼顾新手（分类探索）与老手（搜索直达） |
| D28 | 结果展示：分组（现在就能做 / 差一种） | 兼顾即时动手与升级启发 |
| D29 | 替代关系：三层混合（预置 + 用户 + 外部） | L1 保证开箱即用，L2 灵活扩展，L3 远期探索 |
| D30 | 配方作为 recipe 分类文档进知识库 | 复用 M2 chunk + RAG，不新建独立存储，实验室是知识库的视图 |
| D31 | 数据源六层架构（L1-L5+治理） | 按 M3-M5 梯度开放，统一契约入库，优先级治理避免冲突 |
| D32 | 自动运营三层建设（统计/推荐/反馈） | M3 统计+热门打底，M4 季节推荐+反馈循环，M5 个性化 |
| D33 | 个性化数据仅本地不上报 | 隐私优先，匿名贡献需显式开关 |

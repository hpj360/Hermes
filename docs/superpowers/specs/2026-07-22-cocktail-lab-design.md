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

## 8. 交付物清单

### 8.1 文件清单

| 文件 | 动作 | 职责 |
|---|---|---|
| `src/hermes_kb/ingredients.py` | 新建 | 材料注册表 + 别名归一化 |
| `src/hermes_kb/substitutes.py` | 新建 | 三层替代关系表 + 合并查询 |
| `src/hermes_kb/recipe_match.py` | 新建 | 匹配算法 |
| `src/hermes_kb/seed_recipes.py` | 新建 | IBA 80 款配方种子数据 |
| `src/hermes_kb/api.py` | 修改 | 新增 `GET /api/lab/match` |
| `design/mockup/lab.html` | 新建 | 高保真设计稿 |
| `design/prototype/lab.html` | 新建 | 低保真原型 |
| `design/mockup/_components.css` | 修改 | 追加实验室组件样式 |
| `design/mockup/_nav.js` | 修改 | 导航新增 lab 入口 |
| `tests/test_lab.py` | 新建 | 匹配算法 + API 测试 |

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

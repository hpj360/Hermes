# 鸡尾酒实验室（M3）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 M2 私有酒类知识管家基础上，新增"鸡尾酒实验室"功能：用户选择手头材料 → 匹配可调制的鸡尾酒配方，配方结果复用 M2 引用溯源机制跳转文档详情页。

**Architecture:** 配方作为 `category=recipe` 的特殊文档类型沉淀进现有知识库，复用 chunk + RAG。实验室是知识库的一个"视图"，不新建独立存储。匹配算法在 Python 层遍历配方文档（O(n)），三层替代关系表（预置 + 用户自定义 + 外部同步预留）解决"缺材料"场景。前端独立 `lab.html` 极简页，复用 M2 的设计 token 和引用卡片样式。

**Tech Stack:** Python 3.11 / FastAPI / SQLModel / SQLite（WAL + FTS5） / 原生 HTML+CSS+JS（无构建工具）

---

## 文件结构

### 新建文件（后端）
- `src/hermes_kb/ingredients.py` — 材料注册表 + 别名归一化（4 大类：base_spirit/modifier/juice/garnish）
- `src/hermes_kb/substitutes.py` — 三层替代关系表（L1 预置 + L2 用户自定义 + L3 预留）+ 合并查询
- `src/hermes_kb/recipe_match.py` — 配方匹配算法（full_match / partial_match 分组）
- `src/hermes_kb/seed_recipes.py` — IBA 8 款经典配方种子数据（MVP 子集，可扩展）
- `src/hermes_kb/recipe_stats.py` — 配方使用统计（match_count / view_count）

### 新建文件（前端）
- `design/mockup/lab.html` — 高保真设计稿（材料选择器 + 配方卡片 + 分组结果）
- `design/prototype/lab.html` — 低保真原型（灰阶线框）

### 新建文件（测试）
- `tests/test_kb/test_lab.py` — 匹配算法 + API + 统计测试

### 修改文件
- `src/hermes_kb/models.py` — 新增 `RecipeStats` + `IngredientSubstitute` 表
- `src/hermes_kb/app.py` — 新增 `GET /api/lab/match` + `GET /api/lab/hot` + `POST /api/lab/view/{doc_id}` 端点
- `design/mockup/_nav.js` — 导航新增 lab 入口（位于"问答"与"文档"之间）
- `design/mockup/_components.css` — 追加实验室组件样式（材料 chip / 配方卡 / 替代推荐）
- `design/mockup/index.html` — 首页分类入口区增加 Top 3 热门配方

---

## Task 1: 数据模型 — RecipeStats + IngredientSubstitute 表

**Files:**
- Modify: `src/hermes_kb/models.py`（在文件末尾追加）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_kb/test_lab.py`，先写数据模型测试：

```python
"""鸡尾酒实验室测试：数据模型 + 匹配算法 + API + 统计。"""
from __future__ import annotations

import pytest
from sqlmodel import select


def test_recipe_stats_model(tmp_db):
    """RecipeStats 表可创建并写入。"""
    from hermes_kb.models import RecipeStats
    from hermes_kb.database import get_session

    with get_session() as session:
        stat = RecipeStats(doc_id="recipe-martini", match_count=5, view_count=12)
        session.add(stat)
        session.commit()
        session.refresh(stat)
        assert stat.doc_id == "recipe-martini"
        assert stat.match_count == 5
        assert stat.view_count == 12
        assert stat.last_matched_at is None


def test_ingredient_substitute_model(tmp_db):
    """IngredientSubstitute 表可创建并写入。"""
    from hermes_kb.models import IngredientSubstitute
    from hermes_kb.database import get_session

    with get_session() as session:
        sub = IngredientSubstitute(
            canonical="君度", substitute="橙味力娇酒", source="preset"
        )
        session.add(sub)
        session.commit()
        session.refresh(sub)
        assert sub.id is not None
        assert sub.canonical == "君度"
        assert sub.source == "preset"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_recipe_stats_model tests/test_kb/test_lab.py::test_ingredient_substitute_model -v`

Expected: FAIL with "cannot import name 'RecipeStats'"

- [ ] **Step 3: 实现数据模型**

在 `src/hermes_kb/models.py` 末尾追加（`PRESET_CATEGORIES` 之后）：

```python


class RecipeStats(SQLModel, table=True):
    """M3：配方使用统计。"""

    doc_id: str = Field(primary_key=True, max_length=64)
    match_count: int = Field(default=0)  # 被匹配命中次数
    view_count: int = Field(default=0)  # 被点击查看次数
    last_matched_at: datetime | None = Field(default=None)
    last_viewed_at: datetime | None = Field(default=None)


class IngredientSubstitute(SQLModel, table=True):
    """M3：材料替代关系（L2 用户自定义 + L1 预置镜像）。"""

    id: int | None = Field(default=None, primary_key=True)
    canonical: str = Field(index=True, max_length=64)  # 原材料标准名
    substitute: str = Field(max_length=64)  # 替代材料名
    source: str = Field(default="preset", max_length=16)  # preset | user
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_recipe_stats_model tests/test_kb/test_lab.py::test_ingredient_substitute_model -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /workspace && git add src/hermes_kb/models.py tests/test_kb/test_lab.py && git -c user.name=trae-agent -c user.email=agent@trae.local commit -m "feat(lab): 新增 RecipeStats + IngredientSubstitute 数据模型

- RecipeStats: 配方使用统计（match_count/view_count/时间戳）
- IngredientSubstitute: 材料替代关系（canonical/substitute/source）
- 两表支持 M3 实验室的统计与替代功能"
```

---

## Task 2: 材料注册表 — ingredients.py

**Files:**
- Create: `src/hermes_kb/ingredients.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_kb/test_lab.py` 追加：

```python


def test_ingredient_registry_canonical():
    """材料注册表能通过别名归一化到标准名。"""
    from hermes_kb.ingredients import canonicalize, INGREDIENT_REGISTRY

    assert canonicalize("gin") == "金酒"
    assert canonicalize("Gin") == "金酒"
    assert canonicalize("dry gin") == "金酒"
    assert canonicalize("杜松子酒") == "金酒"
    assert canonicalize("gordon's") == "金酒"
    # 未知材料返回原值
    assert canonicalize("未知材料") == "未知材料"


def test_ingredient_registry_category():
    """材料能正确分类。"""
    from hermes_kb.ingredients import get_category, INGREDIENT_REGISTRY

    assert get_category("金酒") == "base_spirit"
    assert get_category("味美思") == "modifier"
    assert get_category("柠檬汁") == "juice"
    assert get_category("橄榄") == "garnish"


def test_ingredient_registry_list_by_category():
    """能按分类列出所有材料。"""
    from hermes_kb.ingredients import list_by_category

    base_spirits = list_by_category("base_spirit")
    assert "金酒" in base_spirits
    assert "威士忌" in base_spirits
    assert len(base_spirits) >= 6  # 六大基酒


def test_ingredient_registry_all_canonical():
    """所有标准名都能被列出。"""
    from hermes_kb.ingredients import all_canonical

    names = all_canonical()
    assert "金酒" in names
    assert "君度" in names
    assert "柠檬汁" in names
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_ingredient_registry_canonical tests/test_kb/test_lab.py::test_ingredient_registry_category tests/test_kb/test_lab.py::test_ingredient_registry_list_by_category tests/test_kb/test_lab.py::test_ingredient_registry_all_canonical -v`

Expected: FAIL with "No module named 'hermes_kb.ingredients'"

- [ ] **Step 3: 实现材料注册表**

创建 `src/hermes_kb/ingredients.py`：

```python
"""材料注册表 + 别名归一化。

4 大类：
- base_spirit 基酒（金酒/威士忌/朗姆/龙舌兰/白兰地/伏特加）
- modifier 辅料（味美思/苦精/糖浆/君度/利口酒/汤力水/苏打水）
- juice 果汁（柠檬汁/青柠汁/橙汁/蔓越莓汁/菠萝汁）
- garnish 装饰（橄榄/柠檬片/薄荷叶/樱桃/橙皮）
"""
from __future__ import annotations

INGREDIENT_REGISTRY: dict[str, dict] = {
    # === 基酒 ===
    "gin": {
        "canonical": "金酒",
        "aliases": ["gin", "dry gin", "london dry", "杜松子酒", "gordon's", "gordon"],
        "category": "base_spirit",
    },
    "whiskey": {
        "canonical": "威士忌",
        "aliases": ["whiskey", "whisky", "scotch", "bourbon", "rye", "威士忌"],
        "category": "base_spirit",
    },
    "rum": {
        "canonical": "朗姆酒",
        "aliases": ["rum", "white rum", "dark rum", "朗姆", "朗姆酒"],
        "category": "base_spirit",
    },
    "tequila": {
        "canonical": "龙舌兰",
        "aliases": ["tequila", "龙舌兰"],
        "category": "base_spirit",
    },
    "brandy": {
        "canonical": "白兰地",
        "aliases": ["brandy", "cognac", "白兰地", "干邑"],
        "category": "base_spirit",
    },
    "vodka": {
        "canonical": "伏特加",
        "aliases": ["vodka", "伏特加"],
        "category": "base_spirit",
    },
    # === 辅料 ===
    "vermouth": {
        "canonical": "味美思",
        "aliases": ["vermouth", "dry vermouth", "sweet vermouth", "味美思", "苦艾酒"],
        "category": "modifier",
    },
    "campari": {
        "canonical": "金巴利",
        "aliases": ["campari", "金巴利"],
        "category": "modifier",
    },
    "sugar_syrup": {
        "canonical": "糖浆",
        "aliases": ["sugar syrup", "simple syrup", "syrup", "糖浆", "糖水"],
        "category": "modifier",
    },
    "cointreau": {
        "canonical": "君度",
        "aliases": ["cointreau", "triple sec", "橙味力娇酒", "君度"],
        "category": "modifier",
    },
    "angostura": {
        "canonical": "苦精",
        "aliases": ["angostura", "bitters", "苦精", "安高天娜"],
        "category": "modifier",
    },
    "tonic": {
        "canonical": "汤力水",
        "aliases": ["tonic", "tonic water", "汤力水"],
        "category": "modifier",
    },
    "soda": {
        "canonical": "苏打水",
        "aliases": ["soda", "soda water", "苏打水", "气泡水"],
        "category": "modifier",
    },
    "cola": {
        "canonical": "可乐",
        "aliases": ["cola", "coke", "可乐"],
        "category": "modifier",
    },
    "ginger_beer": {
        "canonical": "姜啤",
        "aliases": ["ginger beer", "姜啤"],
        "category": "modifier",
    },
    # === 果汁 ===
    "lemon_juice": {
        "canonical": "柠檬汁",
        "aliases": ["lemon juice", "柠檬汁"],
        "category": "juice",
    },
    "lime_juice": {
        "canonical": "青柠汁",
        "aliases": ["lime juice", "青柠汁", "莱姆汁"],
        "category": "juice",
    },
    "orange_juice": {
        "canonical": "橙汁",
        "aliases": ["orange juice", "橙汁", "橘子汁"],
        "category": "juice",
    },
    "cranberry_juice": {
        "canonical": "蔓越莓汁",
        "aliases": ["cranberry juice", "蔓越莓汁"],
        "category": "juice",
    },
    "pineapple_juice": {
        "canonical": "菠萝汁",
        "aliases": ["pineapple juice", "菠萝汁"],
        "category": "juice",
    },
    "tomato_juice": {
        "canonical": "番茄汁",
        "aliases": ["tomato juice", "番茄汁"],
        "category": "juice",
    },
    # === 装饰 ===
    "olive": {
        "canonical": "橄榄",
        "aliases": ["olive", "橄榄"],
        "category": "garnish",
    },
    "lemon_slice": {
        "canonical": "柠檬片",
        "aliases": ["lemon slice", "lemon", "柠檬片", "柠檬"],
        "category": "garnish",
    },
    "mint": {
        "canonical": "薄荷叶",
        "aliases": ["mint", "mint leaves", "薄荷叶", "薄荷"],
        "category": "garnish",
    },
    "cherry": {
        "canonical": "樱桃",
        "aliases": ["cherry", "maraschino cherry", "樱桃"],
        "category": "garnish",
    },
    "orange_peel": {
        "canonical": "橙皮",
        "aliases": ["orange peel", "橙皮"],
        "category": "garnish",
    },
}

# 反向索引：alias(小写) → canonical
_ALIAS_INDEX: dict[str, str] = {}
for _key, _info in INGREDIENT_REGISTRY.items():
    _canon = _info["canonical"]
    # 标准名本身也加入索引
    _ALIAS_INDEX[_canon.lower()] = _canon
    for _alias in _info["aliases"]:
        _ALIAS_INDEX[_alias.lower()] = _canon


def canonicalize(name: str) -> str:
    """将别名归一化为标准名。未知材料返回原值。"""
    if not name:
        return name
    return _ALIAS_INDEX.get(name.strip().lower(), name.strip())


def get_category(canonical: str) -> str | None:
    """根据标准名获取分类。"""
    for _info in INGREDIENT_REGISTRY.values():
        if _info["canonical"] == canonical:
            return _info["category"]
    return None


def list_by_category(category: str) -> list[str]:
    """列出某分类下所有材料标准名。"""
    return [
        info["canonical"]
        for info in INGREDIENT_REGISTRY.values()
        if info["category"] == category
    ]


def all_canonical() -> list[str]:
    """列出所有材料标准名。"""
    return [info["canonical"] for info in INGREDIENT_REGISTRY.values()]
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_ingredient_registry_canonical tests/test_kb/test_lab.py::test_ingredient_registry_category tests/test_kb/test_lab.py::test_ingredient_registry_list_by_category tests/test_kb/test_lab.py::test_ingredient_registry_all_canonical -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /workspace && git add src/hermes_kb/ingredients.py tests/test_kb/test_lab.py && git -c user.name=trae-agent -c user.email=agent@trae.local commit -m "feat(lab): 材料注册表 + 别名归一化

- INGREDIENT_REGISTRY: 26 种材料，4 大类（基酒/辅料/果汁/装饰）
- canonicalize(): 别名 → 标准名（支持中英文）
- get_category() / list_by_category() / all_canonical()"
```

---

## Task 3: 三层替代关系表 — substitutes.py

**Files:**
- Create: `src/hermes_kb/substitutes.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_kb/test_lab.py` 追加：

```python


def test_substitutes_preset():
    """L1 预置替代关系可查询。"""
    from hermes_kb.substitutes import get_substitutes_preset

    subs = get_substitutes_preset("君度")
    assert "橙味力娇酒" in subs
    assert "干库拉索" in subs


def test_substitutes_merged_with_user(tmp_db):
    """L1 预置 + L2 用户自定义能合并查询。"""
    from hermes_kb.substitutes import get_substitutes, add_user_substitute
    from hermes_kb.database import get_session
    from hermes_kb.models import IngredientSubstitute

    # 先确保预置有
    preset_subs = get_substitutes("君度")
    assert "橙味力娇酒" in preset_subs

    # 添加用户自定义
    add_user_substitute("君度", "自制橙皮酒")
    merged = get_substitutes("君度")
    assert "橙味力娇酒" in merged
    assert "自制橙皮酒" in merged


def test_substitutes_remove_user(tmp_db):
    """可删除用户自定义替代（不影响预置）。"""
    from hermes_kb.substitutes import (
        add_user_substitute,
        remove_user_substitute,
        get_substitutes,
    )

    add_user_substitute("君度", "临时替代")
    assert "临时替代" in get_substitutes("君度")

    remove_user_substitute("君度", "临时替代")
    assert "临时替代" not in get_substitutes("君度")
    # 预置仍在
    assert "橙味力娇酒" in get_substitutes("君度")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_substitutes_preset tests/test_kb/test_lab.py::test_substitutes_merged_with_user tests/test_kb/test_lab.py::test_substitutes_remove_user -v`

Expected: FAIL with "No module named 'hermes_kb.substitutes'"

- [ ] **Step 3: 实现替代关系表**

创建 `src/hermes_kb/substitutes.py`：

```python
"""三层替代关系表（L1 预置 + L2 用户自定义 + L3 预留）。

- L1: 预置 IBA 替代关系（本文件常量）
- L2: 用户自定义（持久化到 SQLite ingredient_substitutes 表）
- L3: 外部同步（M4 远期，接口预留）
"""
from __future__ import annotations

from datetime import datetime

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import IngredientSubstitute

# L1: 预置 IBA 替代关系
SUBSTITUTES_PRESET: dict[str, list[str]] = {
    "君度": ["干库拉索", "橙味力娇酒"],
    "青柠汁": ["柠檬汁"],
    "糖浆": ["蜂蜜糖浆", "白糖水"],
    "汤力水": ["苏打水"],  # 简化提示，实际风味不同
    "金巴利": ["Aperol"],
    "樱桃": ["酒渍樱桃"],
    "苦精": ["橙味苦精"],
    "蔓越莓汁": ["红莓汁"],
}


def get_substitutes_preset(canonical: str) -> list[str]:
    """查询 L1 预置替代关系。"""
    return SUBSTITUTES_PRESET.get(canonical, [])


def get_substitutes(canonical: str) -> list[str]:
    """合并查询 L1 + L2 替代关系。"""
    result = list(get_substitutes_preset(canonical))
    with get_session() as session:
        rows = session.exec(
            select(IngredientSubstitute).where(
                IngredientSubstitute.canonical == canonical
            )
        ).all()
        for row in rows:
            if row.substitute not in result:
                result.append(row.substitute)
    return result


def add_user_substitute(canonical: str, substitute: str) -> None:
    """添加 L2 用户自定义替代关系。"""
    canonical = canonical.strip()
    substitute = substitute.strip()
    if not canonical or not substitute:
        return
    with get_session() as session:
        # 去重检查
        existing = session.exec(
            select(IngredientSubstitute).where(
                IngredientSubstitute.canonical == canonical,
                IngredientSubstitute.substitute == substitute,
            )
        ).first()
        if existing:
            return
        session.add(
            IngredientSubstitute(
                canonical=canonical, substitute=substitute, source="user"
            )
        )
        session.commit()


def remove_user_substitute(canonical: str, substitute: str) -> None:
    """删除 L2 用户自定义替代（仅删 source='user'）。"""
    with get_session() as session:
        rows = session.exec(
            select(IngredientSubstitute).where(
                IngredientSubstitute.canonical == canonical,
                IngredientSubstitute.substitute == substitute,
                IngredientSubstitute.source == "user",
            )
        ).all()
        for row in rows:
            session.delete(row)
        session.commit()


def list_all_substitutes() -> dict[str, list[str]]:
    """列出所有材料的替代关系（L1+L2 合并）。用于运营看板覆盖率统计。"""
    all_subs: dict[str, set[str]] = {}
    # L1
    for canon, subs in SUBSTITUTES_PRESET.items():
        all_subs.setdefault(canon, set()).update(subs)
    # L2
    with get_session() as session:
        rows = session.exec(select(IngredientSubstitute)).all()
        for row in rows:
            all_subs.setdefault(row.canonical, set()).add(row.substitute)
    return {k: sorted(v) for k, v in all_subs.items()}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_substitutes_preset tests/test_kb/test_lab.py::test_substitutes_merged_with_user tests/test_kb/test_lab.py::test_substitutes_remove_user -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /workspace && git add src/hermes_kb/substitutes.py tests/test_kb/test_lab.py && git -c user.name=trae-agent -c user.email=agent@trae.local commit -m "feat(lab): 三层替代关系表

- L1 预置: 8 组 IBA 替代关系（君度/青柠汁/糖浆等）
- L2 用户自定义: SQLite 持久化，add/remove
- get_substitutes(): L1+L2 合并查询
- list_all_substitutes(): 覆盖率统计用"
```

---

## Task 4: IBA 配方种子数据 — seed_recipes.py

**Files:**
- Create: `src/hermes_kb/seed_recipes.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_kb/test_lab.py` 追加：

```python


def test_seed_recipes_structure():
    """种子配方数据结构完整。"""
    from hermes_kb.seed_recipes import SEED_RECIPES

    assert len(SEED_RECIPES) >= 8  # 至少 8 款 IBA 经典

    recipe = SEED_RECIPES[0]
    assert "title" in recipe
    assert "content" in recipe
    assert "base_spirit" in recipe
    assert "difficulty" in recipe
    assert "ingredients" in recipe  # 标准化材料名列表
    assert isinstance(recipe["ingredients"], list)
    assert len(recipe["ingredients"]) > 0


def test_seed_recipes_martini():
    """马天尼配方内容正确。"""
    from hermes_kb.seed_recipes import SEED_RECIPES

    martini = next(r for r in SEED_RECIPES if "马天尼" in r["title"])
    assert "金酒" in martini["ingredients"]
    assert "味美思" in martini["ingredients"]
    assert martini["base_spirit"] == "gin"
    assert martini["difficulty"] == "easy"


def test_seed_recipes_all_ingredients_canonical():
    """所有配方的材料都是标准名（在注册表中）。"""
    from hermes_kb.seed_recipes import SEED_RECIPES
    from hermes_kb.ingredients import all_canonical

    valid_names = set(all_canonical())
    for recipe in SEED_RECIPES:
        for ing in recipe["ingredients"]:
            assert ing in valid_names, (
                f"配方 {recipe['title']} 的材料 {ing} 不在注册表中"
            )
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_seed_recipes_structure tests/test_kb/test_lab.py::test_seed_recipes_martini tests/test_kb/test_lab.py::test_seed_recipes_all_ingredients_canonical -v`

Expected: FAIL with "No module named 'hermes_kb.seed_recipes'"

- [ ] **Step 3: 实现种子配方数据**

创建 `src/hermes_kb/seed_recipes.py`：

```python
"""IBA 经典鸡尾酒配方种子数据（M3 MVP 8 款）。

每款配方作为 Markdown 文档导入知识库（category=recipe）。
ingredients 字段为标准化材料名列表（用于匹配算法）。
"""
from __future__ import annotations

SEED_RECIPES: list[dict] = [
    {
        "title": "马天尼 Martini",
        "base_spirit": "gin",
        "difficulty": "easy",
        "ingredients": ["金酒", "味美思", "橄榄"],
        "content": """# 马天尼 Martini

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
""",
    },
    {
        "title": "莫吉托 Mojito",
        "base_spirit": "rum",
        "difficulty": "easy",
        "ingredients": ["朗姆酒", "青柠汁", "糖浆", "薄荷叶", "苏打水"],
        "content": """# 莫吉托 Mojito

## 配方
- 白朗姆酒 45ml
- 青柠汁 20ml
- 糖浆 15ml
- 薄荷叶 8-10 片
- 苏打水 适量

## 步骤
1. 薄荷叶与糖浆放入杯中轻轻捣压
2. 加入青柠汁与朗姆酒
3. 加碎冰至八分满
4. 注入苏打水至满
5. 搅拌提升，以薄荷枝装饰

## 风味
清新、薄荷凉爽、酸甜平衡。夏日经典长饮。
""",
    },
    {
        "title": "尼格罗尼 Negroni",
        "base_spirit": "gin",
        "difficulty": "easy",
        "ingredients": ["金酒", "金巴利", "味美思", "橙皮"],
        "content": """# 尼格罗尼 Negroni

## 配方
- 金酒 30ml
- 金巴利 30ml
- 甜味美思 30ml
- 橙皮 1 片（装饰）

## 步骤
1. 古典杯加冰
2. 倒入金酒、金巴利、甜味美思
3. 搅拌 20 秒
4. 橙皮扭拧释放精油，装饰

## 风味
苦甜平衡、药草香、酒体饱满。等比经典。
""",
    },
    {
        "title": "玛格丽特 Margarita",
        "base_spirit": "tequila",
        "difficulty": "medium",
        "ingredients": ["龙舌兰", "君度", "青柠汁", "柠檬片"],
        "content": """# 玛格丽特 Margarita

## 配方
- 龙舌兰 50ml
- 君度 20ml
- 青柠汁 20ml
- 盐边 + 柠檬片装饰

## 步骤
1. 杯口蘸半圈盐边
2. 冰块加入摇酒壶
3. 倒入龙舌兰、君度、青柠汁
4. 摇匀 15 秒
5. 滤入盐边杯，柠檬片装饰

## 风味
酸甜咸三味平衡，龙舌兰植物香突出。墨西哥国饮。
""",
    },
    {
        "title": "古典鸡尾酒 Old Fashioned",
        "base_spirit": "whiskey",
        "difficulty": "easy",
        "ingredients": ["威士忌", "糖浆", "苦精", "橙皮"],
        "content": """# 古典鸡尾酒 Old Fashioned

## 配方
- 波本威士忌 60ml
- 糖浆 5ml
- 苦精 2 滴
- 橙皮 1 片（装饰）

## 步骤
1. 古典杯加糖浆与苦精
2. 加冰块
3. 倒入威士忌
4. 搅拌 20 秒
5. 橙皮释放精油装饰

## 风味
醇厚、威士忌主导、微甜。最古老的经典配方之一。
""",
    },
    {
        "title": "白色佳人 White Lady",
        "base_spirit": "gin",
        "difficulty": "medium",
        "ingredients": ["金酒", "君度", "柠檬汁"],
        "content": """# 白色佳人 White Lady

## 配方
- 金酒 40ml
- 君度 15ml
- 柠檬汁 20ml

## 步骤
1. 摇酒壶加冰
2. 倒入金酒、君度、柠檬汁
3. 摇匀 15 秒
4. 滤冰倒入冰镇马天尼杯

## 风味
酸香优雅、杜松与橙香交织。酸酒变体经典。
""",
    },
    {
        "title": "龙舌兰日出 Tequila Sunrise",
        "base_spirit": "tequila",
        "difficulty": "easy",
        "ingredients": ["龙舌兰", "橙汁", "糖浆"],
        "content": """# 龙舌兰日出 Tequila Sunrise

## 配方
- 龙舌兰 45ml
- 橙汁 90ml
- 红石榴糖浆 15ml

## 步骤
1. 高球杯加冰
2. 倒入龙舌兰与橙汁，搅拌
3. 沿杯壁缓缓倒入红石榴糖浆
4. 使其沉底形成日出渐层
5. 饮用前搅拌

## 风味
果香甜美、视觉渐层。日出色彩由此得名。
""",
    },
    {
        "title": "血腥玛丽 Bloody Mary",
        "base_spirit": "vodka",
        "difficulty": "easy",
        "ingredients": ["伏特加", "番茄汁", "柠檬汁", "苦精"],
        "content": """# 血腥玛丽 Bloody Mary

## 配方
- 伏特加 45ml
- 番茄汁 90ml
- 柠檬汁 15ml
- 苦精 2 滴
- 盐、黑胡椒、辣椒酱适量

## 步骤
1. 高球杯加冰
2. 倒入伏特加、番茄汁、柠檬汁
3. 加苦精与调味料
4. 搅拌均匀
5. 芹菜枝或柠檬片装饰

## 风味
咸鲜辛辣、番茄浓郁。宿醉救星传说。
""",
    },
]
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_seed_recipes_structure tests/test_kb/test_lab.py::test_seed_recipes_martini tests/test_kb/test_lab.py::test_seed_recipes_all_ingredients_canonical -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /workspace && git add src/hermes_kb/seed_recipes.py tests/test_kb/test_lab.py && git -c user.name=trae-agent -c user.email=agent@trae.local commit -m "feat(lab): IBA 经典配方种子数据

- 8 款 IBA 经典：马天尼/莫吉托/尼格罗尼/玛格丽特/古典/白色佳人/龙舌兰日出/血腥玛丽
- 每款含 title/base_spirit/difficulty/ingredients/content
- ingredients 使用材料注册表标准名
- content 为 Markdown 格式，可直接导入知识库"
```

---

## Task 5: 配方匹配算法 — recipe_match.py

**Files:**
- Create: `src/hermes_kb/recipe_match.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_kb/test_lab.py` 追加：

```python


@pytest.fixture
def seeded_recipes(tmp_db):
    """导入种子配方的 ImportService。"""
    from hermes_kb.rag import ImportService
    from hermes_kb.seed_recipes import SEED_RECIPES

    importer = ImportService()
    for recipe in SEED_RECIPES:
        importer.import_text(
            content=recipe["content"],
            title=recipe["title"],
            source_type="seed",
            file_type="md",
        )
        # 设置 category=recipe
        from hermes_kb.database import get_session
        from hermes_kb.models import Document
        from sqlmodel import select

        with get_session() as session:
            doc = session.exec(
                select(Document).where(Document.title == recipe["title"])
            ).first()
            if doc:
                doc.category = "recipe"
                session.add(doc)
                session.commit()
    return importer


def test_match_full(seeded_recipes):
    """材料齐全的配方进 full_match。"""
    from hermes_kb.recipe_match import match_recipes

    # 马天尼：金酒 + 味美思 + 橄榄
    result = match_recipes({"金酒", "味美思", "橄榄"})
    titles = [r["title"] for r in result["full_match"]]
    assert "马天尼 Martini" in titles


def test_match_partial(seeded_recipes):
    """缺 1-2 种材料的配方进 partial_match。"""
    from hermes_kb.recipe_match import match_recipes

    # 白色佳人需要金酒+君度+柠檬汁，只给金酒+柠檬汁
    result = match_recipes({"金酒", "柠檬汁"})
    partial_titles = [r["title"] for r in result["partial_match"]]
    assert "白色佳人 White Lady" in partial_titles
    # 验证缺材料
    white_lady = next(r for r in result["partial_match"] if "白色佳人" in r["title"])
    assert "君度" in white_lady["missing"]


def test_match_substitute_resolves(seeded_recipes):
    """有替代品时，缺的材料算"不缺"。"""
    from hermes_kb.recipe_match import match_recipes

    # 玛格丽特需要龙舌兰+君度+青柠汁
    # 君度可用橙味力娇酒替代
    result = match_recipes({"龙舌兰", "橙味力娇酒", "青柠汁"})
    titles = [r["title"] for r in result["full_match"]]
    assert "玛格丽特 Margarita" in titles


def test_match_skip_three_plus_missing(seeded_recipes):
    """缺 3+ 种材料的配方不返回。"""
    from hermes_kb.recipe_match import match_recipes

    # 只给金酒，大多数配方缺 2+ 种
    result = match_recipes({"金酒"})
    all_titles = [r["title"] for r in result["full_match"]] + [
        r["title"] for r in result["partial_match"]
    ]
    # 莫吉托缺 4 种（朗姆/青柠/糖浆/薄荷/苏打），不应出现
    assert "莫吉托 Mojito" not in all_titles


def test_match_empty_input(seeded_recipes):
    """空材料集合返回空结果。"""
    from hermes_kb.recipe_match import match_recipes

    result = match_recipes(set())
    assert result["full_match"] == []
    assert result["partial_match"] == []
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_match_full tests/test_kb/test_lab.py::test_match_partial tests/test_kb/test_lab.py::test_match_substitute_resolves tests/test_kb/test_lab.py::test_match_skip_three_plus_missing tests/test_kb/test_lab.py::test_match_empty_input -v`

Expected: FAIL with "No module named 'hermes_kb.recipe_match'"

- [ ] **Step 3: 实现匹配算法**

创建 `src/hermes_kb/recipe_match.py`：

```python
"""配方匹配算法。

输入：用户已有的材料集合（标准名）
输出：分两组返回
- full_match: 缺 0 种（含替代命中）
- partial_match: 缺 1-2 种
- 缺 3+ 种不返回

排序规则：
- full_match 按材料命中数降序
- partial_match 按缺少数升序
"""
from __future__ import annotations

from typing import Any

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import Chunk, Document
from hermes_kb.substitutes import get_substitutes


def _load_recipes() -> list[dict[str, Any]]:
    """从知识库加载所有 category=recipe 的配方文档。"""
    recipes: list[dict[str, Any]] = []
    with get_session() as session:
        docs = session.exec(
            select(Document).where(Document.category == "recipe")
        ).all()
        for doc in docs:
            # 取第一个 chunk 的 rowid 作为引用锚点
            first_chunk = session.exec(
                select(Chunk)
                .where(Chunk.doc_id == doc.doc_id)
                .order_by(Chunk.idx)
            ).first()
            recipes.append(
                {
                    "doc_id": doc.doc_id,
                    "title": doc.title,
                    "chunk_rowid": first_chunk.id if first_chunk else None,
                    "content": doc.content or "",
                }
            )
    return recipes


def _extract_ingredients_from_seed(title: str) -> set[str]:
    """从种子配方标题反查材料（种子数据固定，用查表方式）。

    生产环境应从 frontmatter 或 chunk 解析，此处用 seed_recipes 映射。
    """
    from hermes_kb.seed_recipes import SEED_RECIPES

    for recipe in SEED_RECIPES:
        if recipe["title"] == title:
            return set(recipe["ingredients"])
    return set()


def _parse_ingredients_from_content(content: str) -> set[str]:
    """从配方内容解析材料（基于材料注册表匹配）。

    简化策略：扫描 content，命中注册表标准名则加入。
    """
    from hermes_kb.ingredients import all_canonical

    found: set[str] = set()
    for name in all_canonical():
        if name in content:
            found.add(name)
    return found


def _get_recipe_ingredients(recipe: dict[str, Any]) -> set[str]:
    """获取配方的材料集合（优先种子映射，回退内容解析）。"""
    # 优先从种子数据查
    ingredients = _extract_ingredients_from_seed(recipe["title"])
    if ingredients:
        return ingredients
    # 回退：从内容解析
    return _parse_ingredients_from_content(recipe["content"])


def _resolve_missing(
    missing: set[str], user_ingredients: set[str]
) -> list[str]:
    """检查缺失材料是否有用户已有的替代品。

    返回真正缺失的材料列表（替代品命中算"不缺"）。
    """
    truly_missing: list[str] = []
    for m in missing:
        subs = set(get_substitutes(m))
        if subs & user_ingredients:
            continue  # 有替代品，不算缺
        truly_missing.append(m)
    return truly_missing


def match_recipes(
    user_ingredients: set[str], limit: int = 20
) -> dict[str, list[dict[str, Any]]]:
    """材料集合 → 配方匹配，分两组返回。

    Args:
        user_ingredients: 用户已有的材料标准名集合
        limit: 每组最多返回数（默认 20）

    Returns:
        {"full_match": [...], "partial_match": [...]}
        - full_match 项: {title, doc_id, chunk_rowid, ingredients, base_spirit, difficulty, match_count}
        - partial_match 项: 同上 + {missing, missing_count}
    """
    if not user_ingredients:
        return {"full_match": [], "partial_match": []}

    from hermes_kb.seed_recipes import SEED_RECIPES

    # 种子元信息映射（base_spirit / difficulty / ingredients）
    seed_meta: dict[str, dict] = {}
    for r in SEED_RECIPES:
        seed_meta[r["title"]] = r

    recipes = _load_recipes()
    full_match: list[dict[str, Any]] = []
    partial_match: list[dict[str, Any]] = []

    for recipe in recipes:
        title = recipe["title"]
        meta = seed_meta.get(title, {})
        recipe_ingredients = (
            set(meta.get("ingredients", [])) or _get_recipe_ingredients(recipe)
        )
        if not recipe_ingredients:
            continue

        missing = recipe_ingredients - user_ingredients
        truly_missing = _resolve_missing(missing, user_ingredients)

        # 构建材料详情
        ingredient_details = []
        for ing in sorted(recipe_ingredients):
            have = ing in user_ingredients
            detail: dict[str, Any] = {"name": ing, "have": have}
            if not have:
                subs = get_substitutes(ing)
                if subs:
                    detail["substitutes"] = subs
            ingredient_details.append(detail)

        base = {
            "title": title,
            "doc_id": recipe["doc_id"],
            "chunk_rowid": recipe["chunk_rowid"],
            "ingredients": ingredient_details,
            "base_spirit": meta.get("base_spirit", ""),
            "difficulty": meta.get("difficulty", ""),
        }

        if len(truly_missing) == 0:
            base["match_count"] = len(recipe_ingredients & user_ingredients)
            full_match.append(base)
        elif len(truly_missing) <= 2:
            base["missing"] = truly_missing
            base["missing_count"] = len(truly_missing)
            partial_match.append(base)

    # 排序
    full_match.sort(key=lambda x: x.get("match_count", 0), reverse=True)
    partial_match.sort(key=lambda x: x.get("missing_count", 0))

    return {
        "full_match": full_match[:limit],
        "partial_match": partial_match[:limit],
    }
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_match_full tests/test_kb/test_lab.py::test_match_partial tests/test_kb/test_lab.py::test_match_substitute_resolves tests/test_kb/test_lab.py::test_match_skip_three_plus_missing tests/test_kb/test_lab.py::test_match_empty_input -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /workspace && git add src/hermes_kb/recipe_match.py tests/test_kb/test_lab.py && git -c user.name=trae-agent -c user.email=agent@trae.local commit -m "feat(lab): 配方匹配算法

- match_recipes(): 材料集合 → full_match + partial_match 分组
- 替代品命中算"不缺"（_resolve_missing）
- 缺 3+ 种不返回，避免噪声
- full_match 按命中数降序，partial_match 按缺少数升序
- 优先种子数据映射材料，回退内容解析"
```

---

## Task 6: 配方使用统计 — recipe_stats.py

**Files:**
- Create: `src/hermes_kb/recipe_stats.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_kb/test_lab.py` 追加：

```python


def test_stats_increment_match(seeded_recipes):
    """匹配命中时 match_count +1。"""
    from hermes_kb.recipe_stats import increment_match_count, get_stats
    from hermes_kb.recipe_match import match_recipes

    result = match_recipes({"金酒", "味美思", "橄榄"})
    martini = next(r for r in result["full_match"] if "马天尼" in r["title"])
    doc_id = martini["doc_id"]

    increment_match_count(doc_id)
    increment_match_count(doc_id)
    stat = get_stats(doc_id)
    assert stat is not None
    assert stat["match_count"] == 2
    assert stat["last_matched_at"] is not None


def test_stats_increment_view(seeded_recipes):
    """查看详情时 view_count +1。"""
    from hermes_kb.recipe_stats import increment_view_count, get_stats

    # 先创建一个配方文档
    from hermes_kb.rag import ImportService

    importer = ImportService()
    result = importer.import_text(
        content="# 测试配方\n金酒 60ml", title="测试配方", source_type="test"
    )
    doc_id = result["doc_id"]

    increment_view_count(doc_id)
    stat = get_stats(doc_id)
    assert stat["view_count"] == 1


def test_stats_hot_recipes(seeded_recipes):
    """热门配方按 match_count 降序。"""
    from hermes_kb.recipe_stats import increment_match_count, get_hot_recipes
    from hermes_kb.recipe_match import match_recipes

    # 给马天尼 +3，尼格罗尼 +1
    result = match_recipes({"金酒", "味美思", "橄榄"})
    martini = next(r for r in result["full_match"] if "马天尼" in r["title"])
    for _ in range(3):
        increment_match_count(martini["doc_id"])

    result = match_recipes({"金酒", "金巴利", "味美思"})
    negroni = next(r for r in result["full_match"] if "尼格罗尼" in r["title"])
    increment_match_count(negroni["doc_id"])

    hot = get_hot_recipes(limit=10, days=30)
    assert len(hot) >= 2
    # 马天尼应排第一
    assert hot[0]["match_count"] >= 3
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_stats_increment_match tests/test_kb/test_lab.py::test_stats_increment_view tests/test_kb/test_lab.py::test_stats_hot_recipes -v`

Expected: FAIL with "No module named 'hermes_kb.recipe_stats'"

- [ ] **Step 3: 实现统计模块**

创建 `src/hermes_kb/recipe_stats.py`：

```python
"""配方使用统计（M3 运营层）。

统计时机：
- 匹配命中：/api/lab/match 返回时对 full_match + partial_match 配方 match_count +1
- 查看详情：用户点引用跳转时 view_count +1
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text as sa_text
from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import Document, RecipeStats


def increment_match_count(doc_id: str) -> None:
    """匹配命中时 match_count +1，更新 last_matched_at。"""
    with get_session() as session:
        stat = session.get(RecipeStats, doc_id)
        now = datetime.utcnow()
        if stat:
            stat.match_count += 1
            stat.last_matched_at = now
        else:
            stat = RecipeStats(
                doc_id=doc_id, match_count=1, last_matched_at=now
            )
        session.add(stat)
        session.commit()


def increment_view_count(doc_id: str) -> None:
    """查看详情时 view_count +1，更新 last_viewed_at。"""
    with get_session() as session:
        stat = session.get(RecipeStats, doc_id)
        now = datetime.utcnow()
        if stat:
            stat.view_count += 1
            stat.last_viewed_at = now
        else:
            stat = RecipeStats(
                doc_id=doc_id, view_count=1, last_viewed_at=now
            )
        session.add(stat)
        session.commit()


def get_stats(doc_id: str) -> dict[str, Any] | None:
    """查询单个配方的统计数据。"""
    with get_session() as session:
        stat = session.get(RecipeStats, doc_id)
        if not stat:
            return None
        return {
            "doc_id": stat.doc_id,
            "match_count": stat.match_count,
            "view_count": stat.view_count,
            "last_matched_at": stat.last_matched_at.isoformat()
            if stat.last_matched_at
            else None,
            "last_viewed_at": stat.last_viewed_at.isoformat()
            if stat.last_viewed_at
            else None,
        }


def get_hot_recipes(limit: int = 3, days: int = 30) -> list[dict[str, Any]]:
    """获取热门配方（按 match_count 降序，限时间范围）。

    Args:
        limit: 返回数量
        days: 时间范围（天），仅统计 last_matched_at 在此范围内的
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    with get_session() as session:
        # 联查 Document 拿 title + chunk_rowid
        rows = session.exec(
            select(RecipeStats, Document)
            .join(Document, RecipeStats.doc_id == Document.doc_id)
            .where(RecipeStats.match_count > 0)
            .where(RecipeStats.last_matched_at >= cutoff)
            .order_by(RecipeStats.match_count.desc())
            .limit(limit)
        ).all()
        results: list[dict[str, Any]] = []
        for stat, doc in rows:
            # 取第一个 chunk 的 rowid
            from hermes_kb.models import Chunk

            first_chunk = session.exec(
                select(Chunk)
                .where(Chunk.doc_id == doc.doc_id)
                .order_by(Chunk.idx)
            ).first()
            results.append(
                {
                    "title": doc.title,
                    "doc_id": doc.doc_id,
                    "chunk_rowid": first_chunk.id if first_chunk else None,
                    "match_count": stat.match_count,
                    "last_matched_at": stat.last_matched_at.isoformat()
                    if stat.last_matched_at
                    else None,
                }
            )
        return results
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_stats_increment_match tests/test_kb/test_lab.py::test_stats_increment_view tests/test_kb/test_lab.py::test_stats_hot_recipes -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /workspace && git add src/hermes_kb/recipe_stats.py tests/test_kb/test_lab.py && git -c user.name=trae-agent -c user.email=agent@trae.local commit -m "feat(lab): 配方使用统计模块

- increment_match_count(): 匹配命中计数 +1
- increment_view_count(): 查看详情计数 +1
- get_stats(): 单配方统计查询
- get_hot_recipes(): 热门配方排行（按 match_count 降序，限时间范围）"
```

---

## Task 7: API 端点 — /api/lab/match + /api/lab/hot + /api/lab/view

**Files:**
- Modify: `src/hermes_kb/app.py`（在年龄门端点之后、静态文件挂载之前追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_kb/test_lab.py` 追加：

```python


def test_api_lab_match(seeded_recipes, client):
    """GET /api/lab/match 返回匹配结果。"""
    resp = client.get("/api/lab/match", params={"ingredients": "金酒,味美思,橄榄"})
    assert resp.status_code == 200
    data = resp.json()
    assert "full_match" in data
    assert "partial_match" in data
    titles = [r["title"] for r in data["full_match"]]
    assert "马天尼 Martini" in titles


def test_api_lab_match_empty(client):
    """空材料返回空结果。"""
    resp = client.get("/api/lab/match", params={"ingredients": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert data["full_match"] == []
    assert data["partial_match"] == []


def test_api_lab_match_increments_stats(seeded_recipes, client):
    """匹配 API 调用后统计计数增加。"""
    # 先调一次匹配
    resp = client.get(
        "/api/lab/match", params={"ingredients": "金酒,味美思,橄榄"}
    )
    assert resp.status_code == 200
    martini = next(
        r for r in resp.json()["full_match"] if "马天尼" in r["title"]
    )
    doc_id = martini["doc_id"]

    # 验证统计已增加
    from hermes_kb.recipe_stats import get_stats

    stat = get_stats(doc_id)
    assert stat is not None
    assert stat["match_count"] >= 1


def test_api_lab_hot(seeded_recipes, client):
    """GET /api/lab/hot 返回热门配方。"""
    # 先制造一些匹配数据
    for _ in range(3):
        client.get(
            "/api/lab/match", params={"ingredients": "金酒,味美思,橄榄"}
        )

    resp = client.get("/api/lab/hot", params={"limit": 10, "days": 30})
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) > 0
    # 马天尼应排前
    assert data["items"][0]["match_count"] >= 3


def test_api_lab_view(seeded_recipes, client):
    """POST /api/lab/view/{doc_id} 增加查看计数。"""
    from hermes_kb.recipe_match import match_recipes

    result = match_recipes({"金酒", "味美思", "橄榄"})
    doc_id = result["full_match"][0]["doc_id"]

    resp = client.post(f"/api/lab/view/{doc_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    from hermes_kb.recipe_stats import get_stats

    stat = get_stats(doc_id)
    assert stat["view_count"] == 1
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_api_lab_match tests/test_kb/test_lab.py::test_api_lab_match_empty tests/test_kb/test_lab.py::test_api_lab_match_increments_stats tests/test_kb/test_lab.py::test_api_lab_hot tests/test_kb/test_lab.py::test_api_lab_view -v`

Expected: FAIL with "404 Not Found"（端点未实现）

- [ ] **Step 3: 实现 API 端点**

在 `src/hermes_kb/app.py` 的年龄门端点之后（`@app.get("/api/age-gate/status")` 之后）、静态文件挂载之前，追加：

```python

    # -----------------------------------------------------------------------
    # M3：鸡尾酒实验室
    # -----------------------------------------------------------------------
    @app.get("/api/lab/match")
    async def lab_match(ingredients: str = "") -> dict[str, Any]:
        """材料 → 配方匹配。ingredients 为逗号分隔的材料名。"""
        from hermes_kb.ingredients import canonicalize
        from hermes_kb.recipe_match import match_recipes
        from hermes_kb.recipe_stats import increment_match_count

        if not ingredients or not ingredients.strip():
            return {"full_match": [], "partial_match": []}

        # 归一化材料名
        raw_names = [s.strip() for s in ingredients.split(",") if s.strip()]
        user_ingredients = {canonicalize(n) for n in raw_names}

        result = match_recipes(user_ingredients)

        # 统计：对匹配命中的配方 match_count +1
        for recipe in result["full_match"] + result["partial_match"]:
            try:
                increment_match_count(recipe["doc_id"])
            except Exception:
                pass  # 统计失败不影响主流程

        return result

    @app.get("/api/lab/hot")
    async def lab_hot(limit: int = 3, days: int = 30) -> dict[str, Any]:
        """热门配方（按 match_count 降序）。"""
        from hermes_kb.recipe_stats import get_hot_recipes

        limit = max(1, min(limit, 50))
        days = max(1, min(days, 365))
        items = get_hot_recipes(limit=limit, days=days)
        return {"items": items}

    @app.post("/api/lab/view/{doc_id}")
    async def lab_view(doc_id: str) -> dict[str, Any]:
        """查看配方详情时调用，view_count +1。"""
        from hermes_kb.recipe_stats import increment_view_count

        increment_view_count(doc_id)
        return {"doc_id": doc_id, "status": "ok"}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_api_lab_match tests/test_kb/test_lab.py::test_api_lab_match_empty tests/test_kb/test_lab.py::test_api_lab_match_increments_stats tests/test_kb/test_lab.py::test_api_lab_hot tests/test_kb/test_lab.py::test_api_lab_view -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /workspace && git add src/hermes_kb/app.py tests/test_kb/test_lab.py && git -c user.name=trae-agent -c user.email=agent@trae.local commit -m "feat(lab): API 端点 /api/lab/match + /hot + /view

- GET /api/lab/match: 材料匹配，自动归一化 + 统计计数
- GET /api/lab/hot: 热门配方排行
- POST /api/lab/view/{doc_id}: 查看计数
- 统计失败不影响主流程"
```

---

## Task 8: 种子配方导入端点 — /api/seed/recipes

**Files:**
- Modify: `src/hermes_kb/app.py`（在 /api/seed 端点之后追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_kb/test_lab.py` 追加：

```python


def test_api_seed_recipes(client):
    """POST /api/seed/recipes 导入 IBA 配方种子。"""
    resp = client.post("/api/seed/recipes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["seeded"] == 8
    assert data["failed"] == 0
    # 验证配方已入库且 category=recipe
    from hermes_kb.database import get_session
    from hermes_kb.models import Document
    from sqlmodel import select

    with get_session() as session:
        recipes = session.exec(
            select(Document).where(Document.category == "recipe")
        ).all()
        assert len(recipes) == 8
        titles = [d.title for d in recipes]
        assert "马天尼 Martini" in titles


def test_api_seed_recipes_idempotent(client):
    """重复导入不会产生重复配方。"""
    client.post("/api/seed/recipes")
    resp = client.post("/api/seed/recipes")
    assert resp.status_code == 200
    # 第二次应跳过已存在的
    from hermes_kb.database import get_session
    from hermes_kb.models import Document
    from sqlmodel import select

    with get_session() as session:
        count = len(
            session.exec(
                select(Document).where(Document.category == "recipe")
            ).all()
        )
        assert count == 8
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_api_seed_recipes tests/test_kb/test_lab.py::test_api_seed_recipes_idempotent -v`

Expected: FAIL with "404 Not Found"

- [ ] **Step 3: 实现种子配方导入端点**

在 `src/hermes_kb/app.py` 的 `/api/seed` 端点之后（`@app.post("/api/seed")` 之后）追加：

```python

    @app.post("/api/seed/recipes", dependencies=[Depends(require_auth)])
    async def seed_recipes() -> dict[str, Any]:
        """M3：导入 IBA 配方种子数据（幂等）。"""
        from hermes_kb.seed_recipes import SEED_RECIPES

        seeded = 0
        failed = 0
        items: list[dict[str, Any]] = []
        for recipe in SEED_RECIPES:
            # 幂等检查：按 title 查是否已存在
            with get_session() as session:
                existing = session.exec(
                    select(Document).where(Document.title == recipe["title"])
                ).first()
                if existing:
                    items.append(
                        {
                            "title": recipe["title"],
                            "status": "skipped",
                            "doc_id": existing.doc_id,
                        }
                    )
                    continue
            try:
                result = importer.import_text(
                    content=recipe["content"],
                    title=recipe["title"],
                    source_type="seed",
                    file_type="md",
                )
                # 设置 category=recipe
                if result.get("doc_id"):
                    with get_session() as session:
                        doc = session.get(Document, result["doc_id"])
                        if doc:
                            doc.category = "recipe"
                            session.add(doc)
                            session.commit()
                seeded += 1
                items.append({**result, "status": "imported"})
            except Exception as e:
                failed += 1
                items.append(
                    {"title": recipe["title"], "error": str(e), "status": "failed"}
                )
        return {"seeded": seeded, "failed": failed, "items": items}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py::test_api_seed_recipes tests/test_kb/test_lab.py::test_api_seed_recipes_idempotent -v`

Expected: PASS

注意：测试因 `KB_AUTH_ENABLED` 默认 false，`Depends(require_auth)` 会放行。若启用认证需在 conftest 处理。

- [ ] **Step 5: 提交**

```bash
cd /workspace && git add src/hermes_kb/app.py tests/test_kb/test_lab.py && git -c user.name=trae-agent -c user.email=agent@trae.local commit -m "feat(lab): 种子配方导入端点 /api/seed/recipes

- 幂等导入：按 title 去重，已存在则跳过
- 导入后自动设置 category=recipe
- 返回 seeded/failed/items 明细"
```

---

## Task 9: 高保真设计稿 — lab.html

**Files:**
- Create: `design/mockup/lab.html`

- [ ] **Step 1: 创建高保真设计稿**

创建 `design/mockup/lab.html`（参考 `ask.html` 的结构模式：link 字体 + _tokens.css + _components.css + 页面专属 style + body data-page + main + script）：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>鸡尾酒实验室 · Hermes KB</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Noto+Serif+SC:wght@500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="_tokens.css">
  <link rel="stylesheet" href="_components.css">
  <style>
    /* 实验室页专属布局 */
    .lab-main { max-width: 960px; margin: 0 auto; padding: var(--sp-8) var(--sp-6); }
    .lab-hero { text-align: center; margin-bottom: var(--sp-8); }
    .lab-hero h1 { font-family: var(--font-serif); font-size: var(--fs-2xl); color: var(--brand-700); margin-bottom: var(--sp-2); }
    .lab-hero .sub { color: var(--ink-400); font-size: var(--fs-sm); }

    /* 材料选择器 */
    .material-selector { background: #fff; border: 1px solid var(--ink-200); border-radius: var(--r-lg); padding: var(--sp-6); box-shadow: var(--shadow-sm); margin-bottom: var(--sp-6); }
    .material-search { width: 100%; margin-bottom: var(--sp-4); }
    .material-category { margin-bottom: var(--sp-3); border-bottom: 1px solid var(--ink-100); padding-bottom: var(--sp-3); }
    .material-category:last-of-type { border-bottom: none; }
    .material-category summary { font-family: var(--font-serif); font-size: var(--fs-sm); color: var(--brand-700); cursor: pointer; padding: var(--sp-1) 0; display: flex; align-items: center; gap: var(--sp-2); }
    .material-category summary .count { font-size: var(--fs-xs); color: var(--ink-400); font-family: var(--font-sans); }
    .chip-list { display: flex; flex-wrap: wrap; gap: var(--sp-2); padding: var(--sp-2) 0; }

    /* 材料 chip（按分类配色） */
    .chip-chip { font-family: var(--font-sans); font-size: var(--fs-xs); padding: 4px var(--sp-3); border-radius: var(--r-full); border: 1px solid var(--ink-200); background: var(--ink-100); color: var(--ink-600); cursor: pointer; transition: all var(--duration-fast) var(--ease-out); }
    .chip-chip:hover { border-color: var(--brand-700); }
    .chip-chip.selected.cat-base_spirit { background: var(--brand-700); color: #fff; border-color: var(--brand-700); }
    .chip-chip.selected.cat-modifier { background: var(--gold-500); color: var(--ink-900); border-color: var(--gold-500); }
    .chip-chip.selected.cat-juice { background: var(--ink-600); color: #fff; border-color: var(--ink-600); }
    .chip-chip.selected.cat-garnish { background: var(--ink-400); color: var(--ink-900); border-color: var(--ink-400); }

    /* 已选材料条 */
    .selected-bar { background: var(--gold-100); border-left: 3px solid var(--gold-500); padding: var(--sp-3) var(--sp-4); border-radius: var(--r-md); margin: var(--sp-4) 0; display: flex; align-items: center; flex-wrap: wrap; gap: var(--sp-2); }
    .selected-bar .label { font-size: var(--fs-xs); color: var(--ink-600); margin-right: var(--sp-2); }
    .selected-chip { background: var(--gold-500); color: var(--ink-900); font-size: var(--fs-xs); padding: 2px var(--sp-2); border-radius: var(--r-full); display: inline-flex; align-items: center; gap: var(--sp-1); cursor: pointer; }
    .selected-chip:hover { background: var(--gold-700); color: #fff; }
    .selected-bar .clear-btn { margin-left: auto; }

    /* 匹配按钮 */
    .match-btn { width: 100%; justify-content: center; padding: var(--sp-3) var(--sp-4); font-size: var(--fs-base); }
    .match-btn.pulse { animation: pulse-gold 2s infinite; }
    @keyframes pulse-gold { 0%, 100% { box-shadow: 0 0 0 0 rgba(201,162,39,0.4); } 50% { box-shadow: 0 0 0 8px rgba(201,162,39,0); } }

    /* 结果区 */
    .results { display: none; }
    .results.show { display: block; }
    .result-group { margin-bottom: var(--sp-6); }
    .result-group h2 { font-family: var(--font-serif); font-size: var(--fs-lg); color: var(--ink-900); margin-bottom: var(--sp-3); display: flex; align-items: center; gap: var(--sp-2); }
    .result-group h2 .badge { font-size: var(--fs-xs); color: var(--ink-400); font-family: var(--font-sans); }
    .result-group.full h2 { color: var(--brand-700); }
    .result-group.partial h2 { color: var(--gold-700); }

    /* 配方卡 */
    .recipe-card { background: #fff; border: 1px solid var(--ink-200); border-radius: var(--r-lg); padding: var(--sp-4) var(--sp-5); margin-bottom: var(--sp-3); box-shadow: var(--shadow-sm); transition: box-shadow var(--duration-base); }
    .recipe-card:hover { box-shadow: var(--shadow-md); }
    .recipe-card.full-match { border-left: 3px solid var(--brand-700); }
    .recipe-card.partial-match { border-left: 3px solid var(--gold-500); }
    .recipe-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--sp-2); }
    .recipe-name { font-family: var(--font-serif); font-size: var(--fs-base); color: var(--ink-900); }
    .match-badge { font-size: var(--fs-xs); padding: 2px var(--sp-2); border-radius: var(--r-full); }
    .match-badge.match-full { background: var(--brand-100); color: var(--brand-700); }
    .match-badge.match-partial { background: var(--gold-100); color: var(--gold-700); }
    .recipe-ingredients { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin-bottom: var(--sp-2); }
    .ing { font-size: var(--fs-xs); padding: 2px var(--sp-2); border-radius: var(--r-sm); }
    .ing.have { background: var(--brand-50); color: var(--brand-700); }
    .ing.missing { background: var(--ink-100); color: var(--ink-400); text-decoration: line-through; }
    .substitute-suggest { font-size: var(--fs-xs); color: var(--gold-700); margin-bottom: var(--sp-2); display: flex; align-items: center; flex-wrap: wrap; gap: var(--sp-2); }
    .sub-chip { background: var(--gold-100); color: var(--gold-700); border: 1px dashed var(--gold-500); padding: 2px var(--sp-2); border-radius: var(--r-sm); cursor: pointer; font-size: var(--fs-xs); }
    .sub-chip:hover { background: var(--gold-500); color: var(--ink-900); }
    .recipe-footer { display: flex; align-items: center; justify-content: space-between; padding-top: var(--sp-2); border-top: 1px dashed var(--ink-200); }
    .citation-link { color: var(--brand-700); font-size: var(--fs-xs); text-decoration: none; }
    .citation-link:hover { text-decoration: underline; }

    /* 空状态 */
    .lab-empty { text-align: center; padding: var(--sp-16) var(--sp-6); color: var(--ink-400); }
    .lab-empty h3 { font-family: var(--font-serif); color: var(--ink-600); margin-bottom: var(--sp-2); }
    .lab-empty .examples { display: flex; gap: var(--sp-2); justify-content: center; margin-top: var(--sp-4); flex-wrap: wrap; }
  </style>
</head>
<body data-page="lab">
  <main class="lab-main">
    <div class="lab-hero">
      <h1 class="serif">鸡尾酒实验室</h1>
      <p class="sub">选择手头的材料，发现你能调的鸡尾酒</p>
    </div>

    <!-- 材料选择区 -->
    <section class="material-selector">
      <input class="input material-search" placeholder="搜索材料... 如 金酒" oninput="filterMaterials(this.value)">

      <details class="material-category" open>
        <summary>基酒 <span class="count" id="cat-count-base_spirit">6</span></summary>
        <div class="chip-list" id="cat-base_spirit">
          <button class="chip-chip cat-base_spirit" onclick="toggleMaterial(this, '金酒', 'base_spirit')">金酒</button>
          <button class="chip-chip cat-base_spirit" onclick="toggleMaterial(this, '威士忌', 'base_spirit')">威士忌</button>
          <button class="chip-chip cat-base_spirit" onclick="toggleMaterial(this, '朗姆酒', 'base_spirit')">朗姆酒</button>
          <button class="chip-chip cat-base_spirit" onclick="toggleMaterial(this, '龙舌兰', 'base_spirit')">龙舌兰</button>
          <button class="chip-chip cat-base_spirit" onclick="toggleMaterial(this, '白兰地', 'base_spirit')">白兰地</button>
          <button class="chip-chip cat-base_spirit" onclick="toggleMaterial(this, '伏特加', 'base_spirit')">伏特加</button>
        </div>
      </details>

      <details class="material-category">
        <summary>辅料 <span class="count" id="cat-count-modifier">10</span></summary>
        <div class="chip-list" id="cat-modifier">
          <button class="chip-chip cat-modifier" onclick="toggleMaterial(this, '味美思', 'modifier')">味美思</button>
          <button class="chip-chip cat-modifier" onclick="toggleMaterial(this, '金巴利', 'modifier')">金巴利</button>
          <button class="chip-chip cat-modifier" onclick="toggleMaterial(this, '糖浆', 'modifier')">糖浆</button>
          <button class="chip-chip cat-modifier" onclick="toggleMaterial(this, '君度', 'modifier')">君度</button>
          <button class="chip-chip cat-modifier" onclick="toggleMaterial(this, '苦精', 'modifier')">苦精</button>
          <button class="chip-chip cat-modifier" onclick="toggleMaterial(this, '汤力水', 'modifier')">汤力水</button>
          <button class="chip-chip cat-modifier" onclick="toggleMaterial(this, '苏打水', 'modifier')">苏打水</button>
          <button class="chip-chip cat-modifier" onclick="toggleMaterial(this, '可乐', 'modifier')">可乐</button>
          <button class="chip-chip cat-modifier" onclick="toggleMaterial(this, '姜啤', 'modifier')">姜啤</button>
        </div>
      </details>

      <details class="material-category">
        <summary>果汁 <span class="count" id="cat-count-juice">6</span></summary>
        <div class="chip-list" id="cat-juice">
          <button class="chip-chip cat-juice" onclick="toggleMaterial(this, '柠檬汁', 'juice')">柠檬汁</button>
          <button class="chip-chip cat-juice" onclick="toggleMaterial(this, '青柠汁', 'juice')">青柠汁</button>
          <button class="chip-chip cat-juice" onclick="toggleMaterial(this, '橙汁', 'juice')">橙汁</button>
          <button class="chip-chip cat-juice" onclick="toggleMaterial(this, '蔓越莓汁', 'juice')">蔓越莓汁</button>
          <button class="chip-chip cat-juice" onclick="toggleMaterial(this, '菠萝汁', 'juice')">菠萝汁</button>
          <button class="chip-chip cat-juice" onclick="toggleMaterial(this, '番茄汁', 'juice')">番茄汁</button>
        </div>
      </details>

      <details class="material-category">
        <summary>装饰 <span class="count" id="cat-count-garnish">5</span></summary>
        <div class="chip-list" id="cat-garnish">
          <button class="chip-chip cat-garnish" onclick="toggleMaterial(this, '橄榄', 'garnish')">橄榄</button>
          <button class="chip-chip cat-garnish" onclick="toggleMaterial(this, '柠檬片', 'garnish')">柠檬片</button>
          <button class="chip-chip cat-garnish" onclick="toggleMaterial(this, '薄荷叶', 'garnish')">薄荷叶</button>
          <button class="chip-chip cat-garnish" onclick="toggleMaterial(this, '樱桃', 'garnish')">樱桃</button>
          <button class="chip-chip cat-garnish" onclick="toggleMaterial(this, '橙皮', 'garnish')">橙皮</button>
        </div>
      </details>

      <div class="selected-bar" id="selectedBar" style="display:none;">
        <span class="label">已选：</span>
        <div id="selectedChips" style="display:inline-flex; flex-wrap:wrap; gap:var(--sp-2);"></div>
        <button class="btn-ghost clear-btn" onclick="clearAll()">清空</button>
      </div>

      <button class="btn-primary match-btn" id="matchBtn" onclick="doMatch()">匹配配方 →</button>
    </section>

    <!-- 空状态 -->
    <section class="lab-empty" id="emptyState">
      <h3 class="serif">选择材料开始</h3>
      <p>点击上方材料 chip，或试试这些：</p>
      <div class="examples">
        <button class="btn-ghost" onclick="quickSelect(['金酒','味美思','橄榄'])">马天尼套餐</button>
        <button class="btn-ghost" onclick="quickSelect(['朗姆酒','青柠汁','糖浆','薄荷叶','苏打水'])">莫吉托套餐</button>
        <button class="btn-ghost" onclick="quickSelect(['龙舌兰','橙汁','糖浆'])">龙舌兰日出套餐</button>
      </div>
    </section>

    <!-- 结果区 -->
    <section class="results" id="results">
      <div class="result-group full" id="fullGroup" style="display:none;">
        <h2>现在就能做 <span class="badge" id="fullCount"></span></h2>
        <div id="fullList"></div>
      </div>
      <div class="result-group partial" id="partialGroup" style="display:none;">
        <h2>差一种就能做 <span class="badge" id="partialCount"></span></h2>
        <div id="partialList"></div>
      </div>
    </section>
  </main>

  <script>
    // 状态：已选材料 { name: category }
    var selected = {};

    function toggleMaterial(btn, name, category) {
      if (selected[name]) {
        delete selected[name];
        btn.classList.remove('selected');
      } else {
        selected[name] = category;
        btn.classList.add('selected');
      }
      updateSelectedBar();
      updateMatchBtn();
    }

    function updateSelectedBar() {
      var bar = document.getElementById('selectedBar');
      var chipsDiv = document.getElementById('selectedChips');
      var names = Object.keys(selected);
      if (names.length === 0) {
        bar.style.display = 'none';
        return;
      }
      bar.style.display = 'flex';
      chipsDiv.innerHTML = names.map(function(name) {
        return '<span class="selected-chip" onclick="removeMaterial(\'' + name + '\')">' + name + ' ×</span>';
      }).join('');
    }

    function removeMaterial(name) {
      delete selected[name];
      // 同步 chip 状态
      document.querySelectorAll('.chip-chip').forEach(function(chip) {
        if (chip.textContent === name) chip.classList.remove('selected');
      });
      updateSelectedBar();
      updateMatchBtn();
    }

    function clearAll() {
      selected = {};
      document.querySelectorAll('.chip-chip.selected').forEach(function(chip) {
        chip.classList.remove('selected');
      });
      updateSelectedBar();
      updateMatchBtn();
      document.getElementById('results').classList.remove('show');
      document.getElementById('emptyState').style.display = 'block';
    }

    function updateMatchBtn() {
      var btn = document.getElementById('matchBtn');
      var count = Object.keys(selected).length;
      if (count > 0) {
        btn.classList.add('pulse');
        btn.textContent = '匹配配方 →（已选 ' + count + ' 种）';
      } else {
        btn.classList.remove('pulse');
        btn.textContent = '匹配配方 →';
      }
    }

    function quickSelect(names) {
      clearAll();
      names.forEach(function(name) {
        var chips = document.querySelectorAll('.chip-chip');
        for (var i = 0; i < chips.length; i++) {
          if (chips[i].textContent === name) {
            var cat = chips[i].className.match(/cat-(\w+)/);
            if (cat) toggleMaterial(chips[i], name, cat[1]);
            break;
          }
        }
      });
    }

    function filterMaterials(query) {
      query = query.trim().toLowerCase();
      document.querySelectorAll('.chip-chip').forEach(function(chip) {
        var match = chip.textContent.toLowerCase().indexOf(query) >= 0;
        chip.style.display = match ? '' : 'none';
      });
    }

    function doMatch() {
      var names = Object.keys(selected);
      if (names.length === 0) return;

      // 模拟匹配结果（高保真稿静态展示）
      var mockFull = [];
      var mockPartial = [];

      if (selected['金酒'] && selected['味美思'] && selected['橄榄']) {
        mockFull.push({
          title: '马天尼 Martini', chunk: 42, ingredients: [
            {name: '金酒', amount: '60ml', have: true},
            {name: '干味美思', amount: '10ml', have: true},
            {name: '橄榄', amount: '1 颗', have: true}
          ]
        });
      }
      if (selected['金酒'] && selected['金巴利'] && selected['味美思']) {
        mockFull.push({
          title: '尼格罗尼 Negroni', chunk: 71, ingredients: [
            {name: '金酒', amount: '30ml', have: true},
            {name: '金巴利', amount: '30ml', have: true},
            {name: '甜味美思', amount: '30ml', have: true},
            {name: '橙皮', amount: '1 片', have: true}
          ]
        });
      }
      if (selected['金酒'] && selected['柠檬汁'] && !selected['君度']) {
        mockPartial.push({
          title: '白色佳人 White Lady', chunk: 58, missing: ['君度'], ingredients: [
            {name: '金酒', amount: '40ml', have: true},
            {name: '君度', amount: '15ml', have: false, substitutes: ['橙味力娇酒', '干库拉索']},
            {name: '柠檬汁', amount: '20ml', have: true}
          ]
        });
      }

      renderResults(mockFull, mockPartial);
    }

    function renderResults(full, partial) {
      document.getElementById('emptyState').style.display = 'none';
      document.getElementById('results').classList.add('show');

      // full match
      var fullGroup = document.getElementById('fullGroup');
      if (full.length > 0) {
        fullGroup.style.display = 'block';
        document.getElementById('fullCount').textContent = '(' + full.length + ')';
        document.getElementById('fullList').innerHTML = full.map(renderCard).join('');
      } else {
        fullGroup.style.display = 'none';
      }

      // partial match
      var partialGroup = document.getElementById('partialGroup');
      if (partial.length > 0) {
        partialGroup.style.display = 'block';
        document.getElementById('partialCount').textContent = '(' + partial.length + ')';
        document.getElementById('partialList').innerHTML = partial.map(renderCard).join('');
      } else {
        partialGroup.style.display = 'none';
      }
    }

    function renderCard(r) {
      var isPartial = r.missing && r.missing.length > 0;
      var cardClass = isPartial ? 'partial-match' : 'full-match';
      var badgeClass = isPartial ? 'match-partial' : 'match-full';
      var badgeText = isPartial ? '缺 ' + r.missing.length + ' 种' : '材料齐全';

      var ingHtml = r.ingredients.map(function(ing) {
        var cls = ing.have ? 'have' : 'missing';
        var text = (ing.have ? '✓ ' : '✗ ') + ing.name + ' ' + (ing.amount || '');
        return '<span class="ing ' + cls + '">' + text + '</span>';
      }).join('');

      var subHtml = '';
      if (isPartial) {
        var subs = [];
        r.ingredients.forEach(function(ing) {
          if (!ing.have && ing.substitutes) {
            ing.substitutes.forEach(function(s) {
              subs.push('<button class="sub-chip" onclick="addSubstitute(\'' + s + '\')">' + s + ' +</button>');
            });
          }
        });
        if (subs.length > 0) {
          subHtml = '<div class="substitute-suggest">可替代：' + subs.join('') + '</div>';
        }
      }

      return '<div class="recipe-card ' + cardClass + '">' +
        '<div class="recipe-header">' +
          '<h3 class="recipe-name">' + r.title + '</h3>' +
          '<span class="match-badge ' + badgeClass + '">' + badgeText + '</span>' +
        '</div>' +
        '<div class="recipe-ingredients">' + ingHtml + '</div>' +
        subHtml +
        '<div class="recipe-footer">' +
          '<a href="doc-detail.html?chunk=' + r.chunk + '" class="citation-link">[' + r.chunk + '] 引用 IBA 百科</a>' +
          '<button class="btn-ghost" onclick="askAbout(\'' + r.title + '\')">基于此配方提问</button>' +
        '</div>' +
      '</div>';
    }

    function addSubstitute(name) {
      // 找到对应分类的 chip 并选中
      var chips = document.querySelectorAll('.chip-chip');
      for (var i = 0; i < chips.length; i++) {
        if (chips[i].textContent === name) {
          var cat = chips[i].className.match(/cat-(\w+)/);
          if (cat && !chips[i].classList.contains('selected')) {
            toggleMaterial(chips[i], name, cat[1]);
          }
          break;
        }
      }
      doMatch(); // 重新匹配
    }

    function askAbout(title) {
      window.location.href = 'ask.html?q=' + encodeURIComponent(title + '的做法');
    }
  </script>
</body>
</html>
```

- [ ] **Step 2: 验证文件创建**

Run: `cd /workspace && ls -la design/mockup/lab.html && wc -l design/mockup/lab.html`

Expected: 文件存在，行数 > 200

- [ ] **Step 3: 提交**

```bash
cd /workspace && git add design/mockup/lab.html && git -c user.name=trae-agent -c user.email=agent@trae.local commit -m "feat(lab): 高保真设计稿 lab.html

- 材料选择器：搜索框 + 4 大类折叠 + chip 配色（基酒酒红/辅料暗金/果汁暖灰/装饰浅灰）
- 已选材料条：gold-100 底 + gold-500 左边框
- 配方卡片：full-match 酒红左边框 / partial-match 暗金左边框
- 替代推荐：点 + chip 自动加入并重新匹配
- 引用跳转：[N] 链接 doc-detail.html?chunk=N 复用 M2 高亮
- 空状态：3 个示例套餐快速选择"
```

---

## Task 10: 低保真原型 — lab.html + 导航集成

**Files:**
- Create: `design/prototype/lab.html`
- Modify: `design/mockup/_nav.js`

- [ ] **Step 1: 创建低保真原型**

创建 `design/prototype/lab.html`（灰阶线框，参考现有 prototype 的 _shared.css）：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>鸡尾酒实验室 · Hermes KB（低保真）</title>
  <link rel="stylesheet" href="_shared.css">
</head>
<body data-page="lab">
  <main class="page">
    <header class="page-header">
      <h1>鸡尾酒实验室</h1>
      <p class="muted">选择手头的材料，发现你能调的鸡尾酒</p>
    </header>

    <!-- 材料选择区 -->
    <section class="block">
      <input class="input" placeholder="搜索材料... 如 金酒" type="text">

      <div class="category">
        <h3>基酒</h3>
        <div class="chips">
          <span class="chip">[金酒]</span>
          <span class="chip">[威士忌]</span>
          <span class="chip">[朗姆酒]</span>
          <span class="chip">[龙舌兰]</span>
          <span class="chip">[白兰地]</span>
          <span class="chip">[伏特加]</span>
        </div>
      </div>

      <div class="category">
        <h3>辅料</h3>
        <div class="chips">
          <span class="chip">[味美思]</span>
          <span class="chip">[金巴利]</span>
          <span class="chip">[糖浆]</span>
          <span class="chip">[君度]</span>
          <span class="chip">[苦精]</span>
          <span class="chip">[汤力水]</span>
          <span class="chip">[苏打水]</span>
        </div>
      </div>

      <div class="category">
        <h3>果汁</h3>
        <div class="chips">
          <span class="chip">[柠檬汁]</span>
          <span class="chip">[青柠汁]</span>
          <span class="chip">[橙汁]</span>
          <span class="chip">[蔓越莓汁]</span>
        </div>
      </div>

      <div class="category">
        <h3>装饰</h3>
        <div class="chips">
          <span class="chip">[橄榄]</span>
          <span class="chip">[柠檬片]</span>
          <span class="chip">[薄荷叶]</span>
          <span class="chip">[樱桃]</span>
        </div>
      </div>

      <div class="selected-bar">
        已选：[金酒 ×] [味美思 ×] [橄榄 ×] <a href="#" class="link">清空</a>
      </div>

      <button class="btn-primary">[匹配配方 →]</button>
    </section>

    <!-- 结果区 -->
    <section class="block">
      <h2>现在就能做 (1)</h2>
      <div class="card">
        <strong>马天尼 Martini</strong> <span class="badge">材料齐全</span>
        <div class="ingredients">
          [✓ 金酒 60ml] [✓ 干味美思 10ml] [✓ 橄榄 1 颗]
        </div>
        <div class="footer">
          <a href="doc-detail.html?chunk=42" class="link">[42] 引用 IBA 百科</a>
          <a href="ask.html?q=马天尼的做法" class="link">[基于此配方提问]</a>
        </div>
      </div>

      <h2>差一种就能做 (1)</h2>
      <div class="card">
        <strong>白色佳人 White Lady</strong> <span class="badge">缺 1 种</span>
        <div class="ingredients">
          [✓ 金酒 40ml] [✗ 君度 15ml] [✓ 柠檬汁 20ml]
        </div>
        <div class="substitute">
          可替代：[橙味力娇酒 +] [干库拉索 +]
        </div>
        <div class="footer">
          <a href="doc-detail.html?chunk=58" class="link">[58] 引用 IBA 百科</a>
          <a href="ask.html?q=白色佳人的做法" class="link">[基于此配方提问]</a>
        </div>
      </div>
    </section>
  </main>
</body>
</html>
```

- [ ] **Step 2: 修改导航加入 lab 入口**

修改 `design/mockup/_nav.js`，在 NAV_ITEMS 数组的"问答"项之后插入 lab 项。

将 `_nav.js` 第 6-14 行的 NAV_ITEMS 数组：

```javascript
  var NAV_ITEMS = [
    { href: 'index.html', label: '首页', page: 'home' },
    { href: 'ask.html', label: '问答', page: 'ask' },
    { href: 'docs.html', label: '文档', page: 'docs' },
    { href: 'tags.html', label: '标签', page: 'tags' },
    { href: 'history.html', label: '历史', page: 'history' },
    { href: 'dashboard.html', label: '仪表盘', page: 'dashboard' },
    { href: 'audit.html', label: '审计', page: 'audit' }
  ];
```

替换为：

```javascript
  var NAV_ITEMS = [
    { href: 'index.html', label: '首页', page: 'home' },
    { href: 'ask.html', label: '问答', page: 'ask' },
    { href: 'lab.html', label: '实验室', page: 'lab' },
    { href: 'docs.html', label: '文档', page: 'docs' },
    { href: 'tags.html', label: '标签', page: 'tags' },
    { href: 'history.html', label: '历史', page: 'history' },
    { href: 'dashboard.html', label: '仪表盘', page: 'dashboard' },
    { href: 'audit.html', label: '审计', page: 'audit' }
  ];
```

- [ ] **Step 3: 验证导航更新**

Run: `cd /workspace && grep -c "lab.html" design/mockup/_nav.js`

Expected: 1（lab.html 出现在 NAV_ITEMS 中）

- [ ] **Step 4: 提交**

```bash
cd /workspace && git add design/prototype/lab.html design/mockup/_nav.js && git -c user.name=trae-agent -c user.email=agent@trae.local commit -m "feat(lab): 低保真原型 + 导航集成

- prototype/lab.html: 灰阶线框，占位内容，仅链接无 JS
- _nav.js: 新增实验室入口（位于问答与文档之间）"
```

---

## Task 11: 组件样式 + 首页热门区

**Files:**
- Modify: `design/mockup/_components.css`（追加实验室组件样式）
- Modify: `design/mockup/index.html`（首页增加 Top 3 热门配方区）

- [ ] **Step 1: 追加实验室组件样式到 _components.css**

在 `design/mockup/_components.css` 末尾追加：

```css


/* === 实验室组件（M3） === */
.material-selector {
  background: #fff; border: 1px solid var(--ink-200);
  border-radius: var(--r-lg); padding: var(--sp-6);
  box-shadow: var(--shadow-sm);
}
.material-search { width: 100%; margin-bottom: var(--sp-4); }
.material-category {
  margin-bottom: var(--sp-3);
  border-bottom: 1px solid var(--ink-100);
  padding-bottom: var(--sp-3);
}
.material-category:last-of-type { border-bottom: none; }
.material-category summary {
  font-family: var(--font-serif); font-size: var(--fs-sm);
  color: var(--brand-700); cursor: pointer;
  padding: var(--sp-1) 0;
}
.chip-list { display: flex; flex-wrap: wrap; gap: var(--sp-2); padding: var(--sp-2) 0; }
.chip-chip {
  font-family: var(--font-sans); font-size: var(--fs-xs);
  padding: 4px var(--sp-3); border-radius: var(--r-full);
  border: 1px solid var(--ink-200); background: var(--ink-100);
  color: var(--ink-600); cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.chip-chip:hover { border-color: var(--brand-700); }
.chip-chip.selected.cat-base_spirit { background: var(--brand-700); color: #fff; border-color: var(--brand-700); }
.chip-chip.selected.cat-modifier { background: var(--gold-500); color: var(--ink-900); border-color: var(--gold-500); }
.chip-chip.selected.cat-juice { background: var(--ink-600); color: #fff; border-color: var(--ink-600); }
.chip-chip.selected.cat-garnish { background: var(--ink-400); color: var(--ink-900); border-color: var(--ink-400); }

.selected-bar {
  background: var(--gold-100); border-left: 3px solid var(--gold-500);
  padding: var(--sp-3) var(--sp-4); border-radius: var(--r-md);
  margin: var(--sp-4) 0;
  display: flex; align-items: center; flex-wrap: wrap; gap: var(--sp-2);
}
.selected-chip {
  background: var(--gold-500); color: var(--ink-900);
  font-size: var(--fs-xs); padding: 2px var(--sp-2);
  border-radius: var(--r-full); cursor: pointer;
}
.selected-chip:hover { background: var(--gold-700); color: #fff; }

.recipe-card {
  background: #fff; border: 1px solid var(--ink-200);
  border-radius: var(--r-lg); padding: var(--sp-4) var(--sp-5);
  margin-bottom: var(--sp-3); box-shadow: var(--shadow-sm);
  transition: box-shadow var(--duration-base);
}
.recipe-card:hover { box-shadow: var(--shadow-md); }
.recipe-card.full-match { border-left: 3px solid var(--brand-700); }
.recipe-card.partial-match { border-left: 3px solid var(--gold-500); }
.recipe-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: var(--sp-2);
}
.recipe-name { font-family: var(--font-serif); font-size: var(--fs-base); color: var(--ink-900); }
.match-badge { font-size: var(--fs-xs); padding: 2px var(--sp-2); border-radius: var(--r-full); }
.match-badge.match-full { background: var(--brand-100); color: var(--brand-700); }
.match-badge.match-partial { background: var(--gold-100); color: var(--gold-700); }
.recipe-ingredients { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin-bottom: var(--sp-2); }
.ing { font-size: var(--fs-xs); padding: 2px var(--sp-2); border-radius: var(--r-sm); }
.ing.have { background: var(--brand-50); color: var(--brand-700); }
.ing.missing { background: var(--ink-100); color: var(--ink-400); text-decoration: line-through; }
.substitute-suggest {
  font-size: var(--fs-xs); color: var(--gold-700);
  margin-bottom: var(--sp-2);
  display: flex; align-items: center; flex-wrap: wrap; gap: var(--sp-2);
}
.sub-chip {
  background: var(--gold-100); color: var(--gold-700);
  border: 1px dashed var(--gold-500);
  padding: 2px var(--sp-2); border-radius: var(--r-sm);
  cursor: pointer; font-size: var(--fs-xs);
}
.sub-chip:hover { background: var(--gold-500); color: var(--ink-900); }
.recipe-footer {
  display: flex; align-items: center; justify-content: space-between;
  padding-top: var(--sp-2); border-top: 1px dashed var(--ink-200);
}
.citation-link { color: var(--brand-700); font-size: var(--fs-xs); text-decoration: none; }
.citation-link:hover { text-decoration: underline; }

/* 首页热门配方区 */
.hot-recipes {
  background: #fff; border: 1px solid var(--ink-200);
  border-radius: var(--r-lg); padding: var(--sp-6);
  box-shadow: var(--shadow-sm); margin: var(--sp-6) 0;
}
.hot-recipes h3 { font-family: var(--font-serif); font-size: var(--fs-lg); color: var(--brand-700); margin-bottom: var(--sp-3); }
.hot-recipe {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--sp-2) var(--sp-3); border-bottom: 1px solid var(--ink-100);
  text-decoration: none; color: var(--ink-900);
}
.hot-recipe:last-child { border-bottom: none; }
.hot-recipe:hover { background: var(--brand-50); }
.hot-recipe .rank { font-family: var(--font-serif); color: var(--gold-500); font-size: var(--fs-lg); margin-right: var(--sp-3); }
.hot-recipe .name { flex: 1; font-size: var(--fs-sm); }
.hot-recipe .count { font-size: var(--fs-xs); color: var(--ink-400); }
```

- [ ] **Step 2: 在首页 index.html 增加热门配方区**

先读取 `design/mockup/index.html` 找到分类入口区的结束位置。

Run: `cd /workspace && grep -n "分类入口\|category-entry\|PRESET_CATEGORIES" design/mockup/index.html`

Expected: 找到分类入口区的标记行

在分类入口区之后（`</section>` 结束标签之后）插入热门配方区：

```html

    <!-- 热门配方区（M3 实验室） -->
    <section class="hot-recipes">
      <h3 class="serif">本周热门配方</h3>
      <a href="doc-detail.html?chunk=42" class="hot-recipe">
        <span class="rank">1</span>
        <span class="name">马天尼 Martini</span>
        <span class="count">命中 128 次</span>
      </a>
      <a href="doc-detail.html?chunk=58" class="hot-recipe">
        <span class="rank">2</span>
        <span class="name">莫吉托 Mojito</span>
        <span class="count">命中 96 次</span>
      </a>
      <a href="doc-detail.html?chunk=71" class="hot-recipe">
        <span class="rank">3</span>
        <span class="name">尼格罗尼 Negroni</span>
        <span class="count">命中 84 次</span>
      </a>
    </section>
```

- [ ] **Step 3: 验证样式追加**

Run: `cd /workspace && grep -c "实验室组件" design/mockup/_components.css && grep -c "hot-recipes" design/mockup/index.html`

Expected: 1 和 1（两处都存在）

- [ ] **Step 4: 提交**

```bash
cd /workspace && git add design/mockup/_components.css design/mockup/index.html && git -c user.name=trae-agent -c user.email=agent@trae.local commit -m "feat(lab): 组件样式 + 首页热门配方区

- _components.css: 追加实验室组件（材料选择器/配方卡/替代推荐/热门区）
- index.html: 分类入口区后增加 Top 3 热门配方（静态展示）"
```

---

## Task 12: 全量回归测试 + 推送

**Files:**
- 无新建，仅运行测试

- [ ] **Step 1: 运行实验室全量测试**

Run: `cd /workspace && python -m pytest tests/test_kb/test_lab.py -v`

Expected: 全部 PASS（约 20 个测试用例）

- [ ] **Step 2: 运行全量回归测试**

Run: `cd /workspace && python -m pytest tests/ -v --tb=short`

Expected: 全部 PASS，无回归（M0/M1/M2 测试不受影响）

- [ ] **Step 3: 推送到远端**

```bash
cd /workspace && git push origin feature/m0-mvp
```

Expected: 推送成功，所有 M3 commit 上传

- [ ] **Step 4: 验证推送**

Run: `cd /workspace && git log --oneline origin/feature/m0-mvp -15`

Expected: 看到 M3 的所有 commit（Task 1-11）

---

## Self-Review

### 1. Spec 覆盖检查

| Spec 章节 | 覆盖 Task | 状态 |
|---|---|---|
| §2.1 配方文档结构 | Task 4（seed_recipes content） | ✅ |
| §2.2 材料分类 4 大类 | Task 2（INGREDIENT_REGISTRY） | ✅ |
| §2.3 材料标准化别名 | Task 2（canonicalize + _ALIAS_INDEX） | ✅ |
| §2.4 三层替代关系表 | Task 1（IngredientSubstitute 表）+ Task 3（substitutes.py） | ✅ |
| §2.5 匹配算法 | Task 5（recipe_match.py） | ✅ |
| §3 页面结构 | Task 9（lab.html 高保真）+ Task 10（低保真） | ✅ |
| §4 组件设计 | Task 9（材料选择器 + 配方卡）+ Task 11（_components.css） | ✅ |
| §5 与 M2 集成 | Task 10（_nav.js）+ Task 11（_components.css + index.html） | ✅ |
| §6 冷启动空状态 | Task 9（lab-empty + 3 示例套餐） | ✅ |
| §7.1 /api/lab/match | Task 7 | ✅ |
| §7.2 /api/lab/hot | Task 7 | ✅ |
| §8 交付物清单 | Task 1-11 全覆盖 | ✅ |
| §12.2 配方使用统计 | Task 1（RecipeStats 表）+ Task 6（recipe_stats.py） | ✅ |
| §12.3 热门推荐 | Task 7（/api/lab/hot）+ Task 11（index.html 热门区） | ✅ |
| POST /api/lab/view | Task 7 | ✅ |

**缺口**：§11 数据源 L3-L5（TheCocktailDB/ima/UGC/品牌）属 M4-M5，spec 明确不在 M3 范围，正确排除。§12.4-12.7（缺材料反馈/每日推荐/运营看板/个性化）属 M4-M5，正确排除。

### 2. Placeholder 扫描

- ✅ 无 TBD/TODO
- ✅ 所有代码块完整（数据模型/材料注册表/替代表/种子配方/匹配算法/统计/API/设计稿/样式）
- ✅ 所有测试用例有具体断言
- ✅ 所有 git commit 命令含具体 message

### 3. 类型一致性检查

| 名称 | Task 定义处 | 后续使用 | 一致 |
|---|---|---|---|
| `RecipeStats` 模型字段 | Task 1 | Task 6（recipe_stats.py 使用 doc_id/match_count/view_count/last_matched_at/last_viewed_at） | ✅ |
| `IngredientSubstitute` 模型字段 | Task 1 | Task 3（substitutes.py 使用 canonical/substitute/source） | ✅ |
| `canonicalize(name)` 签名 | Task 2 | Task 7（app.py 调用） | ✅ |
| `get_substitutes(canonical)` 签名 | Task 3 | Task 5（recipe_match.py 调用） | ✅ |
| `match_recipes(user_ingredients)` 签名 | Task 5 | Task 7（app.py 调用） | ✅ |
| `increment_match_count(doc_id)` 签名 | Task 6 | Task 7（app.py 调用） | ✅ |
| `get_hot_recipes(limit, days)` 签名 | Task 6 | Task 7（app.py 调用） | ✅ |
| API 响应字段（title/doc_id/chunk_rowid/ingredients/base_spirit/difficulty） | Task 5 返回 | Task 7 响应 | ✅ |

类型一致性全部通过。

---

**Plan complete.** 11 个 Task，覆盖 M3 鸡尾酒实验室全部交付物（5 后端模块 + 1 测试 + 2 前端 + 3 修改），TDD 流程，每 Task 独立 commit。

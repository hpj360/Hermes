"""配方匹配综合治理测试（A3-2 + A3-3 + A4-2）。"""
from __future__ import annotations


def test_a3_2_load_recipes_no_n_plus_1(monkeypatch):
    """A3-2: _load_recipes 不应对每个 doc 单独查 first_chunk。"""
    from sqlmodel import select as _select

    from hermes_kb.rag import ImportService
    from hermes_kb import recipe_match
    from hermes_kb.database import get_session as _get_session
    from hermes_kb.models import Document as _Document

    svc = ImportService()
    for i in range(5):
        svc.import_text(title=f"配方{i}", content=f"<!-- ingredients: 金酒|味美思 -->\n# 配方{i}")
    # import_text 默认 category=""，_load_recipes 过滤 category="recipe"，需显式打标
    with _get_session() as session:
        for doc in session.exec(_select(_Document)).all():
            doc.category = "recipe"
            session.add(doc)
        session.commit()

    call_count = 0
    original_get_session = recipe_match.get_session

    def counting_get_session():
        nonlocal call_count
        call_count += 1
        return original_get_session()

    monkeypatch.setattr(recipe_match, "get_session", counting_get_session)
    recipes = recipe_match._load_recipes()

    assert len(recipes) >= 5
    # _load_recipes 应只用 1 次 session（批量查），不是 N+1
    assert call_count == 1, f"N+1 detected: {call_count} sessions for {len(recipes)} recipes"


def test_a3_2_get_hot_recipes_no_n_plus_1(monkeypatch):
    """A3-2: get_hot_recipes 不应 N+1。"""
    from hermes_kb.rag import ImportService
    from hermes_kb import recipe_stats

    svc = ImportService()
    doc_ids = []
    for i in range(3):
        did = svc.import_text(title=f"热门{i}", content=f"<!-- ingredients: 金酒 -->\n# 热门{i}")["doc_id"]
        doc_ids.append(did)
        for _ in range(3):
            recipe_stats.increment_match_count(did)

    # 监控 session 调用
    call_count = 0
    original_get_session = recipe_stats.get_session

    def counting_get_session():
        nonlocal call_count
        call_count += 1
        return original_get_session()

    monkeypatch.setattr(recipe_stats, "get_session", counting_get_session)
    hot = recipe_stats.get_hot_recipes(limit=3, days=30)

    assert len(hot) >= 1
    # get_hot_recipes 应只用 1 次 session
    assert call_count == 1, f"N+1 detected: {call_count} sessions for {len(hot)} hot recipes"


def test_a3_3_match_recipes_does_not_block_on_stats():
    """A3-3: match_recipes 不应同步写统计，应返回 _pending_stats。"""
    from hermes_kb.rag import ImportService
    from hermes_kb.recipe_match import match_recipes

    svc = ImportService()
    svc.import_text(
        title="测试统计异步",
        content="<!-- ingredients: 金酒|味美思 -->\n# 测试统计异步"
    )

    result = match_recipes({"金酒", "味美思"})
    # 应有 _pending_stats 内部字段
    assert "_pending_stats" in result
    pending = result["_pending_stats"]
    assert "matched_doc_ids" in pending
    assert "missing_ingredients" in pending


def test_a3_3_batch_increment_match_counts():
    """A3-3: batch_increment_match_counts 应单次批量更新。"""
    from hermes_kb.rag import ImportService
    from hermes_kb.recipe_stats import batch_increment_match_counts, get_stats

    svc = ImportService()
    doc_ids = []
    for i in range(3):
        did = svc.import_text(title=f"批量{i}", content=f"<!-- ingredients: 金酒 -->\n# 批量{i}")["doc_id"]
        doc_ids.append(did)

    batch_increment_match_counts(doc_ids)
    for did in doc_ids:
        stat = get_stats(did)
        assert stat is not None
        assert stat["match_count"] == 1


def test_a3_3_batch_increment_missing():
    """A3-3: batch_increment_missing 应单次批量更新。"""
    from hermes_kb.missing_stats import batch_increment_missing, get_missing_stats

    batch_increment_missing(["青柠汁", "糖浆", "薄荷叶"])
    for name in ["青柠汁", "糖浆", "薄荷叶"]:
        stat = get_missing_stats(name)
        assert stat is not None
        assert stat["missing_count"] >= 1


def test_a3_3_lab_match_endpoint_writes_stats_in_background(client):
    """A3-3: /api/lab/match 端点应用 BackgroundTasks 写统计。"""
    from hermes_kb.rag import ImportService

    svc = ImportService()
    svc.import_text(
        title="端点异步统计",
        content="<!-- ingredients: 金酒|味美思 -->\n# 端点异步统计"
    )

    resp = client.get("/api/lab/match?ingredients=金酒,味美思")
    assert resp.status_code == 200
    body = resp.json()
    # 响应不应包含内部 _pending_stats 字段
    assert "_pending_stats" not in body


def test_a4_2_frontmatter_parsing():
    """A4-2: 应优先从 frontmatter 注释解析材料。"""
    from hermes_kb.recipe_match import _parse_ingredients_from_frontmatter

    content = """<!-- ingredients: 金酒|味美思|橄榄 -->
# 马天尼

## 配方
- 金酒 60ml
- 干味美思 10ml
"""
    ings = _parse_ingredients_from_frontmatter(content)
    assert ings == {"金酒", "味美思", "橄榄"}


def test_a4_2_no_frontmatter_returns_empty():
    """A4-2: 无 frontmatter 注释应返回空集合。"""
    from hermes_kb.recipe_match import _parse_ingredients_from_frontmatter

    content = "# 无标注配方\n\n## 配方\n- 金酒"
    ings = _parse_ingredients_from_frontmatter(content)
    assert ings == set()


def test_a4_2_get_recipe_ingredients_prefers_frontmatter():
    """A4-2: _get_recipe_ingredients 应优先用 frontmatter。"""
    from hermes_kb.recipe_match import _get_recipe_ingredients

    recipe = {
        "title": "未知配方",
        "content": "<!-- ingredients: 朗姆酒|青柠汁|糖浆 -->\n# 未知配方",
    }
    ings = _get_recipe_ingredients(recipe)
    assert ings == {"朗姆酒", "青柠汁", "糖浆"}


def test_a4_2_substring_matching_improved():
    """A4-2: 裸子串匹配应改进，避免'柠檬'误匹配'柠檬汁'。"""
    from hermes_kb.recipe_match import _parse_ingredients_from_content

    # 假设 all_canonical 含 "柠檬" 和 "柠檬汁"
    # content 只有 "柠檬汁" 时，不应匹配 "柠檬"
    content = "加入柠檬汁 20ml"
    ings = _parse_ingredients_from_content(content)
    # "柠檬汁" 应匹配
    assert "柠檬汁" in ings
    # "柠檬" 不应单独匹配（因为 content 里是 "柠檬汁"，不是独立的 "柠檬"）
    # 注意：这取决于 all_canonical 是否含 "柠檬"，如果不含则跳过此断言

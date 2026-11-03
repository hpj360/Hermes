"""知识库 OpenViking 能力吸收测试（L0/L1/L2 + 目录递归检索 + 复盘沉淀）。"""
from __future__ import annotations

import pytest

import hermes.skills as skills_mod
from hermes.skills import _strip_frontmatter_block, discover_knowledge

DOC_S = "---\ntitle: 人设\nsummary: 谁在说话\noverview: |\n  人设要点\n  三不原则\ntype: playbook\n---\n\n# 正文\n人设详细规则全文。"


@pytest.fixture
def knowledge_root(monkeypatch, tmp_path):
    root = tmp_path / "knowledge"
    ops = root / "content-ops"
    ops.mkdir(parents=True)
    (ops / "voice.md").write_text(DOC_S, encoding="utf-8")
    (ops / "structures.md").write_text(
        "---\ntitle: 结构库\nsummary: 六个标题机制与结构模板\n---\n\n正文结构说明，"
        "包含清单型与对比型结构。",
        encoding="utf-8",
    )
    (root / "general.md").write_text(
        "---\ntitle: 通用工程知识\nsummary: harness 工程原则\n---\n正文工程知识。",
        encoding="utf-8",
    )
    monkeypatch.setattr(skills_mod, "knowledge_dir", lambda: root)
    return root


def test_discover_knowledge_domains_and_frontmatter(knowledge_root):
    entries = discover_knowledge()
    domains = {e["domain"] for e in entries}
    assert domains == {"content-ops", "general"}
    voice = next(e for e in entries if e["name"] == "content-ops/voice")
    assert voice["title"] == "人设"
    assert voice["summary"] == "谁在说话"
    assert voice["overview"].startswith("人设要点")
    assert voice["type"] == "playbook"


def test_strip_frontmatter_block(knowledge_root):
    body = _strip_frontmatter_block(DOC_S)
    assert body.lstrip().startswith("# 正文")
    assert body.rstrip().endswith("人设详细规则全文。")


def test_discover_knowledge_domain_filter_case_insensitive(knowledge_root):
    assert {e["name"] for e in discover_knowledge("CONTENT-OPS")} == {
        "content-ops/voice",
        "content-ops/structures",
    }


# ---------------------------------------------------------------------------
# 目录递归检索 + 轨迹
# ---------------------------------------------------------------------------


def test_search_knowledge_weighted_hits(knowledge_root):
    from hermes.content_team.knowledge_search import search_knowledge

    entries = discover_knowledge()
    result = search_knowledge("人设 语气 三不原则", entries)
    assert result["docs"], "查人设应命中"
    assert result["docs"][0]["name"] == "content-ops/voice"
    # 轨迹可观察
    trace = result["trace"]
    assert trace["strategy"] == "tfidf_weighted(directory_first)"
    assert trace["indexed_docs"] == 3
    assert trace["elapsed_ms"] >= 0
    # 目录层聚合
    assert result["directories"][0]["domain"] == "content-ops"


def test_search_knowledge_no_match_empty(knowledge_root):
    from hermes.content_team.knowledge_search import search_knowledge

    result = search_knowledge("完全无关的量子力学内容", discover_knowledge())
    qs = result["trace"]
    assert result["docs"] in ([], None) or not result["docs"]
    assert qs["indexed_docs"] == 3


def test_search_knowledge_empty_query(knowledge_root):
    from hermes.content_team.knowledge_search import search_knowledge

    result = search_knowledge("  ", discover_knowledge())
    assert result["docs"] == []
    assert result["trace"]["error"] == "empty query"


# ---------------------------------------------------------------------------
# API：knowledge 目录/检索
# ---------------------------------------------------------------------------


async def test_knowledge_catalog_l0_l1_l2(client, monkeypatch, tmp_path):
    root = tmp_path / "knowledge"
    ops = root / "content-ops"
    ops.mkdir(parents=True)
    (ops / "a.md").write_text(DOC_S, encoding="utf-8")
    import hermes.skills as sk

    monkeypatch.setattr(sk, "knowledge_dir", lambda: root)

    l0 = await client.get("/api/runtime/knowledge?domain=content-ops&load=l0")
    assert l0.status_code == 200
    e = l0.json()["entries"][0]
    assert e["summary"] == "谁在说话"
    assert e["overview"] is None and e["content"] is None

    l1 = await client.get("/api/runtime/knowledge?load=l1&domain=content-ops")
    assert l1.json()["entries"][0]["overview"] is not None
    assert l1.json()["entries"][0]["content"] is None

    l2 = await client.get("/api/runtime/knowledge?load=l2&domain=content-ops")
    body = l2.json()["entries"][0]["content"]
    assert "# 正文" in body


async def test_knowledge_catalog_invalid_load(client):
    resp = await client.get("/api/runtime/knowledge?load=l3")
    assert resp.status_code == 400


async def test_knowledge_search_endpoint(client, monkeypatch, tmp_path):
    root = tmp_path / "knowledge"
    ops = root / "content-ops"
    ops.mkdir(parents=True)
    (ops / "a.md").write_text(DOC_S, encoding="utf-8")
    import hermes.skills as sk

    monkeypatch.setattr(sk, "knowledge_dir", lambda: root)

    resp = await client.get("/api/runtime/knowledge/search?q=人设&top=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trace"]["indexed_docs"] == 1
    assert data["docs"][0]["name"] == "content-ops/a"


async def test_knowledge_search_short_query(client):
    assert (await client.get("/api/runtime/knowledge/search?q=a")).status_code == 422

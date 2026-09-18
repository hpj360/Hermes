"""C6: vault index / search / knowledge card tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes.workbench.notes import NotesStore, _parse_note


@pytest.fixture
def notes_dir(tmp_path: Path) -> Path:
    return tmp_path / "notes"


def _seed(notes_dir: Path) -> NotesStore:
    store = NotesStore(notes_dir)
    store.write(
        "t1",
        "家庭酒吧布置",
        type_="idea",
        body="阳台 2 平米改小酒吧，折叠推车 + 亚克力板。#调酒 #家居",
        created_at="2026-09-01T00:00:00+00:00",
    )
    store.write(
        "t2",
        "威士忌入门",
        type_="link",
        url="https://example.com/whisky",
        body="金汤力零失败配方，新手调酒必看。#调酒 #威士忌",
        created_at="2026-09-02T00:00:00+00:00",
    )
    store.write(
        "t3",
        "成都生活随记",
        type_="fact",
        body="成都的慢生活与仪式感。",
        created_at="2026-09-03T00:00:00+00:00",
    )
    return store


# ---------------------------------------------------------------------------
# parsing / index
# ---------------------------------------------------------------------------


def test_index_parses_entries(notes_dir: Path) -> None:
    store = _seed(notes_dir)
    entries = store.index()
    assert len(entries) == 3
    # newest first
    assert entries[0].title == "成都生活随记"
    by_id = {e.id: e for e in entries}
    assert by_id["t1"].type == "idea"
    assert by_id["t1"].tags == ["调酒", "家居"]
    assert "阳台" in by_id["t1"].snippet
    assert by_id["t2"].url == "https://example.com/whisky"


def test_index_limit(notes_dir: Path) -> None:
    store = _seed(notes_dir)
    assert len(store.index(limit=2)) == 2


def test_parse_note_without_frontmatter(tmp_path: Path) -> None:
    p = tmp_path / "plain.md"
    p.write_text("# 无前置元数据\n\n正文内容", encoding="utf-8")
    entry = _parse_note(p, tmp_path)
    assert entry.title == "无前置元数据"
    assert entry.type == "note"
    assert "正文内容" in entry.snippet


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_matches_title_tag_body_and_ranks(notes_dir: Path) -> None:
    store = _seed(notes_dir)
    results = store.search("调酒")
    ids = [e.id for e in results]
    # t1/t2 have the tag; t3 does not
    assert set(ids) == {"t1", "t2"}
    # keyword in title & tag scores higher than tag-only
    assert store.search("威士忌")[0].id == "t2"


def test_search_empty_query_returns_none(notes_dir: Path) -> None:
    store = _seed(notes_dir)
    assert store.search("") == []
    assert store.search("   ") == []


def test_search_no_match(notes_dir: Path) -> None:
    store = _seed(notes_dir)
    assert store.search("量子物理") == []


# ---------------------------------------------------------------------------
# knowledge card
# ---------------------------------------------------------------------------


def test_knowledge_card_collects_related(notes_dir: Path) -> None:
    store = _seed(notes_dir)
    card = store.knowledge_card(["调酒", "成都"])
    assert card["keywords"] == ["调酒", "成都"]
    assert card["note_count"] >= 2
    ids = {n["id"] for n in card["related_notes"]}
    assert "t1" in ids and "t3" in ids


def test_knowledge_card_respects_limit(notes_dir: Path) -> None:
    store = _seed(notes_dir)
    card = store.knowledge_card(["调酒", "成都", "威士忌"], limit=1)
    assert card["note_count"] == 1


def test_knowledge_card_no_keywords(notes_dir: Path) -> None:
    store = _seed(notes_dir)
    card = store.knowledge_card([])
    assert card["note_count"] == 0


# ---------------------------------------------------------------------------
# routes wired
# ---------------------------------------------------------------------------


def test_c6_routes_registered() -> None:
    from hermes.workbench import server

    names = {h for _m, _p, h in server._ROUTES}
    assert {"h_get_notes", "h_get_notes_search", "h_post_knowledge_card"} <= names


# ---------------------------------------------------------------------------
# gateway endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from hermes.workbench import cli as wb_cli
    from hermes.workbench.gateway import create_app

    notes_dir = tmp_path / "notes"
    _seed(notes_dir)
    monkeypatch.setattr(wb_cli, "_make_notes_dir", lambda: notes_dir)
    monkeypatch.setattr(wb_cli, "_state_dir", lambda: tmp_path / "state")
    wb_cli._reset_scheduler_center()
    center = wb_cli._make_scheduler_center()
    mock_router = MagicMock()
    mock_router.resolve.return_value = MagicMock()
    mock_router.try_acquire.return_value = True
    mock_router.release.return_value = None
    center.router = mock_router

    from fastapi.testclient import TestClient

    with TestClient(create_app()) as client:
        yield client
    wb_cli._reset_scheduler_center()


def test_gateway_notes_index(app) -> None:
    resp = app.get("/wb/notes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["note_count"] == 3
    assert len(data["entries"]) == 3


def test_gateway_notes_search(app) -> None:
    resp = app.get("/wb/notes/search", params={"q": "调酒"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


def test_gateway_notes_search_requires_q(app) -> None:
    resp = app.get("/wb/notes/search")
    assert resp.status_code == 400


def test_gateway_knowledge_card(app) -> None:
    resp = app.post("/wb/knowledge-card", json={"keywords": ["调酒"]})
    assert resp.status_code == 200
    assert resp.json()["note_count"] >= 1


def test_gateway_knowledge_card_validates(app) -> None:
    resp = app.post("/wb/knowledge-card", json={"keywords": "not-a-list"})
    assert resp.status_code == 400

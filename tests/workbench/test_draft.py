"""Tests for generic platform draft generation (workbench.draft)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hermes.workbench.draft import generate_draft


class _FakeResp:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeClient:
    def __init__(self, content: str = "", exc: Exception | None = None) -> None:
        self._content = content
        self._exc = exc

    def chat(self, messages, *, max_tokens=None, **_: object) -> _FakeResp:
        if self._exc is not None:
            raise self._exc
        return _FakeResp(self._content)


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------


def test_generate_draft_parses_llm_json() -> None:
    client = _FakeClient(
        content='{"title": "3步搞定威士忌酸", "body": "第一段\\n\\n第二段", '
        '"hashtags": ["#调酒", "威士忌"]}'
    )
    draft = generate_draft(
        "家庭调酒", "简单易学", ["威士忌", "调酒"], "XIAOHONGSHU", llm_client=client
    )
    assert draft.source == "llm"
    assert draft.title == "3步搞定威士忌酸"
    assert draft.hashtags == ["调酒", "威士忌"]
    assert draft.title_limit == 20


def test_generate_draft_truncates_to_platform_limit() -> None:
    long = "标题" * 40
    client = _FakeClient(content=f'{{"title": "{long}", "body": "正文", "hashtags": []}}')
    draft = generate_draft("t", platform="DOUYIN", llm_client=client)
    assert draft.title_limit == 55
    assert len(draft.title) <= 55


# ---------------------------------------------------------------------------
# fallback path
# ---------------------------------------------------------------------------


def test_generate_draft_falls_back_on_error() -> None:
    draft = generate_draft(
        "家庭调酒", "简单易学", ["威士忌"], "XIAOHONGSHU",
        llm_client=_FakeClient(exc=RuntimeError("boom")),
    )
    assert draft.source == "template"
    assert draft.body
    assert draft.title


def test_generate_draft_falls_back_on_bad_json() -> None:
    draft = generate_draft("t", llm_client=_FakeClient(content="not json"))
    assert draft.source == "template"


def test_generate_draft_platform_keys_case_insensitive() -> None:
    draft = generate_draft("t", "d", ["k"], "douyin")  # lowercase input
    assert draft.platform == "DOUYIN"
    assert draft.title_limit == 55


# ---------------------------------------------------------------------------
# endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path, monkeypatch):
    from hermes.workbench import cli as wb_cli
    from hermes.workbench.gateway import create_app

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


def test_llm_draft_endpoint(app, monkeypatch) -> None:
    from hermes.workbench import draft as draft_mod

    monkeypatch.setattr(
        draft_mod,
        "_default_client",
        lambda: _FakeClient(
            content='{"title": "端点标题", "body": "端点正文", "hashtags": ["x"]}'
        ),
    )
    resp = app.post(
        "/wb/llm/draft",
        json={"title": "选题", "description": "方向", "platform": "XIAOHONGSHU"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "端点标题"
    assert data["source"] == "llm"


def test_llm_draft_endpoint_requires_title(app) -> None:
    resp = app.post("/wb/llm/draft", json={"description": "no title"})
    assert resp.status_code == 400


def test_llm_draft_endpoint_template_fallback(app, monkeypatch) -> None:
    from hermes.workbench import draft as draft_mod

    monkeypatch.setattr(draft_mod, "_default_client", lambda: None)
    resp = app.post("/wb/llm/draft", json={"title": "选题", "keywords": ["调酒"]})
    assert resp.status_code == 200
    assert resp.json()["source"] == "template"

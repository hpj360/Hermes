"""Tests for LLM-driven platform draft generation (content_team.llm_draft)."""
from __future__ import annotations

from hermes.content_team.llm_draft import generate_llm_draft
from hermes.content_team.models.platform import Platform
from hermes.content_team.models.topic import Topic


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeClient:
    """Minimal fake LLM client: either returns fixed content or raises."""

    def __init__(self, content: str = "", exc: Exception | None = None) -> None:
        self._content = content
        self._exc = exc
        self.calls: list[dict] = []

    def chat(self, messages, *, max_tokens=None, **_: object) -> _FakeResponse:
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._content)


def _topic(**kw) -> Topic:
    defaults = {
        "title": "在家调一杯威士忌酸",
        "description": "分享家庭调酒入门，突出简单易学",
        "keywords": ["威士忌", "家庭调酒", "鸡尾酒"],
    }
    defaults.update(kw)
    return Topic(**defaults)


# ---------------------------------------------------------------------------
# 成功路径
# ---------------------------------------------------------------------------


def test_generate_llm_draft_parses_json() -> None:
    """Valid JSON from the model yields a populated Draft."""
    client = _FakeClient(
        content='{"title": "3步搞定威士忌酸", "body": "第一段\\n\\n第二段", '
        '"hashtags": ["家庭调酒", "威士忌"]}'
    )
    draft = generate_llm_draft(_topic(), Platform.XIAOHONGSHU, llm_client=client)
    assert draft.title == "3步搞定威士忌酸"
    assert draft.body.startswith("第一段")
    assert draft.hashtags == ["家庭调酒", "威士忌"]
    assert draft.platform == "XIAOHONGSHU"
    assert draft.title_limit == 20


def test_generate_llm_draft_truncates_long_title() -> None:
    """A title over the platform limit is truncated."""
    long_title = "这是一个非常非常长的标题" * 5
    client = _FakeClient(
        content=f'{{"title": "{long_title}", "body": "正文", "hashtags": []}}'
    )
    draft = generate_llm_draft(_topic(), Platform.XIAOHONGSHU, llm_client=client)
    assert len(draft.title) <= 20


def test_generate_llm_draft_normalizes_hashtags() -> None:
    """Hashtags are stripped of leading '#' and de-duplicated."""
    client = _FakeClient(
        content='{"title": "标题", "body": "正文", '
        '"hashtags": ["#调酒", "调酒", " 威士忌 ", ""]}'
    )
    draft = generate_llm_draft(_topic(), Platform.XIAOHONGSHU, llm_client=client)
    assert draft.hashtags == ["调酒", "威士忌"]


def test_generate_llm_draft_douyin_limit() -> None:
    """Douyin uses its own title limit (55)."""
    client = _FakeClient(
        content='{"title": "抖音标题", "body": "口语化正文", "hashtags": ["调酒"]}'
    )
    draft = generate_llm_draft(_topic(), Platform.DOUYIN, llm_client=client)
    assert draft.platform == "DOUYIN"
    assert draft.title_limit == 55


# ---------------------------------------------------------------------------
# 回退路径
# ---------------------------------------------------------------------------


def test_generate_llm_draft_falls_back_on_error() -> None:
    """Any LLM error degrades to the deterministic template draft."""
    client = _FakeClient(exc=RuntimeError("boom"))
    draft = generate_llm_draft(_topic(), Platform.XIAOHONGSHU, llm_client=client)
    # 模板草稿：标题为选题标题（未超限）
    assert draft.title
    assert "评论区" in draft.body


def test_generate_llm_draft_falls_back_on_bad_json() -> None:
    """Unparseable output degrades to the template draft."""
    client = _FakeClient(content="not json at all")
    draft = generate_llm_draft(_topic(), Platform.XIAOHONGSHU, llm_client=client)
    assert draft.title
    assert "评论区" in draft.body


def test_generate_llm_draft_falls_back_on_missing_fields() -> None:
    """JSON without title/body degrades to the template draft."""
    client = _FakeClient(content='{"hashtags": ["x"]}')
    draft = generate_llm_draft(_topic(), Platform.XIAOHONGSHU, llm_client=client)
    assert draft.title  # template fallback, not empty
    assert "评论区" in draft.body


def test_generate_llm_draft_falls_back_when_no_client(monkeypatch) -> None:
    """No LLM configured → template draft (never raises)."""
    from hermes.content_team import llm_draft

    monkeypatch.setattr(llm_draft, "_default_client", lambda: None)
    draft = generate_llm_draft(_topic(), Platform.XIAOHONGSHU)
    assert draft.title
    assert "评论区" in draft.body


# ---------------------------------------------------------------------------
# API 接线
# ---------------------------------------------------------------------------


async def test_draft_endpoint_use_llm(client, monkeypatch) -> None:
    """POST draft?use_llm=true routes through the LLM generator (mocked)."""
    from hermes.content_team.api import content as content_api
    from hermes.content_team.sop import Draft

    def _fake(topic, platform):
        return Draft(
            title="LLM生成的标题",
            title_candidates=["LLM生成的标题"],
            body="LLM生成的正文",
            hashtags=["调酒"],
            platform=platform.value,
            title_limit=20,
            body_limit=1000,
        )

    monkeypatch.setattr(content_api, "generate_llm_draft", _fake)

    topic = await client.post("/api/topics", json={"title": "选题LLM"})
    tid = topic.json()["id"]
    resp = await client.post(f"/api/topics/{tid}/draft?use_llm=true")
    assert resp.status_code == 200
    assert resp.json()["title"] == "LLM生成的标题"


async def test_draft_endpoint_default_is_template(client) -> None:
    """Default (use_llm omitted) keeps the deterministic template behavior."""
    topic = await client.post("/api/topics", json={"title": "选题模板"})
    tid = topic.json()["id"]
    resp = await client.post(f"/api/topics/{tid}/draft")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"]  # template produced a title
    assert data["platform"] == "XIAOHONGSHU"

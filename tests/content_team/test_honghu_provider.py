"""红狐Hub HTTP 解析层测试（httpx MockTransport，联调加固）。

用 mock 传输验证：请求头/参数组装 + 文档化响应形状的解析容错。
真实契约为占位约定；接入前按红狐Hub文档核对路径（环境变量可配）。
"""
from __future__ import annotations

import httpx
import pytest

from hermes.content_team.trend_sources import HonghuTrendProvider


def _provider_with_transport(monkeypatch, handler) -> HonghuTrendProvider:
    """构建注入 MockTransport 的 Provider（绕过真实网络）。"""
    import httpx

    p = HonghuTrendProvider("https://api.honghu.test", "sk-test")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "hermes.content_team.trend_sources.httpx.AsyncClient",
        lambda **kw: client,
    )
    return p


@pytest.mark.asyncio
async def test_fetch_hot_notes_headers_and_params(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "notes": [
                    {
                        "title": "出租屋小酒馆",
                        "metrics": {"likes": 900, "collects": 300},
                        "author_fans": 1500,
                        "url": "https://xhs.link/abc",
                        "tag": "居家调酒",
                    }
                ]
            },
        )

    p = _provider_with_transport(monkeypatch, handler)
    notes = await p.fetch_hot_notes(keyword="居家调酒", limit=10)

    assert captured["url"].startswith("https://api.honghu.test/v1/xhs/hot-notes")
    assert "keyword=%E5%B1%85%E5%AE%B6%E8%B0%83%E9%85%92" in captured["url"]
    assert "limit=10" in captured["url"]
    assert captured["auth"] == "Bearer sk-test"

    assert len(notes) == 1
    note = notes[0]
    assert note.title == "出租屋小酒馆"
    assert note.likes == 900
    assert note.collects == 300
    assert note.engagement == 1200
    assert note.author_fans == 1500
    assert note.category == "居家调酒"
    assert note.source == "honghu"


@pytest.mark.asyncio
async def test_fetch_hot_notes_flat_field_variant(monkeypatch):
    """宽松字段映射：平铺字段（无 metrics 包裹）同样可解析。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"note_title": "平价清吧平替", "likes": 1500, "comments": 40},
            ],
        )

    p = _provider_with_transport(monkeypatch, handler)
    notes = await p.fetch_hot_notes()
    assert len(notes) == 1
    assert notes[0].title == "平价清吧平替"
    assert notes[0].likes == 1500
    assert notes[0].comments == 40


@pytest.mark.asyncio
async def test_fetch_hot_list_parses_rank_and_heat(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {"rank": 1, "topic": "便利店调酒新喝法", "heat_value": 6510000, "tag": "上升"},
                ]
            },
        )

    p = _provider_with_transport(monkeypatch, handler)
    items = await p.fetch_hot_list()
    assert items[0].rank == 1
    assert items[0].title == "便利店调酒新喝法"
    assert items[0].heat == 6510000
    assert items[0].source == "honghu"


@pytest.mark.asyncio
async def test_fetch_hot_notes_bad_shape_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    p = _provider_with_transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="notes"):
        await p.fetch_hot_notes()


@pytest.mark.asyncio
async def test_fetch_hot_notes_http_error_propagates(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    p = _provider_with_transport(monkeypatch, handler)
    import httpx

    with pytest.raises(httpx.HTTPStatusError):
        await p.fetch_hot_notes()
